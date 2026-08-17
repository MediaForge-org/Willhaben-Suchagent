from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_DEV_PATH = "/mnt/Festplatte/Schreibtisch/Projekte/Willhaben-Suchagent"


def _read(name: str) -> str:
    return (PROJECT_ROOT / name).read_text(encoding="utf-8")


def test_windows_setup_script_is_relocatable_and_has_no_hardcoded_dev_path() -> None:
    content = _read("Einrichtung.bat")
    assert "%~dp0" in content
    assert FORBIDDEN_DEV_PATH not in content
    assert "C:\\Program Files" not in content
    assert "npm" not in content.lower()
    assert "pytest" not in content.lower()


def test_windows_start_script_is_relocatable_and_has_no_hardcoded_dev_path() -> None:
    content = _read("Willhaben-Suchagent starten.bat")
    assert "%~dp0" in content
    assert FORBIDDEN_DEV_PATH not in content
    assert ".venv\\Scripts\\willhaben-suchagent.exe" in content


def test_linux_setup_script_is_relocatable_and_has_no_hardcoded_dev_path() -> None:
    content = _read("Einrichtung.sh")
    assert "BASH_SOURCE[0]" in content
    assert FORBIDDEN_DEV_PATH not in content
    assert "npm" not in content.lower()
    assert "pytest" not in content.lower()


def test_linux_start_script_is_relocatable_and_uses_installed_entry_point() -> None:
    content = _read("Willhaben-Suchagent starten.sh")
    assert "BASH_SOURCE[0]" in content
    assert FORBIDDEN_DEV_PATH not in content
    assert ".venv/bin/willhaben-suchagent" in content


def test_all_four_launcher_entry_points_exist() -> None:
    for name in (
        "Einrichtung.sh",
        "Willhaben-Suchagent starten.sh",
        "Einrichtung.bat",
        "Willhaben-Suchagent starten.bat",
    ):
        assert (PROJECT_ROOT / name).is_file(), name
