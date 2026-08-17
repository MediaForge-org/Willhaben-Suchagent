"""systemd --user autostart for Linux, entirely optional and never sudo.

Everything here is computed from the CURRENT program folder location and the
CURRENT venv interpreter — moving the whole folder and re-running install()
regenerates a unit file with the new absolute paths. All process calls go
through an injectable CommandRunner so tests never touch the real user's
systemd.
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent.app.core.paths import default_config_dir, default_data_dir

SERVICE_NAME = "willhaben-suchagent.service"


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str]], CommandResult]


def _default_runner(command: Sequence[str]) -> CommandResult:
    completed = subprocess.run(  # noqa: S603
        list(command), capture_output=True, text=True, check=False
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def service_unit_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / SERVICE_NAME


def render_service_unit(
    *,
    project_root: Path,
    python_executable: Path,
    config_dir: Path | None = None,
    data_dir: Path | None = None,
    agent_executable: Path | None = None,
) -> str:
    """Render the unit file.

    By default ExecStart runs the agent as a Python module (source/venv
    setup). Pass ``agent_executable`` to instead run a standalone bundled
    binary (e.g. a PyInstaller build) directly, with no Python interpreter
    involved at run time.
    """
    project_root = project_root.expanduser().resolve()
    python_executable = python_executable.expanduser().absolute()
    config_dir = config_dir or default_config_dir()
    data_dir = data_dir or default_data_dir()
    exec_start = (
        f'"{agent_executable.expanduser().absolute()}"'
        if agent_executable is not None
        else f'"{python_executable}" -m agent.app.main'
    )
    return (
        "[Unit]\n"
        "Description=Willhaben-Suchagent (Hintergrunddienst)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "StartLimitIntervalSec=120\n"
        "StartLimitBurst=5\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={project_root}\n"
        f'Environment="WILLHABEN_DATABASE_PATH={data_dir / "willhaben_suchagent.db"}"\n'
        f'Environment="WILLHABEN_SECRET_STORE_PATH={data_dir / "secrets.json"}"\n'
        f"EnvironmentFile=-{config_dir / 'agent.env'}\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def write_service_unit(
    *,
    project_root: Path,
    python_executable: Path,
    home: Path,
    config_dir: Path | None = None,
    data_dir: Path | None = None,
    agent_executable: Path | None = None,
) -> Path:
    unit_path = service_unit_path(home)
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    content = render_service_unit(
        project_root=project_root,
        python_executable=python_executable,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_executable=agent_executable,
    )
    temporary = unit_path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(unit_path)
    return unit_path


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    installed: bool
    active: bool
    autostart_enabled: bool


def query_service_status(*, home: Path, runner: CommandRunner | None = None) -> ServiceStatus:
    resolved_runner = runner or _default_runner
    installed = service_unit_path(home).is_file()
    if not installed:
        return ServiceStatus(installed=False, active=False, autostart_enabled=False)
    active_result = resolved_runner(["systemctl", "--user", "is-active", SERVICE_NAME])
    enabled_result = resolved_runner(["systemctl", "--user", "is-enabled", SERVICE_NAME])
    return ServiceStatus(
        installed=True,
        active=active_result.stdout.strip() == "active",
        autostart_enabled=enabled_result.stdout.strip() == "enabled",
    )


def install(
    *,
    project_root: Path,
    python_executable: Path,
    home: Path,
    runner: CommandRunner | None = None,
    config_dir: Path | None = None,
    data_dir: Path | None = None,
    agent_executable: Path | None = None,
) -> ServiceStatus:
    resolved_runner = runner or _default_runner
    resolved_config_dir = config_dir or default_config_dir()
    resolved_data_dir = data_dir or default_data_dir()
    resolved_config_dir.mkdir(parents=True, exist_ok=True)
    resolved_data_dir.mkdir(parents=True, exist_ok=True)

    write_service_unit(
        project_root=project_root,
        python_executable=python_executable,
        home=home,
        config_dir=resolved_config_dir,
        data_dir=resolved_data_dir,
        agent_executable=agent_executable,
    )
    resolved_runner(["systemctl", "--user", "daemon-reload"])
    resolved_runner(["systemctl", "--user", "enable", "--now", SERVICE_NAME])
    return query_service_status(home=home, runner=resolved_runner)


def uninstall(*, home: Path, runner: CommandRunner | None = None) -> None:
    resolved_runner = runner or _default_runner
    resolved_runner(["systemctl", "--user", "disable", "--now", SERVICE_NAME])
    service_unit_path(home).unlink(missing_ok=True)
    resolved_runner(["systemctl", "--user", "daemon-reload"])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage the Willhaben-Suchagent user service")
    parser.add_argument("action", choices=("install", "uninstall", "status"))
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument(
        "--agent-executable",
        type=Path,
        default=None,
        help="Run this standalone binary directly instead of '<python> -m agent.app.main'.",
    )
    parser.add_argument("--home", type=Path, default=Path.home())
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.action == "install":
        if args.project_root is None or (args.python is None and args.agent_executable is None):
            raise SystemExit("--project-root and --python (or --agent-executable) are required")
        result = install(
            project_root=args.project_root,
            python_executable=args.python or args.agent_executable,
            home=args.home,
            agent_executable=args.agent_executable,
        )
        active_label = "aktiv" if result.active else "nicht aktiv"
        enabled_label = "aktiviert" if result.autostart_enabled else "nicht aktiviert"
        print(f"Hintergrunddienst installiert=True aktiv={active_label} autostart={enabled_label}")
        return 0
    if args.action == "uninstall":
        uninstall(home=args.home)
        print("Hintergrunddienst entfernt.")
        return 0
    result = query_service_status(home=args.home)
    print(
        f"installiert={result.installed} aktiv={result.active} autostart={result.autostart_enabled}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
