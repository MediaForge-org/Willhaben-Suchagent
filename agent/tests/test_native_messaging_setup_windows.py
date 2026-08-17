from __future__ import annotations

import json
from pathlib import Path

from agent.app.native_messaging.setup_windows import (
    REGISTRY_KEY_PATH,
    install,
    launcher_path,
    manifest_path,
    uninstall,
)


class FakeRegistryWriter:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []

    def set_default_value(self, key_path: str, value: str) -> None:
        self.values[key_path] = value

    def delete_key(self, key_path: str) -> None:
        self.deleted.append(key_path)
        self.values.pop(key_path, None)


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "Willhaben-Suchagent"
    host_source = project_root / "agent" / "app" / "native_messaging"
    host_source.mkdir(parents=True)
    (host_source / "host.py").write_text("# host\n")
    python_executable = project_root / ".venv" / "Scripts" / "python.exe"
    python_executable.parent.mkdir(parents=True)
    python_executable.write_text("")
    return project_root, python_executable


def test_install_writes_registry_value_pointing_at_manifest(tmp_path: Path) -> None:
    project_root, python_executable = _make_project(tmp_path)
    registry = FakeRegistryWriter()

    launcher, manifest = install(project_root, python_executable, registry_writer=registry)

    assert registry.values[REGISTRY_KEY_PATH] == str(manifest)
    assert manifest.is_file()
    assert launcher.is_file()


def test_manifest_path_field_points_at_launcher_not_python_directly(tmp_path: Path) -> None:
    project_root, python_executable = _make_project(tmp_path)
    registry = FakeRegistryWriter()

    launcher, manifest = install(project_root, python_executable, registry_writer=registry)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))

    assert manifest_data["path"] == str(launcher)
    assert manifest_data["name"] == "at.willhaben_suchagent.bridge"
    assert manifest_data["allowed_extensions"] == ["willhaben-suchagent@local"]


def test_launcher_bat_references_absolute_current_python_and_host_paths(tmp_path: Path) -> None:
    project_root, python_executable = _make_project(tmp_path)
    registry = FakeRegistryWriter()

    launcher, _ = install(project_root, python_executable, registry_writer=registry)
    content = launcher.read_text(encoding="utf-8")

    assert str(python_executable) in content
    assert str(project_root / "agent" / "app" / "native_messaging" / "host.py") in content


def test_install_on_path_with_spaces_and_different_drive(tmp_path: Path) -> None:
    project_root = tmp_path / "D" / "Programme" / "Willhaben Suchagent"
    host_source_dir = project_root / "agent" / "app" / "native_messaging"
    host_source_dir.mkdir(parents=True)
    (host_source_dir / "host.py").write_text("# host\n")
    python_executable = project_root / ".venv" / "Scripts" / "python.exe"
    python_executable.parent.mkdir(parents=True)
    python_executable.write_text("")
    registry = FakeRegistryWriter()

    launcher, manifest = install(project_root, python_executable, registry_writer=registry)

    assert "Willhaben Suchagent" in str(launcher)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    assert "Willhaben Suchagent" in manifest_data["path"]


def test_reinstall_after_relocation_updates_registry_to_new_path(tmp_path: Path) -> None:
    old_root, old_python = _make_project(tmp_path / "old-location")
    registry = FakeRegistryWriter()
    install(old_root, old_python, registry_writer=registry)
    old_manifest_value = registry.values[REGISTRY_KEY_PATH]

    new_root, new_python = _make_project(tmp_path / "new-location")
    _, new_manifest = install(new_root, new_python, registry_writer=registry)

    assert registry.values[REGISTRY_KEY_PATH] == str(new_manifest)
    assert registry.values[REGISTRY_KEY_PATH] != old_manifest_value


def test_uninstall_removes_files_and_registry_key(tmp_path: Path) -> None:
    project_root, python_executable = _make_project(tmp_path)
    registry = FakeRegistryWriter()
    launcher, manifest = install(project_root, python_executable, registry_writer=registry)

    uninstall(project_root, registry_writer=registry)

    assert not launcher.exists()
    assert not manifest.exists()
    assert REGISTRY_KEY_PATH in registry.deleted


def test_uninstall_without_prior_install_does_not_raise(tmp_path: Path) -> None:
    project_root = tmp_path / "Willhaben-Suchagent"
    project_root.mkdir()
    registry = FakeRegistryWriter()

    uninstall(project_root, registry_writer=registry)

    assert REGISTRY_KEY_PATH in registry.deleted


def test_no_development_path_is_hardcoded_in_generated_files(tmp_path: Path) -> None:
    project_root, python_executable = _make_project(tmp_path)
    registry = FakeRegistryWriter()

    launcher, manifest = install(project_root, python_executable, registry_writer=registry)

    forbidden = "/mnt/Festplatte/Schreibtisch/Projekte/Willhaben-Suchagent"
    assert forbidden not in launcher.read_text(encoding="utf-8")
    assert forbidden not in manifest.read_text(encoding="utf-8")
    assert str(project_root) == str(manifest_path(project_root).parent.parent)
    assert launcher_path(project_root).parent == manifest_path(project_root).parent


def test_install_wraps_bundled_executable_directly_without_python(tmp_path: Path) -> None:
    project_root = tmp_path / "Willhaben-Suchagent"
    project_root.mkdir()
    bundled_host = project_root / "runtime" / "willhaben-suchagent-host.exe"
    bundled_host.parent.mkdir(parents=True)
    bundled_host.write_text("")
    writer = FakeRegistryWriter()

    launcher, manifest = install(
        project_root, None, registry_writer=writer, host_executable=bundled_host
    )

    launcher_content = launcher.read_text(encoding="utf-8")
    assert str(bundled_host) in launcher_content
    assert ".venv" not in launcher_content
    assert "host.py" not in launcher_content
