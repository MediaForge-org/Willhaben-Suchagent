from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from agent.app.native_messaging.host import HOST_NAME, write_host_manifest


def install(
    project_root: Path,
    python_executable: Path | None,
    home: Path,
    *,
    host_executable: Path | None = None,
) -> tuple[Path, Path]:
    """Install the launcher + manifest.

    By default, the generated launcher runs the host as a Python module
    (source/venv setup: ``python_executable`` + ``host.py``). Pass
    ``host_executable`` to instead wrap a standalone bundled binary (e.g. a
    PyInstaller build) directly — no Python interpreter needed at run time.
    """
    project_root = project_root.expanduser().resolve()
    home = home.expanduser().resolve()

    launcher_directory = home / ".local" / "share" / "willhaben-suchagent" / "native-messaging"
    manifest_directory = home / ".mozilla" / "native-messaging-hosts"
    launcher = launcher_directory / HOST_NAME
    manifest = manifest_directory / f"{HOST_NAME}.json"
    launcher_directory.mkdir(parents=True, exist_ok=True)
    manifest_directory.mkdir(parents=True, exist_ok=True)

    if host_executable is not None:
        host_executable = host_executable.expanduser().absolute()
        launcher_content = f'#!/bin/sh\nexec {shlex.quote(str(host_executable))} "$@"\n'
    else:
        if python_executable is None:
            raise ValueError("python_executable is required unless host_executable is given")
        # Keep a virtual-environment interpreter path intact instead of resolving
        # its symlink to the system Python. The resulting launcher still contains
        # an absolute path and never depends on shell activation.
        python_executable = python_executable.expanduser().absolute()
        host_source = project_root / "agent" / "app" / "native_messaging" / "host.py"
        if not python_executable.is_file():
            raise FileNotFoundError(f"Python-Interpreter nicht gefunden: {python_executable}")
        if not host_source.is_file():
            raise FileNotFoundError(f"Native Host nicht gefunden: {host_source}")
        launcher_content = (
            "#!/bin/sh\n"
            f'exec {shlex.quote(str(python_executable))} {shlex.quote(str(host_source))} "$@"\n'
        )
    temporary_launcher = launcher.with_suffix(".tmp")
    temporary_launcher.write_text(launcher_content, encoding="utf-8")
    temporary_launcher.chmod(0o700)
    temporary_launcher.replace(launcher)
    write_host_manifest(manifest, launcher)
    manifest.chmod(0o600)
    return launcher, manifest


def uninstall(home: Path) -> tuple[Path, Path]:
    home = home.expanduser().resolve()
    launcher = home / ".local" / "share" / "willhaben-suchagent" / "native-messaging" / HOST_NAME
    manifest = home / ".mozilla" / "native-messaging-hosts" / f"{HOST_NAME}.json"
    launcher.unlink(missing_ok=True)
    manifest.unlink(missing_ok=True)
    return launcher, manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the Firefox native messaging bridge")
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--python", type=Path)
    parser.add_argument(
        "--host-executable",
        type=Path,
        default=None,
        help="Wrap this standalone binary directly instead of '<python> host.py'.",
    )
    parser.add_argument("--home", type=Path, default=Path.home())
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.action == "install":
        if args.python is None and args.host_executable is None:
            raise SystemExit("--python or --host-executable is required for install")
        launcher, manifest = install(
            args.project_root, args.python, args.home, host_executable=args.host_executable
        )
        print("Firefox Native-Messaging-Bridge installiert.")
        print(f"Launcher: {launcher}")
        print(f"Host-Manifest: {manifest}")
        print("Firefox vollständig neu starten oder die temporäre Extension neu laden.")
        return 0

    launcher, manifest = uninstall(args.home)
    print("Firefox Native-Messaging-Bridge entfernt.")
    print(f"Entfernt, falls vorhanden: {launcher}")
    print(f"Entfernt, falls vorhanden: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
