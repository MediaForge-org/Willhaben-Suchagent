"""Regression tests for the release setup executable's path resolution.

Root cause of the relocation bug this guards against: the frozen release
setup entry point (deployment/pyinstaller/run_setup.py) used to build the
native-messaging manifest/launcher location from a `--project-root` CLI
argument. That argument has to survive a shell/batch-file invocation chain
(Einrichtung.bat -> setup.exe, or a test harness invoking it directly) which
can mangle a path containing spaces; and even when it doesn't, nothing
guaranteed the passed value actually matched wherever the running executable
itself lived on disk. The fix: derive the release root deterministically
from the executable's own on-disk location (parent of the runtime/ folder
containing it) via `_release_root()`, never from an argument, and never from
the process's current working directory.

`run_setup.py` is a standalone script (not part of the installable `agent`
package, since it becomes a separate PyInstaller entry point), so it is
loaded here via importlib rather than a normal import.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SETUP_PATH = REPO_ROOT / "deployment" / "pyinstaller" / "run_setup.py"


@pytest.fixture
def run_setup(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("run_setup_under_test", RUN_SETUP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pretend_frozen_at(monkeypatch: pytest.MonkeyPatch, exe_path: Path) -> None:
    """Simulate sys.executable as PyInstaller sets it: the path of the
    running frozen executable itself (here: the setup exe)."""
    monkeypatch.setattr(sys, "executable", str(exe_path))


def test_release_root_resolves_from_original_release_path(run_setup, monkeypatch, tmp_path) -> None:
    original_root = tmp_path / "Willhaben-Suchagent-1.0.0"
    setup_exe = original_root / "runtime" / "willhaben-suchagent-setup.exe"
    _pretend_frozen_at(monkeypatch, setup_exe)

    assert run_setup._release_root() == original_root.resolve()


def test_release_root_resolves_from_relocated_path(run_setup, monkeypatch, tmp_path) -> None:
    relocated_root = tmp_path / "moved" / "elsewhere" / "Willhaben-Suchagent-1.0.0"
    setup_exe = relocated_root / "runtime" / "willhaben-suchagent-setup.exe"
    _pretend_frozen_at(monkeypatch, setup_exe)

    assert run_setup._release_root() == relocated_root.resolve()


def test_release_root_resolves_correctly_with_a_space_in_the_path(
    run_setup, monkeypatch, tmp_path
) -> None:
    spaced_root = tmp_path / "Willhaben Test" / "Willhaben-Suchagent-1.0.0"
    setup_exe = spaced_root / "runtime" / "willhaben-suchagent-setup.exe"
    _pretend_frozen_at(monkeypatch, setup_exe)

    assert run_setup._release_root() == spaced_root.resolve()
    assert " " in str(run_setup._release_root())


def test_release_root_is_independent_of_current_working_directory(
    run_setup, monkeypatch, tmp_path
) -> None:
    release_root = tmp_path / "Willhaben-Suchagent-1.0.0"
    setup_exe = release_root / "runtime" / "willhaben-suchagent-setup.exe"
    _pretend_frozen_at(monkeypatch, setup_exe)

    unrelated_cwd = tmp_path / "some" / "unrelated" / "directory"
    unrelated_cwd.mkdir(parents=True)
    monkeypatch.chdir(unrelated_cwd)

    assert run_setup._release_root() == release_root.resolve()


def test_release_root_ignores_a_wrong_or_stale_project_root_argument(
    run_setup, monkeypatch, tmp_path
) -> None:
    """A --project-root value that doesn't match where the executable itself
    lives must never win - the executable's own location is authoritative."""
    real_root = tmp_path / "Willhaben-Suchagent-1.0.0"
    setup_exe = real_root / "runtime" / "willhaben-suchagent-setup.exe"
    _pretend_frozen_at(monkeypatch, setup_exe)

    wrong_project_root = tmp_path / "some" / "completely" / "different" / "path"
    monkeypatch.setattr(
        sys, "argv", ["run_setup", "install-windows", "--project-root", str(wrong_project_root)]
    )
    # _release_root() must not consult argv/args at all.
    assert run_setup._release_root() == real_root.resolve()
    assert run_setup._release_root() != wrong_project_root.resolve()


@pytest.mark.skipif(
    sys.platform != "win32", reason="drive letters are only meaningful under WindowsPath"
)
def test_release_root_correctly_reflects_a_different_windows_drive_letter(
    run_setup, monkeypatch
) -> None:
    for drive in ("C:", "D:", "E:"):
        setup_exe = Path(
            f"{drive}\\Programme\\Willhaben-Suchagent\\runtime\\willhaben-suchagent-setup.exe"
        )
        monkeypatch.setattr(sys, "executable", str(setup_exe))
        assert str(run_setup._release_root()).startswith(drive)


def test_release_root_uses_only_relative_parent_navigation_no_platform_specific_literal() -> None:
    """Cross-platform structural stand-in for the drive-letter test above
    (which can only run for real on Windows): the resolution logic must be
    built purely from `.parent`/`sys.executable`, never a literal drive
    letter or OS-specific path fragment baked into the source."""
    content = RUN_SETUP_PATH.read_text(encoding="utf-8")
    assert "sys.executable" in content
    assert ".parent" in content
    for forbidden in ("C:\\", "D:\\", "/mnt/", "/home/"):
        assert forbidden not in content


def test_release_root_contains_no_hardcoded_development_or_ci_path() -> None:
    content = RUN_SETUP_PATH.read_text(encoding="utf-8")
    for forbidden in ("D:\\a\\", "/home/runner", "github", "site-packages", "\\Users\\"):
        assert forbidden.lower() not in content.lower()


def test_release_root_two_different_locations_never_leak_into_each_other(
    run_setup, monkeypatch, tmp_path
) -> None:
    root_a = tmp_path / "build-a"
    root_b = tmp_path / "relocated-b with space"
    _pretend_frozen_at(monkeypatch, root_a / "runtime" / "willhaben-suchagent-setup.exe")
    resolved_a = run_setup._release_root()
    _pretend_frozen_at(monkeypatch, root_b / "runtime" / "willhaben-suchagent-setup.exe")
    resolved_b = run_setup._release_root()

    assert resolved_a == root_a.resolve()
    assert resolved_b == root_b.resolve()
    assert str(root_a) not in str(resolved_b)
    assert str(root_b) not in str(resolved_a)


def test_install_functions_take_no_project_root_parameter(run_setup) -> None:
    """Structural guard: _install_linux/_install_windows must derive the root
    themselves (via _release_root()) rather than accept it as an argument -
    that is exactly what made a mismatched/mangled argument possible before."""
    import inspect

    assert list(inspect.signature(run_setup._install_linux).parameters) == []
    assert list(inspect.signature(run_setup._install_windows).parameters) == []


def test_project_root_cli_argument_is_optional() -> None:
    """Kept for backwards compatibility with existing launcher scripts, but
    must never be required - a release setup that only works when a fragile
    argument survives shell-quoting is exactly the bug being fixed here."""
    source = RUN_SETUP_PATH.read_text(encoding="utf-8")
    assert 'parser.add_argument("--project-root", type=Path, required=False)' in source


def test_einrichtung_bat_and_start_bat_use_their_own_location() -> None:
    einrichtung = (
        REPO_ROOT / "deployment" / "release-templates" / "windows" / "Einrichtung.bat"
    ).read_text(encoding="utf-8")
    starten = (
        REPO_ROOT
        / "deployment"
        / "release-templates"
        / "windows"
        / "Willhaben-Suchagent starten.bat"
    ).read_text(encoding="utf-8")
    for content, name in (
        (einrichtung, "Einrichtung.bat"),
        (starten, "Willhaben-Suchagent starten.bat"),
    ):
        assert "%~dp0" in content, f"{name} must derive its location from %~dp0"
        # Every expansion of the derived SCRIPT_DIR must be quoted so a path
        # containing spaces stays a single argument.
        assert '"%SCRIPT_DIR%' in content
