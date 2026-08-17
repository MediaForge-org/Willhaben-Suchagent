from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent.app.deployment.bootstrap_core import (
    BootstrapError,
    CommandResult,
    bootstrap,
    ensure_env_file,
    ensure_venv,
    find_compatible_python,
    install_runtime_dependencies,
    venv_python,
)


class RecordingRunner:
    def __init__(self, responses: dict[str, CommandResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._responses = responses or {}
        self._default = CommandResult(0, "", "")

    def __call__(self, command: list[str]) -> CommandResult:
        self.calls.append(list(command))
        key = " ".join(command)
        for pattern, result in self._responses.items():
            if pattern in key:
                return result
        return self._default


def _touch_venv_python(project_root: Path) -> None:
    python_path = venv_python(project_root)
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("")


def test_find_compatible_python_accepts_supported_version() -> None:
    runner = RecordingRunner({"--version": CommandResult(0, "Python 3.12.4\n", "")})

    found = find_compatible_python(runner=runner)

    assert found
    assert any("--version" in " ".join(call) for call in runner.calls)


def test_find_compatible_python_rejects_too_old_version() -> None:
    runner = RecordingRunner({"--version": CommandResult(0, "Python 3.8.10\n", "")})

    with pytest.raises(BootstrapError):
        find_compatible_python(runner=runner)


def test_ensure_venv_creates_when_missing(tmp_path: Path) -> None:
    runner = RecordingRunner()

    created = ensure_venv(tmp_path, "python3", runner=runner)

    assert created is True
    assert any("-m" in call and "venv" in call for call in runner.calls)


def test_ensure_venv_is_idempotent_when_already_present(tmp_path: Path) -> None:
    _touch_venv_python(tmp_path)
    runner = RecordingRunner()

    created = ensure_venv(tmp_path, "python3", runner=runner)

    assert created is False
    assert runner.calls == []


def test_ensure_venv_raises_friendly_error_on_failure(tmp_path: Path) -> None:
    runner = RecordingRunner({"venv": CommandResult(1, "", "boom")})

    with pytest.raises(BootstrapError):
        ensure_venv(tmp_path, "python3", runner=runner)


def test_install_runtime_dependencies_never_requests_dev_extra(tmp_path: Path) -> None:
    runner = RecordingRunner()

    install_runtime_dependencies(tmp_path, runner=runner)

    assert len(runner.calls) == 1
    command_text = " ".join(runner.calls[0])
    assert "[dev]" not in command_text
    assert "-e" in runner.calls[0]


def test_install_runtime_dependencies_reports_friendly_network_error(tmp_path: Path) -> None:
    runner = RecordingRunner({"pip": CommandResult(1, "", "Temporary failure in name resolution")})

    with pytest.raises(BootstrapError) as excinfo:
        install_runtime_dependencies(tmp_path, runner=runner)

    assert "Internetverbindung" in str(excinfo.value)
    assert "Traceback" not in str(excinfo.value)


def test_install_runtime_dependencies_generic_failure_has_no_traceback(tmp_path: Path) -> None:
    runner = RecordingRunner({"pip": CommandResult(1, "", "some obscure pip internal error")})

    with pytest.raises(BootstrapError) as excinfo:
        install_runtime_dependencies(tmp_path, runner=runner)

    assert "Traceback" not in str(excinfo.value)


def test_bootstrap_is_idempotent_on_second_run(tmp_path: Path) -> None:
    runner = RecordingRunner({"--version": CommandResult(0, "Python 3.12.4\n", "")})

    first = bootstrap(tmp_path, runner=runner)
    _touch_venv_python(tmp_path)
    second = bootstrap(tmp_path, runner=runner)

    assert first.venv_created is True
    assert second.venv_created is False


def test_venv_python_path_is_platform_appropriate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    windows_path = venv_python(tmp_path)
    assert windows_path.name == "python.exe"
    assert "Scripts" in windows_path.parts

    monkeypatch.setattr(sys, "platform", "linux")
    linux_path = venv_python(tmp_path)
    assert linux_path.name == "python"
    assert "bin" in linux_path.parts


def test_ensure_env_file_creates_pointer_to_platform_data_dir(tmp_path: Path) -> None:
    env_path = ensure_env_file(tmp_path)

    content = env_path.read_text(encoding="utf-8")
    assert "WILLHABEN_DATABASE_PATH=" in content
    assert "WILLHABEN_SECRET_STORE_PATH=" in content


def test_ensure_env_file_never_overwrites_existing_dev_env(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("NTFY_ENABLED=true\n", encoding="utf-8")

    result = ensure_env_file(tmp_path)

    assert result.read_text(encoding="utf-8") == "NTFY_ENABLED=true\n"


def test_bootstrap_works_with_program_folder_containing_spaces(tmp_path: Path) -> None:
    project_root = tmp_path / "Willhaben Suchagent"
    project_root.mkdir()
    runner = RecordingRunner({"--version": CommandResult(0, "Python 3.12.4\n", "")})

    result = bootstrap(project_root, runner=runner)

    assert str(project_root) in str(result.venv_python_path)
