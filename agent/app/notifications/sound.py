from __future__ import annotations

import asyncio
import io
import logging
import math
import os
import shutil
import struct
import sys
import tempfile
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SOUND_ID = "notify"


@dataclass(frozen=True, slots=True)
class SoundVariant:
    id: str
    name: str


SOUND_VARIANTS: dict[str, SoundVariant] = {
    "notify": SoundVariant("notify", "Notify"),
    "ping": SoundVariant("ping", "Ping"),
    "pop": SoundVariant("pop", "Pop"),
}


class DesktopNotificationSoundService(ABC):
    """Provider-independent local sound capability used by the scheduler."""

    enabled: bool
    sound_id: str
    available: bool
    disabled_reason: str | None

    @abstractmethod
    def configure(self, *, enabled: bool, sound_id: str) -> None:
        """Apply already validated persistent preferences without restarting."""

    @abstractmethod
    async def play_new_listing_chime(self) -> bool:
        """Play the configured sound for a genuinely new-listing cycle."""

    @abstractmethod
    async def preview(self, sound_id: str) -> bool:
        """Play one explicitly requested built-in sound for the settings UI."""


class NullDesktopNotificationSoundService(DesktopNotificationSoundService):
    def __init__(self, reason: str = "Desktop sound is not configured") -> None:
        self.enabled = False
        self.sound_id = DEFAULT_SOUND_ID
        self.available = False
        self.disabled_reason = reason

    def configure(self, *, enabled: bool, sound_id: str) -> None:
        _require_sound_id(sound_id)
        self.enabled = enabled
        self.sound_id = sound_id

    async def play_new_listing_chime(self) -> bool:
        return False

    async def preview(self, sound_id: str) -> bool:
        _require_sound_id(sound_id)
        return False


class FakeDesktopNotificationSoundService(DesktopNotificationSoundService):
    def __init__(
        self,
        *,
        enabled: bool = True,
        sound_id: str = DEFAULT_SOUND_ID,
        failing: bool = False,
        available: bool = True,
    ) -> None:
        _require_sound_id(sound_id)
        self.enabled = enabled
        self.sound_id = sound_id
        self.available = available
        self.disabled_reason = None if available else "Desktop sound is unavailable"
        self.failing = failing
        self.play_count = 0
        self.preview_count = 0
        self.previewed_sound_ids: list[str] = []

    def configure(self, *, enabled: bool, sound_id: str) -> None:
        _require_sound_id(sound_id)
        self.enabled = enabled
        self.sound_id = sound_id

    async def play_new_listing_chime(self) -> bool:
        if not self.enabled:
            return False
        self.play_count += 1
        if self.failing:
            raise RuntimeError("simulated desktop sound failure")
        return self.available

    async def preview(self, sound_id: str) -> bool:
        _require_sound_id(sound_id)
        self.preview_count += 1
        self.previewed_sound_ids.append(sound_id)
        if self.failing:
            raise RuntimeError("simulated desktop sound failure")
        return self.available


class LinuxDesktopNotificationSoundService(DesktopNotificationSoundService):
    """Play project-owned synthesized WAV files through the local desktop stack."""

    _PLAYER_CANDIDATES = (
        ("pw-play", ()),
        ("paplay", ()),
        ("aplay", ("-q",)),
    )

    def __init__(
        self,
        *,
        enabled: bool,
        sound_id: str = DEFAULT_SOUND_ID,
        cache_directory: Path | None = None,
    ) -> None:
        _require_sound_id(sound_id)
        self.enabled = enabled
        self.sound_id = sound_id
        self._player = self._find_player() if enabled else None
        self.available = self._player is not None
        self.disabled_reason = self._disabled_reason()
        self._cache_directory = cache_directory or _default_cache_directory()

    def configure(self, *, enabled: bool, sound_id: str) -> None:
        _require_sound_id(sound_id)
        self.enabled = enabled
        self.sound_id = sound_id
        if enabled and self._player is None:
            self._player = self._find_player()
        self.available = self._player is not None
        self.disabled_reason = self._disabled_reason()

    def _disabled_reason(self) -> str | None:
        if not self.enabled:
            return "Desktop sound is disabled"
        if self._player is None:
            return "No supported desktop audio player was found"
        return None

    @classmethod
    def _find_player(cls) -> tuple[str, tuple[str, ...]] | None:
        for executable, arguments in cls._PLAYER_CANDIDATES:
            resolved = shutil.which(executable)
            if resolved:
                return resolved, arguments
        return None

    async def play_new_listing_chime(self) -> bool:
        if not self.enabled:
            logger.info("desktop_sound_skipped reason=%s", self.disabled_reason)
            return False
        return await self._play(self.sound_id)

    async def preview(self, sound_id: str) -> bool:
        _require_sound_id(sound_id)
        return await self._play(sound_id)

    async def _play(self, sound_id: str) -> bool:
        if self._player is None:
            # Preview is an explicit user action and remains useful while automatic
            # notifications are disabled. Resolve the player lazily in that case.
            self._player = self._find_player()
            self.available = self._player is not None
        if self._player is None:
            logger.info("desktop_sound_skipped reason=%s", self.disabled_reason)
            return False
        try:
            sound_path = self._ensure_sound_file(sound_id)
            executable, arguments = self._player
            process = await asyncio.create_subprocess_exec(
                executable,
                *arguments,
                str(sound_path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                return_code = await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
                logger.warning("desktop_sound_failed error=PlaybackTimeout")
                return False
            if return_code != 0:
                logger.warning("desktop_sound_failed error=PlayerExitCode code=%s", return_code)
                return False
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("desktop_sound_failed error=%s", type(error).__name__)
            return False
        logger.info("desktop_sound_played sound_id=%s", sound_id)
        return True

    def _ensure_sound_file(self, sound_id: str) -> Path:
        expected = _generate_willhaben_sound(sound_id)
        sound_path = self._cache_directory / f"willhaben-{sound_id}-v5.wav"
        if sound_path.is_file() and sound_path.stat().st_size == len(expected):
            return sound_path
        self._cache_directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"willhaben-{sound_id}-",
            suffix=".tmp",
            dir=self._cache_directory,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(expected)
            temporary.chmod(0o600)
            temporary.replace(sound_path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return sound_path


def create_desktop_sound_service(
    *,
    enabled: bool,
    sound_id: str = DEFAULT_SOUND_ID,
) -> DesktopNotificationSoundService:
    if sys.platform.startswith("linux"):
        return LinuxDesktopNotificationSoundService(enabled=enabled, sound_id=sound_id)
    return NullDesktopNotificationSoundService("Desktop sound is unsupported on this platform")


def _require_sound_id(sound_id: str) -> None:
    if sound_id not in SOUND_VARIANTS:
        raise ValueError(f"Unsupported desktop sound id: {sound_id}")


def _default_cache_directory() -> Path:
    cache_root = os.environ.get("XDG_CACHE_HOME")
    return (
        Path(cache_root).expanduser() if cache_root else Path.home() / ".cache"
    ) / "willhaben-suchagent"


def _generate_willhaben_sound(sound_id: str) -> bytes:
    """Generate one layered, normalized and fully original notification sound."""

    _require_sound_id(sound_id)
    sample_rate = 44_100
    generators = {
        "notify": _notify_samples,
        "ping": _ping_samples,
        "pop": _pop_samples,
    }
    samples = generators[sound_id](sample_rate)
    return _wav_bytes(_normalize(samples), sample_rate)


def _generate_willhaben_chime() -> bytes:
    """Backward-compatible name for the default synthesized notification sound."""

    return _generate_willhaben_sound(DEFAULT_SOUND_ID)


def _notify_samples(sample_rate: int) -> list[float]:
    """Compact friendly two-event digital chime with a lightly bouncing contour."""

    samples = _silence(sample_rate, 0.64)
    _add_transient(samples, sample_rate, start=0.010, duration=0.030, gain=0.038)
    _add_tone(
        samples,
        sample_rate,
        start=0.014,
        duration=0.235,
        frequency=500.0,
        end_frequency=528.0,
        gain=0.52,
        partials=((1.0, 1.0), (2.0, 0.070), (3.0, 0.012), (0.5, 0.075)),
        attack=0.006,
        release=0.115,
        decay=1.25,
    )
    _add_tone(
        samples,
        sample_rate,
        start=0.164,
        duration=0.420,
        frequency=670.0,
        end_frequency=654.0,
        gain=0.62,
        partials=((1.0, 1.0), (2.0, 0.060), (3.0, 0.010), (0.5, 0.080)),
        attack=0.008,
        release=0.175,
        decay=1.0,
    )
    return samples


def _ping_samples(sample_rate: int) -> list[float]:
    """A glassier first ping followed by a softer, warmer closing event."""

    samples = _silence(sample_rate, 0.70)
    _add_transient(samples, sample_rate, start=0.008, duration=0.026, gain=0.032)
    _add_tone(
        samples,
        sample_rate,
        start=0.012,
        duration=0.305,
        frequency=1127.0,
        end_frequency=1095.0,
        gain=0.43,
        partials=((1.0, 1.0), (2.018, 0.17), (3.07, 0.038)),
        attack=0.004,
        release=0.165,
        decay=1.75,
    )
    _add_tone(
        samples,
        sample_rate,
        start=0.220,
        duration=0.415,
        frequency=742.0,
        end_frequency=754.0,
        gain=0.50,
        partials=((1.0, 1.0), (2.0, 0.065), (0.5, 0.055)),
        attack=0.012,
        release=0.185,
        decay=1.15,
    )
    return samples


def _pop_samples(sample_rate: int) -> list[float]:
    """Round digital impulse with a short, more assertive closing note."""

    samples = _silence(sample_rate, 0.56)
    _add_transient(samples, sample_rate, start=0.007, duration=0.050, gain=0.095)
    _add_tone(
        samples,
        sample_rate,
        start=0.010,
        duration=0.190,
        frequency=310.0,
        end_frequency=205.0,
        gain=0.48,
        partials=((1.0, 1.0), (2.0, 0.075)),
        attack=0.003,
        release=0.090,
        decay=1.5,
    )
    _add_tone(
        samples,
        sample_rate,
        start=0.118,
        duration=0.370,
        frequency=783.0,
        end_frequency=806.0,
        gain=0.58,
        partials=((1.0, 1.0), (2.0, 0.105), (3.0, 0.018), (0.5, 0.050)),
        attack=0.008,
        release=0.150,
        decay=1.1,
    )
    return samples


def _silence(sample_rate: int, duration: float) -> list[float]:
    return [0.0] * round(sample_rate * duration)


def _add_tone(
    samples: list[float],
    sample_rate: int,
    *,
    start: float,
    duration: float,
    frequency: float,
    gain: float,
    partials: tuple[tuple[float, float], ...],
    attack: float,
    release: float,
    decay: float,
    end_frequency: float | None = None,
) -> None:
    start_index = round(start * sample_rate)
    count = min(round(duration * sample_rate), len(samples) - start_index)
    phase = 0.0
    for index in range(max(0, count)):
        progress = index / max(1, count - 1)
        current_frequency = frequency + ((end_frequency or frequency) - frequency) * progress
        phase += 2 * math.pi * current_frequency / sample_rate
        envelope = _smooth_envelope(
            index,
            count,
            sample_rate,
            attack=attack,
            release=release,
        ) * math.exp(-decay * progress)
        layered = sum(partial_gain * math.sin(phase * ratio) for ratio, partial_gain in partials)
        samples[start_index + index] += gain * envelope * layered


def _add_transient(
    samples: list[float],
    sample_rate: int,
    *,
    start: float,
    duration: float,
    gain: float,
) -> None:
    start_index = round(start * sample_rate)
    count = min(round(duration * sample_rate), len(samples) - start_index)
    filtered = 0.0
    for index in range(max(0, count)):
        # Deterministic synthesized noise, softly low-pass filtered and faded.
        raw = math.sin((index + 1) * 12.9898) * 43_758.5453
        noise = 2 * (raw - math.floor(raw)) - 1
        filtered = 0.22 * noise + 0.78 * filtered
        progress = index / max(1, count - 1)
        envelope = math.sin(math.pi * min(1.0, progress / 0.12) / 2) ** 2
        envelope *= (1 - progress) ** 3
        samples[start_index + index] += gain * envelope * filtered


def _smooth_envelope(
    index: int,
    count: int,
    sample_rate: int,
    *,
    attack: float,
    release: float,
) -> float:
    attack_samples = max(1, round(sample_rate * attack))
    release_samples = max(1, round(sample_rate * release))
    attack_progress = min(1.0, index / attack_samples)
    release_progress = min(1.0, (count - index - 1) / release_samples)
    attack_gain = math.sin(attack_progress * math.pi / 2) ** 2
    release_gain = math.sin(release_progress * math.pi / 2) ** 2
    return attack_gain * release_gain


def _normalize(samples: list[float], target_peak: float = 0.68) -> list[int]:
    peak = max((abs(sample) for sample in samples), default=0.0)
    if peak == 0:
        return [0] * len(samples)
    scale = target_peak * 32_767 / peak
    return [max(-32_767, min(32_767, round(sample * scale))) for sample in samples]


def _wav_bytes(samples: list[int], sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(sample_rate)
        sound.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
    return buffer.getvalue()
