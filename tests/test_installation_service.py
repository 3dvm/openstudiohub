"""Unit tests for the InstallationService verification helper."""

import json

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


def _write_blueprint(project, version="5.2.0"):
    pipeline = project / "pipeline"
    pipeline.mkdir(parents=True, exist_ok=True)
    (pipeline / "project_init.json").write_text(
        json.dumps({"blender_version": version}), encoding="utf-8"
    )


def test_verify_installation_rejects_a_different_blender_version(tmp_path):
    project = tmp_path / "project"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text(
        json.dumps({"blender_version": "5.3.0"}), encoding="utf-8"
    )
    (project / "svn").mkdir()
    _write_blueprint(project, "5.3.0")
    _materialize_blender(project)

    service = _make_service(tmp_path)
    assert service.verify_installation(project) is False


def test_verify_installation_rejects_stale_project_config(tmp_path):
    project = tmp_path / "project"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text(
        json.dumps({"blender_version": "5.2.0"}), encoding="utf-8"
    )
    (project / "svn").mkdir()
    _write_blueprint(project, "5.3.0")
    _materialize_blender(project)

    service = _make_service(tmp_path)
    assert service.workspace_needs_update(project) is True
    assert service.verify_installation(project) is False


def test_verify_installation_rejects_workspace_update_flag(tmp_path):
    project = tmp_path / "project"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text(
        json.dumps({"blender_version": "5.2.0", "workspace_update_required": True}),
        encoding="utf-8",
    )
    (project / "svn").mkdir()
    _materialize_blender(project)

    service = _make_service(tmp_path)
    assert service.verify_installation(project) is False


def test_verify_installation_accepts_matching_versions(tmp_path):
    project = tmp_path / "project"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text(
        json.dumps({"blender_version": "5.2.0"}), encoding="utf-8"
    )
    (project / "svn").mkdir()
    _write_blueprint(project, "5.2.0")
    _materialize_blender(project)

    service = _make_service(tmp_path)
    assert service.verify_installation(project) is True
