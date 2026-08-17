"""Windows Firefox native-messaging setup: HKCU registry + a generated launcher.

Firefox on Windows discovers a native messaging host through a registry value
under HKEY_CURRENT_USER (no administrator rights needed) whose default value
is the absolute path to the host's JSON manifest. That manifest's own "path"
field points at a small generated .bat launcher, which in turn calls the
venv's python.exe with an absolute path to host.py.

Both the registry value and the manifest are recomputed from the CURRENT
program folder location every time setup runs, so moving the whole folder and
re-running setup is all that's needed after a relocation — nothing here is
hardcoded to a specific install path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Protocol

from agent.app.native_messaging.host import HOST_NAME, write_host_manifest

REGISTRY_KEY_PATH = f"Software\\Mozilla\\NativeMessagingHosts\\{HOST_NAME}"


class RegistryWriter(Protocol):
    def set_default_value(self, key_path: str, value: str) -> None: ...

    def delete_key(self, key_path: str) -> None: ...


class _WinregWriter:
    def set_default_value(self, key_path: str, value: str) -> None:
        import winreg

        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        try:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
        finally:
            winreg.CloseKey(key)

    def delete_key(self, key_path: str) -> None:
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except FileNotFoundError:
            pass


def _default_registry_writer() -> RegistryWriter:
    if sys.platform != "win32":
        raise RuntimeError("Windows native-messaging setup requires Windows")
    return _WinregWriter()


def native_messaging_dir(project_root: Path) -> Path:
    return project_root / "native-messaging"


def manifest_path(project_root: Path) -> Path:
    return native_messaging_dir(project_root) / f"{HOST_NAME}.json"


def launcher_path(project_root: Path) -> Path:
    return native_messaging_dir(project_root) / f"{HOST_NAME}.bat"


def install(
    project_root: Path,
    python_executable: Path | None,
    *,
    registry_writer: RegistryWriter | None = None,
    host_executable: Path | None = None,
) -> tuple[Path, Path]:
    """Install the launcher + manifest + registry value.

    By default, the generated launcher runs the host as a Python module
    (source/venv setup: ``python_executable`` + ``host.py``). Pass
    ``host_executable`` to instead wrap a standalone bundled binary (e.g. a
    PyInstaller build) directly — no Python interpreter needed at run time.
    """
    project_root = project_root.expanduser().resolve()
    launcher = launcher_path(project_root)
    manifest = manifest_path(project_root)
    launcher.parent.mkdir(parents=True, exist_ok=True)

    if host_executable is not None:
        host_executable = host_executable.expanduser().absolute()
        launcher_content = f'@echo off\r\n"{host_executable}" %*\r\n'
    else:
        if python_executable is None:
            raise ValueError("python_executable is required unless host_executable is given")
        python_executable = python_executable.expanduser().absolute()
        host_source = project_root / "agent" / "app" / "native_messaging" / "host.py"
        if not host_source.is_file():
            raise FileNotFoundError(f"Native Host nicht gefunden: {host_source}")
        launcher_content = f'@echo off\r\n"{python_executable}" "{host_source}" %*\r\n'
    launcher.write_text(launcher_content, encoding="utf-8", newline="")

    write_host_manifest(manifest, launcher)

    writer = registry_writer or _default_registry_writer()
    writer.set_default_value(REGISTRY_KEY_PATH, str(manifest))
    return launcher, manifest


def uninstall(
    project_root: Path,
    *,
    registry_writer: RegistryWriter | None = None,
) -> tuple[Path, Path]:
    project_root = project_root.expanduser().resolve()
    launcher = launcher_path(project_root)
    manifest = manifest_path(project_root)
    launcher.unlink(missing_ok=True)
    manifest.unlink(missing_ok=True)
    writer = registry_writer or _default_registry_writer()
    writer.delete_key(REGISTRY_KEY_PATH)
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
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.action == "install":
        if args.python is None and args.host_executable is None:
            raise SystemExit("--python or --host-executable is required for install")
        launcher, manifest = install(
            args.project_root, args.python, host_executable=args.host_executable
        )
        print("Firefox Native-Messaging-Bridge installiert.")
        print(f"Launcher: {launcher}")
        print(f"Host-Manifest: {manifest}")
        print("Firefox vollständig neu starten oder die temporäre Extension neu laden.")
        return 0

    launcher, manifest = uninstall(args.project_root)
    print("Firefox Native-Messaging-Bridge entfernt.")
    print(f"Entfernt, falls vorhanden: {launcher}")
    print(f"Entfernt, falls vorhanden: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
