"""Unit tests for the ProjectListViewModel (Qt-backed)."""

from pathlib import Path

from src.application.services.installation_service import InstallationService
from src.domain.identity.value_objects import Role
from src.interfaces.qt.viewmodels.project_list_viewmodel import ProjectListViewModel


class FakeProductionService:
    def list_open_projects(self):
        return []

    def download_project_thumbnail(self, *args):
        return None


class FakeAuthService:
    def current_role(self):
        return Role.ARTIST

    def access_token(self):
        return ""

    @property
    def host(self):
        return ""


class FakeConfigFactory:
    def __init__(self, nas_dir):
        self._nas_dir = nas_dir

    def get_vfs_local_name(self):
        return "local"

    def get_vfs_svn_name(self):
        return "svn"

    def get_workspace_root(self):
        return self._nas_dir

    def get_raw_config(self):
        return {}


class DummyHealth:
    def __init__(self, is_nas=False, has_kitsu=True, has_bp=False, is_local=False) -> None:
        self.is_accessible_on_nas = is_nas
        self.has_kitsu_project = has_kitsu
        self.has_blueprint = has_bp
        self.is_installed_locally = is_local

class DummyBlueprint:
    def __init__(self, version="Blender"):
        self.blender_version = version

class DummyHubProject:
    def __init__(self, health, blueprint=None):
        self.health = health
        self.blueprint = blueprint

class FakeAuditService:
    def audit_project(self, project_name: str, kitsu_id: str = ""):
        if project_name == "Neon":
            health = DummyHealth(is_nas=True, has_kitsu=True, has_bp=True, is_local=True)
            return DummyHubProject(health, DummyBlueprint("5.1.2"))

        return DummyHubProject(DummyHealth(is_nas=False, has_kitsu=True, has_bp=False, is_local=False))

def _make_vm(tmp_path):
    nas_dir = tmp_path / "workspace"
    nas_dir.mkdir(exist_ok=True)
    installation_service = InstallationService(FakeConfigFactory(nas_dir), nas_dir / "vault")
    return ProjectListViewModel(
        production_service=FakeProductionService(),
        auth_service=FakeAuthService(),
        config_factory=FakeConfigFactory(nas_dir),
        installation_service=installation_service,
        audit_service=FakeAuditService(),
        read_vcs_credentials=True,
        nas_dir=nas_dir,
        open_kitsu_callback=lambda url: None,
        open_watchtower_callback=lambda project_dir: None,
        instance_lock_callback=lambda active: None,
    )


def test_compute_status_not_mounted(tmp_path, qapp):
    vm = _make_vm(tmp_path)
    status = vm.compute_status({"name": "Ghost Project"})

    assert status["project_dir"] is None
    assert status["is_installed"] is False
    assert status["is_corrupted"] is True
    assert status["badge_text"] == "Not Mounted"


def test_compute_status_installed(tmp_path, qapp):
    nas_dir = tmp_path / "workspace"
    project = nas_dir / "Neon"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text("{}")
    (project / "svn").mkdir()
    (project / "pipeline").mkdir()
    (project / "pipeline" / "project_init.json").write_text('{"blender_version": "5.1.2"}')

    vm = _make_vm(tmp_path)
    status = vm.compute_status({"name": "Neon"})

    assert status["is_installed"] is True
    assert status["is_corrupted"] is False
    assert status["badge_text"] == "5.1.2"
    assert status["project_dir"] == project
