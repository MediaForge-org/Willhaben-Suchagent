"""Fast, no-PyInstaller checks for the release packaging pieces.

A real PyInstaller build (validated manually before release, see
deployment/build-release-linux.sh) takes too long to run on every test
invocation. These tests instead check the things that can regress silently
and cheaply: syntax of the build scripts/spec, and that the release-flavored
launcher templates never leak a dev-only (venv/pip) path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pyinstaller_spec_is_valid_python_syntax() -> None:
    spec = REPO_ROOT / "deployment" / "pyinstaller" / "willhaben-suchagent.spec"
    compile(spec.read_text(encoding="utf-8"), str(spec), "exec")


def test_pyinstaller_entrypoints_are_valid_python_syntax() -> None:
    for name in ("run_agent.py", "run_native_host.py", "run_setup.py"):
        path = REPO_ROOT / "deployment" / "pyinstaller" / name
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_linux_build_script_has_valid_shell_syntax() -> None:
    script = REPO_ROOT / "deployment" / "build-release-linux.sh"
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", "-n", str(script)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_release_templates_have_valid_shell_syntax() -> None:
    for script in (
        REPO_ROOT / "deployment" / "release-templates" / "linux" / "Einrichtung.sh",
        REPO_ROOT / "deployment" / "release-templates" / "linux" / "Willhaben-Suchagent starten.sh",
    ):
        result = subprocess.run(  # noqa: S603
            ["/bin/bash", "-n", str(script)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr


def test_release_templates_never_reference_dev_venv_or_pip() -> None:
    forbidden = ("pip install", ".venv", "pip3", "npm install", "npm run")
    for script in (
        REPO_ROOT / "deployment" / "release-templates" / "linux" / "Einrichtung.sh",
        REPO_ROOT / "deployment" / "release-templates" / "linux" / "Willhaben-Suchagent starten.sh",
        REPO_ROOT / "deployment" / "release-templates" / "windows" / "Einrichtung.bat",
        REPO_ROOT
        / "deployment"
        / "release-templates"
        / "windows"
        / "Willhaben-Suchagent starten.bat",
    ):
        content = script.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in content, f"{script.name} unexpectedly references '{marker}'"


def test_release_templates_reference_bundled_runtime_only() -> None:
    linux_setup = (
        REPO_ROOT / "deployment" / "release-templates" / "linux" / "Einrichtung.sh"
    ).read_text(encoding="utf-8")
    assert "runtime/willhaben-suchagent-setup" in linux_setup

    windows_setup = (
        REPO_ROOT / "deployment" / "release-templates" / "windows" / "Einrichtung.bat"
    ).read_text(encoding="utf-8")
    assert "runtime\\willhaben-suchagent-setup.exe" in windows_setup


def test_run_agent_entrypoint_defaults_data_paths_outside_release_folder() -> None:
    content = (REPO_ROOT / "deployment" / "pyinstaller" / "run_agent.py").read_text(
        encoding="utf-8"
    )
    assert "default_database_path" in content
    assert "default_secret_store_path" in content
    assert "setdefault" in content


def test_gitignore_excludes_release_build_artifacts() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("build/", "dist/", "dist-release/"):
        assert pattern in gitignore


def test_pyproject_declares_pyinstaller_as_build_only_optional_dependency() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.optional-dependencies]" in pyproject
    build_section = pyproject.split("build = [")[1].split("]")[0]
    assert "pyinstaller" in build_section
    # Must not be a runtime dependency of the normal package install.
    core_dependencies = pyproject.split("dependencies = [")[1].split("]")[0]
    assert "pyinstaller" not in core_dependencies


def test_agent_and_native_host_entrypoints_are_importable_as_modules() -> None:
    # A cheap smoke check that the modules PyInstaller freezes actually import
    # cleanly under the current interpreter (catches obvious breakage early,
    # without running PyInstaller itself).
    for module in ("agent.app.main", "agent.app.native_messaging.host"):
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr
