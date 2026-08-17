from __future__ import annotations

from pathlib import Path

from agent.app.deployment.linux_setup import (
    SERVICE_NAME,
    CommandResult,
    install,
    query_service_status,
    render_service_unit,
    service_unit_path,
    uninstall,
)


class RecordingRunner:
    def __init__(self, responses: dict[str, CommandResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._responses = responses or {}

    def __call__(self, command: list[str]) -> CommandResult:
        self.calls.append(list(command))
        key = " ".join(command)
        for pattern, result in self._responses.items():
            if pattern in key:
                return result
        return CommandResult(0, "", "")


def test_render_service_unit_has_crash_recovery_and_no_hardcoded_dev_path(tmp_path: Path) -> None:
    project_root = tmp_path / "Programme" / "Willhaben-Suchagent"
    python_executable = project_root / ".venv" / "bin" / "python"

    content = render_service_unit(
        project_root=project_root,
        python_executable=python_executable,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )

    assert "Restart=on-failure" in content
    assert "RestartSec=5" in content
    assert "StartLimitBurst=" in content
    assert str(project_root) in content
    assert "/mnt/Festplatte/Schreibtisch/Projekte/Willhaben-Suchagent" not in content


def test_install_writes_unit_and_enables_service_without_sudo(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project_root = tmp_path / "project"
    python_executable = project_root / ".venv" / "bin" / "python"
    runner = RecordingRunner(
        {
            "is-active": CommandResult(0, "active\n", ""),
            "is-enabled": CommandResult(0, "enabled\n", ""),
        }
    )

    result = install(
        project_root=project_root,
        python_executable=python_executable,
        home=home,
        runner=runner,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )

    assert service_unit_path(home).is_file()
    assert result.active is True
    assert result.autostart_enabled is True
    assert all("sudo" not in " ".join(call) for call in runner.calls)
    assert any("daemon-reload" in " ".join(call) for call in runner.calls)
    assert any("enable" in call for call in runner.calls)


def test_query_service_status_reports_not_installed_when_no_unit_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    runner = RecordingRunner()

    result = query_service_status(home=home, runner=runner)

    assert result.installed is False
    assert result.active is False
    assert runner.calls == []


def test_uninstall_removes_unit_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project_root = tmp_path / "project"
    python_executable = project_root / ".venv" / "bin" / "python"
    runner = RecordingRunner()
    install(
        project_root=project_root,
        python_executable=python_executable,
        home=home,
        runner=runner,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )

    uninstall(home=home, runner=runner)

    assert not service_unit_path(home).is_file()


def test_install_is_idempotent_on_second_run(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project_root = tmp_path / "project"
    python_executable = project_root / ".venv" / "bin" / "python"
    runner = RecordingRunner()

    install(
        project_root=project_root,
        python_executable=python_executable,
        home=home,
        runner=runner,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    first_content = service_unit_path(home).read_text(encoding="utf-8")
    install(
        project_root=project_root,
        python_executable=python_executable,
        home=home,
        runner=runner,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    second_content = service_unit_path(home).read_text(encoding="utf-8")

    assert first_content == second_content


def test_install_after_relocation_points_at_new_project_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    old_root = tmp_path / "old"
    old_python = old_root / ".venv" / "bin" / "python"
    runner = RecordingRunner()
    install(
        project_root=old_root,
        python_executable=old_python,
        home=home,
        runner=runner,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )

    new_root = tmp_path / "new"
    new_python = new_root / ".venv" / "bin" / "python"
    install(
        project_root=new_root,
        python_executable=new_python,
        home=home,
        runner=runner,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )

    content = service_unit_path(home).read_text(encoding="utf-8")
    assert str(new_root) in content
    assert str(old_root) not in content


def test_service_unit_never_disables_process_for_controlled_provider_states(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    python_executable = project_root / ".venv" / "bin" / "python"
    content = render_service_unit(
        project_root=project_root,
        python_executable=python_executable,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    # Crash-recovery must only cover real process failures; 403/429/challenge handling
    # is application-level and must never intentionally exit the process to trigger this.
    assert "Restart=on-failure" in content
    assert "Restart=always" not in content


def test_service_name_constant_matches_unit_filename() -> None:
    assert SERVICE_NAME == "willhaben-suchagent.service"


def test_render_service_unit_uses_bundled_executable_directly_when_given(tmp_path: Path) -> None:
    project_root = tmp_path / "Programme" / "Willhaben-Suchagent"
    agent_executable = project_root / "runtime" / "willhaben-suchagent"

    content = render_service_unit(
        project_root=project_root,
        python_executable=project_root / ".venv" / "bin" / "python",
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        agent_executable=agent_executable,
    )

    assert f'ExecStart="{agent_executable}"' in content
    assert "-m agent.app.main" not in content
