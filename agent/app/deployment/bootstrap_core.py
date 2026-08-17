"""Portable, dependency-free runtime bootstrap for end-user installs.

This module deliberately uses only the standard library: it must run with the
bare system Python, before any project dependency (or even the project itself)
is importable. It creates/updates the local ".venv" next to the program folder
(wherever that folder currently lives) and installs *runtime* dependencies only
— never the "dev" extra (pytest, Ruff), which a normal user never needs.

All subprocess calls go through an injectable `CommandRunner` so tests can
verify behaviour without ever invoking a real interpreter, pip, or network.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

MINIMUM_PYTHON = (3, 12)
MAXIMUM_PYTHON = (4, 0)
VENV_DIR_NAME = ".venv"


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str]], CommandResult]


class BootstrapError(RuntimeError):
    """A friendly, user-facing bootstrap failure (never a raw traceback)."""


def _default_runner(command: Sequence[str]) -> CommandResult:
    completed = subprocess.run(  # noqa: S603
        list(command),
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def venv_dir(project_root: Path) -> Path:
    return project_root / VENV_DIR_NAME


def venv_python(project_root: Path) -> Path:
    base = venv_dir(project_root)
    if sys.platform == "win32":
        return base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def candidate_python_executables() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("py -3.13", "py -3.12", "py", "python")
    return ("python3.13", "python3.12", "python3", "python")


def _parse_version(output: str) -> tuple[int, int] | None:
    # "Python 3.12.4" -> (3, 12)
    parts = output.strip().split()
    if len(parts) < 2:
        return None
    version_parts = parts[1].split(".")
    if len(version_parts) < 2:
        return None
    try:
        return int(version_parts[0]), int(version_parts[1])
    except ValueError:
        return None


def find_compatible_python(*, runner: CommandRunner | None = None) -> str:
    """Find a usable "python" command, preferring the newest compatible version."""

    resolved_runner = runner or _default_runner
    for candidate in candidate_python_executables():
        command = candidate.split()
        if shutil.which(command[0]) is None and runner is None:
            continue
        result = resolved_runner([*command, "--version"])
        if result.returncode != 0:
            continue
        version = _parse_version(result.stdout or result.stderr)
        if version is None:
            continue
        if MINIMUM_PYTHON <= version < MAXIMUM_PYTHON:
            return candidate
    raise BootstrapError(
        "Es wurde keine passende Python-Version (>= "
        f"{MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}) gefunden. "
        "Bitte installiere Python und starte die Einrichtung erneut."
    )


def ensure_venv(
    project_root: Path,
    python_command: str,
    *,
    runner: CommandRunner | None = None,
) -> bool:
    """Create the local venv if missing. Returns True if it was just created."""

    resolved_runner = runner or _default_runner
    target = venv_dir(project_root)
    if venv_python(project_root).exists():
        return False
    result = resolved_runner([*python_command.split(), "-m", "venv", str(target)])
    if result.returncode != 0:
        raise BootstrapError(
            "Die lokale Python-Umgebung (.venv) konnte nicht erstellt werden. "
            "Prüfe, ob genügend Speicherplatz und Rechte für den Programmordner vorhanden sind."
        )
    return True


def install_runtime_dependencies(
    project_root: Path,
    *,
    runner: CommandRunner | None = None,
) -> None:
    """Install only the runtime dependency set (never the 'dev' extra)."""

    resolved_runner = runner or _default_runner
    python = venv_python(project_root)
    result = resolved_runner(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-e",
            str(project_root),
        ]
    )
    if result.returncode != 0:
        combined = f"{result.stdout}\n{result.stderr}".lower()
        network_markers = (
            "temporary failure",
            "could not fetch url",
            "connection",
            "network",
            "timed out",
            "name or service not known",
        )
        if any(marker in combined for marker in network_markers):
            raise BootstrapError(
                "Für die Ersteinrichtung wird eine Internetverbindung benötigt, "
                "um Programmbibliotheken herunterzuladen. Bitte Internetverbindung "
                "prüfen und die Einrichtung erneut starten."
            )
        raise BootstrapError(
            "Die Programmbibliotheken konnten nicht installiert werden. "
            "Bitte die Einrichtung erneut starten; falls der Fehler bestehen "
            "bleibt, wende dich mit den Details der Fehlermeldung an den Support."
        )


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    venv_created: bool
    python_command: str
    venv_python_path: Path


def ensure_env_file(project_root: Path) -> Path:
    """Point the app at the platform-standard data directory, without ever
    touching an existing .env — a development install keeps working exactly
    as before, and a prior production install never loses its pointer."""

    from agent.app.core.paths import default_data_dir

    env_path = project_root / ".env"
    if not env_path.exists():
        data_dir = default_data_dir()
        env_path.write_text(
            f"WILLHABEN_DATABASE_PATH={data_dir / 'willhaben_suchagent.db'}\n"
            f"WILLHABEN_SECRET_STORE_PATH={data_dir / 'secrets.json'}\n",
            encoding="utf-8",
        )
    return env_path


def bootstrap(
    project_root: Path,
    *,
    runner: CommandRunner | None = None,
) -> BootstrapResult:
    """Idempotent end-to-end bootstrap: find Python, create venv, install deps."""

    project_root = project_root.expanduser().resolve()
    python_command = find_compatible_python(runner=runner)
    venv_created = ensure_venv(project_root, python_command, runner=runner)
    install_runtime_dependencies(project_root, runner=runner)
    ensure_env_file(project_root)
    return BootstrapResult(
        venv_created=venv_created,
        python_command=python_command,
        venv_python_path=venv_python(project_root),
    )


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Bootstrap the Willhaben-Suchagent runtime")
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = bootstrap(args.project_root)
    except BootstrapError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    print("Laufzeitumgebung bereit.")
    print(f"Python: {result.python_command}")
    print(f"venv: {result.venv_python_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
