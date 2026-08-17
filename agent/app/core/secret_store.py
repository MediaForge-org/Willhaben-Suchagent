"""File-based secret storage, kept strictly separate from SQLite and the API.

Secrets (ntfy token, Discord webhook, SMTP password) live in one JSON file
that is never readable by other local users, never checked into git, and
never echoed back in full through the API or logs.
"""

from __future__ import annotations

import contextlib
import json
import stat
from pathlib import Path


class SecretStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(key): str(value) for key, value in raw.items() if isinstance(value, str)}

    def get(self, key: str) -> str | None:
        return self.load().get(key)

    def set_many(self, values: dict[str, str | None]) -> None:
        """Set or delete (value None/empty) the given keys, preserving the rest."""

        current = self.load()
        for key, value in values.items():
            if value:
                current[key] = value
            else:
                current.pop(key, None)
        self._write(current)

    def seed_defaults(self, values: dict[str, str | None]) -> None:
        """Populate the store from environment fallbacks, but only on first run."""

        if self.path.exists():
            return
        seeded = {key: value for key, value in values.items() if value}
        if seeded:
            self._write(seeded)

    def _write(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            self.path.parent.chmod(stat.S_IRWXU)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with contextlib.suppress(OSError):
            temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temporary.replace(self.path)
