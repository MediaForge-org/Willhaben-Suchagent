"""PyInstaller entry point for the bundled release setup executable.

Wraps the same, already-tested Python setup modules used by the from-source
developer workflow (agent.app.native_messaging.setup_linux/setup_windows and
agent.app.deployment.linux_setup), but points them at the OTHER two bundled
executables in this same runtime/ folder instead of "python -m <module>" — so
a release end user never needs a Python interpreter, pip, or a venv.

Invoked by the release-flavored Einrichtung.sh / Einrichtung.bat, never by
the from-source Einrichtung.sh / Einrichtung.bat (those keep using the venv +
`python -m ...` path unchanged).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _runtime_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _release_root() -> Path:
    """The release package root: the parent of the runtime/ folder that
    contains this very executable.

    Deliberately NOT derived from argv, an inherited --project-root value,
    or the process's current working directory: none of those are reliable
    (cwd is whatever the caller happened to be in; a passed-through path can
    be mangled by shell/argument-quoting on the way here, especially one
    containing spaces). This executable's own on-disk location is the one
    thing that is always correct — after the whole release folder is moved,
    re-running this same executable from its new location automatically
    resolves to the new root.
    """
    return _runtime_dir().parent


def _agent_executable() -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return _runtime_dir() / f"willhaben-suchagent{suffix}"


def _host_executable() -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return _runtime_dir() / f"willhaben-suchagent-host{suffix}"


def _install_linux() -> int:
    project_root = _release_root()
    from agent.app.native_messaging.setup_linux import install as install_native_messaging

    launcher, manifest = install_native_messaging(
        project_root, None, Path.home(), host_executable=_host_executable()
    )
    print(f"Native-Messaging-Bridge installiert: {launcher}")
    print(f"Manifest: {manifest}")

    from agent.app.deployment.linux_setup import install as install_autostart

    status = install_autostart(
        project_root=project_root,
        python_executable=_agent_executable(),
        home=Path.home(),
        agent_executable=_agent_executable(),
    )
    print(f"Autostart eingerichtet: aktiv={status.active} autostart={status.autostart_enabled}")
    return 0


def _uninstall_linux() -> int:
    from agent.app.deployment.linux_setup import uninstall as uninstall_autostart
    from agent.app.native_messaging.setup_linux import uninstall as uninstall_native_messaging

    uninstall_native_messaging(Path.home())
    uninstall_autostart(home=Path.home())
    print("Native-Messaging-Bridge und Autostart entfernt.")
    return 0


def _install_windows() -> int:
    project_root = _release_root()
    from agent.app.native_messaging.setup_windows import install as install_native_messaging

    launcher, manifest = install_native_messaging(
        project_root, None, host_executable=_host_executable()
    )
    print(f"Native-Messaging-Bridge installiert: {launcher}")
    print(f"Manifest: {manifest}")
    return 0


def _uninstall_windows() -> int:
    from agent.app.native_messaging.setup_windows import uninstall as uninstall_native_messaging

    uninstall_native_messaging(_release_root())
    print("Native-Messaging-Bridge entfernt.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Willhaben-Suchagent release setup")
    parser.add_argument(
        "action",
        choices=("install-linux", "uninstall-linux", "install-windows", "uninstall-windows"),
    )
    # Accepted for backwards compatibility with existing Einrichtung.sh/.bat
    # invocations, but intentionally unused for path resolution — see
    # _release_root() for why. Kept optional so a stale/mismatched value can
    # never break setup; a mismatch would only ever indicate the caller
    # invoked the wrong copy of this executable, not a bad argument.
    parser.add_argument("--project-root", type=Path, required=False)
    args = parser.parse_args()

    if args.action == "install-linux":
        return _install_linux()
    if args.action == "uninstall-linux":
        return _uninstall_linux()
    if args.action == "install-windows":
        return _install_windows()
    return _uninstall_windows()


if __name__ == "__main__":
    sys.exit(main())
