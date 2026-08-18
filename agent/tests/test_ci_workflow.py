"""Static checks for the Windows release GitHub Actions workflow.

Does not run the workflow (that requires GitHub Actions itself) — verifies
the YAML is well-formed and shaped as expected, and that the PowerShell
scripts it invokes are at least syntactically valid, so a typo doesn't have
to be discovered by burning a Windows-runner minute.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "windows-release.yml"


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_workflow_file_exists_and_is_valid_yaml() -> None:
    assert WORKFLOW_PATH.is_file()
    workflow = _load_workflow()
    assert "jobs" in workflow


def test_workflow_is_manually_triggerable() -> None:
    workflow = _load_workflow()
    assert "workflow_dispatch" in workflow["on"]


def test_workflow_runs_on_a_real_windows_runner() -> None:
    workflow = _load_workflow()
    job = workflow["jobs"]["windows-release"]
    assert job["runs-on"] in ("windows-2025", "windows-latest")


def test_workflow_never_publishes_a_release_or_tag() -> None:
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    for forbidden in ("gh release create", "softprops/action-gh-release", "git tag", "git push"):
        assert forbidden not in content


def test_workflow_scope_excludes_unrelated_stacks() -> None:
    content = WORKFLOW_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("cargo", "rustc", "pnpm", "composer", "pest"):
        assert forbidden not in content


def test_workflow_builds_extension_before_packaging() -> None:
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "npm ci" in content
    assert "npm run typecheck" in content
    assert "npm test" in content
    assert "npm run build" in content
    assert "build-release-windows.ps1" in content


def test_workflow_runs_the_smoke_test_script() -> None:
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "deployment/ci/windows-smoke-test.ps1" in content


def test_workflow_uploads_release_and_log_artifacts() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["windows-release"]["steps"]
    upload_steps = [
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact")
    ]
    assert len(upload_steps) >= 2
    uploaded_paths = " ".join(step["with"]["path"] for step in upload_steps)
    assert "*.zip" in uploaded_paths
    assert "SHA256SUMS.windows" in uploaded_paths
    assert "*.xpi" in uploaded_paths


def test_windows_smoke_test_script_exists() -> None:
    script = REPO_ROOT / "deployment" / "ci" / "windows-smoke-test.ps1"
    assert script.is_file()


def test_windows_smoke_test_script_never_uses_real_secrets() -> None:
    content = (REPO_ROOT / "deployment" / "ci" / "windows-smoke-test.ps1").read_text(
        encoding="utf-8"
    )
    for forbidden in ("discord.com/api/webhooks/1", "ntfy.sh/real", "smtp.gmail.com"):
        assert forbidden not in content


@pytest.mark.parametrize(
    "script",
    [
        "deployment/ci/windows-smoke-test.ps1",
        "deployment/build-release-windows.ps1",
    ],
)
def test_windows_scripts_never_use_powershell5_only_byte_encoding(script: str) -> None:
    """'-Encoding Byte' (and the equivalent 'Encoding = "Byte"') only exists in
    Windows PowerShell 5.1 - PowerShell 7 (pwsh, used on windows-2025 runners)
    rejects it outright. Binary I/O must go through .NET APIs
    ([System.IO.File]::Read/WriteAllBytes, raw Stream Read/Write) instead."""
    content = (REPO_ROOT / script).read_text(encoding="utf-8")
    lowered = content.lower()
    assert "-encoding byte" not in lowered
    assert 'encoding = "byte"' not in lowered
    assert "encoding = 'byte'" not in lowered


def test_native_messaging_smoke_test_uses_binary_safe_stream_io() -> None:
    """Guards against silently regressing back to a PowerShell pipeline/text
    capture for the framed native-messaging bytes (both mangle binary data,
    independently of the '-Encoding Byte' bug this replaced)."""
    content = (REPO_ROOT / "deployment" / "ci" / "windows-smoke-test.ps1").read_text(
        encoding="utf-8"
    )
    assert "RedirectStandardInput" in content
    assert "RedirectStandardOutput" in content
    assert ".BaseStream" in content
    # Must not pipe request bytes into the host executable through the
    # PowerShell object pipeline, and must not capture its stdout via
    # "$var = & exe" text capture - both corrupt raw bytes.
    assert "| & $hostExe" not in content
    assert "$hostExe |" not in content


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
@pytest.mark.parametrize(
    "script",
    [
        "deployment/build-release-windows.ps1",
        "deployment/ci/windows-smoke-test.ps1",
    ],
)
def test_powershell_scripts_have_valid_syntax(script: str) -> None:
    path = REPO_ROOT / script
    command = (
        "$errors = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{path}', [ref]$null, [ref]$errors"
        ") | Out-Null; "
        "if ($errors.Count -gt 0) { "
        "$errors | ForEach-Object { Write-Host $_ }; exit 1 "
        "} else { exit 0 }"
    )
    result = subprocess.run(  # noqa: S603
        ["pwsh", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
