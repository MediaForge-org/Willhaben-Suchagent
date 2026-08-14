import io
import wave
from pathlib import Path

import pytest

from agent.app.notifications.sound import (
    SOUND_VARIANTS,
    LinuxDesktopNotificationSoundService,
    _generate_willhaben_sound,
)
from agent.app.storage.database import Database


@pytest.mark.parametrize("sound_id", SOUND_VARIANTS)
def test_each_project_sound_is_deterministic_valid_short_wav(sound_id: str) -> None:
    first = _generate_willhaben_sound(sound_id)
    second = _generate_willhaben_sound(sound_id)

    assert first == second
    assert first.startswith(b"RIFF")
    assert first[8:12] == b"WAVE"
    with wave.open(io.BytesIO(first), "rb") as sound:
        duration = sound.getnframes() / sound.getframerate()
        assert sound.getnchannels() == 1
        assert sound.getsampwidth() == 2
    assert 0.45 <= duration <= 0.8


def test_project_exposes_only_the_three_new_sound_variants() -> None:
    assert [(variant.id, variant.name) for variant in SOUND_VARIANTS.values()] == [
        ("notify", "Notify"),
        ("ping", "Ping"),
        ("pop", "Pop"),
    ]


def test_all_project_sound_variants_are_distinct() -> None:
    generated = {_generate_willhaben_sound(sound_id) for sound_id in SOUND_VARIANTS}

    assert len(generated) == len(SOUND_VARIANTS)


def test_generated_sounds_are_peak_normalized_without_clipping() -> None:
    peaks: list[int] = []
    for sound_id in SOUND_VARIANTS:
        with wave.open(io.BytesIO(_generate_willhaben_sound(sound_id)), "rb") as sound:
            frames = sound.readframes(sound.getnframes())
        samples = [
            int.from_bytes(frames[index : index + 2], "little", signed=True)
            for index in range(0, len(frames), 2)
        ]
        peaks.append(max(abs(sample) for sample in samples))
        assert samples[0] == 0
        assert samples[-1] == 0

    assert all(22_275 <= peak <= 22_283 for peak in peaks)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "legacy_id",
    ["signal", "beacon", "pulse", "chime", "glass", "rise", "soft"],
)
async def test_legacy_sound_ids_migrate_to_new_default(
    tmp_path: Path,
    legacy_id: str,
) -> None:
    database = Database(tmp_path / "legacy-sound.db")
    await database.initialize()
    await database.raw_execute(
        "UPDATE agent_settings SET value = ? WHERE key = 'desktop_sound_id'",
        (legacy_id,),
    )

    await database.initialize()

    assert (await database.get_desktop_sound_preferences()).sound_id == "notify"


def test_linux_sound_service_is_explicitly_disabled(tmp_path: Path) -> None:
    service = LinuxDesktopNotificationSoundService(
        enabled=False,
        cache_directory=tmp_path,
    )

    assert service.enabled is False
    assert service.available is False
    assert service.disabled_reason == "Desktop sound is disabled"
