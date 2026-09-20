"""Unit tests for the InstallationService verification helper."""

from src.application.services.installation_service import InstallationService
from src.infrastructure.sandbox.blender_locator import BlenderLocator


class FakeConfigFactory:
    def get_vfs_local_name(self):
        return "local"

    def get_vfs_svn_name(self):
        return "svn"


def _make_service(tmp_path):
    return InstallationService(FakeConfigFactory(), tmp_path / "vault")


def _materialize_blender(project):
    folder = project / "local" / "blender-build" / BlenderLocator.archive_folder_name("5.2.0")
    exe = folder / BlenderLocator.relative_executable()
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    return exe


def test_verify_installation_true(tmp_path):
    project = tmp_path / "project"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text("{}")
    (project / "svn").mkdir()
    _materialize_blender(project)

    service = _make_service(tmp_path)
    assert service.verify_installation(project) is True


def test_verify_installation_false_when_config_missing(tmp_path):
    project = tmp_path / "project"
    (project / "svn").mkdir(parents=True)

    service = _make_service(tmp_path)
    assert service.verify_installation(project) is False


def test_verify_installation_false_when_vcs_missing(tmp_path):
    project = tmp_path / "project"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text("{}")

    service = _make_service(tmp_path)
    assert service.verify_installation(project) is False


def test_verify_installation_false_when_blender_missing(tmp_path):
    project = tmp_path / "project"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text("{}")
    (project / "svn").mkdir()

    service = _make_service(tmp_path)
    assert service.verify_installation(project) is False


def test_get_os_info_shape():
    os_name, ext = InstallationService._get_os_info()
    assert os_name in {"linux", "windows", "macos"}
    assert ext in {"tar.xz", "zip", "dmg"}
