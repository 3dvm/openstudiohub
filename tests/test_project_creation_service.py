"""Unit tests for the resumable project creation saga."""

from pathlib import Path

from src.application.services import project_creation_service as mod
from src.application.services.project_creation_service import ProjectCreationService
from src.application.services.workspace_operations import VCSProvisioner
from src.domain.workspace.topography import WorkspaceTopography


class FakeConfig:
    def __init__(self, root: Path) -> None:
        self._root = root

    def get_workspace_root(self) -> Path:
        return self._root

    def get_vcs_repository_url(self) -> str:
        return "svn://vcs.example.com/projects"

    def get_vcs_adapter_type(self) -> str:
        return "svn"

    def get_topography(self) -> WorkspaceTopography:
        return WorkspaceTopography()


class FakeKitsu:
    def __init__(self, health=(True, "Kitsu is online."), create=(True, "created", {"id": "k1"})) -> None:
        self.health = health
        self._create = create
        self.created = []
        self.deleted = []
        self.existing = None

    def check_health(self, timeout: float = 5.0):
        return self.health

    def create_project_from_template(self, project_name, template):
        self.created.append((project_name, template))
        return self._create

    def get_project_by_name(self, project_name):
        return self.existing

    def upload_project_splash(self, *args, **kwargs):
        return True

    def delete_project(self, project_id):
        self.deleted.append(project_id)
        return True, "Project destroyed."


class FakeRouter:
    health = (True, "VCS server reachable.")
    destroyed = []

    def __init__(self, vcs_type, repo_url, workspace_dir, server_profile=None, ssh_passphrase_provider=None) -> None:
        self.vcs_type = vcs_type
        self.repo_url = repo_url
        self.workspace_dir = workspace_dir
        self.server_profile = server_profile
        self.ssh_passphrase_provider = ssh_passphrase_provider

    @classmethod
    def probe_health(cls, vcs_type, repo_url, username=None, password=None, timeout=5.0, server_profile=None, ssh_passphrase_provider=None):
        return cls.health

    @classmethod
    def destroy_repository(cls, vcs_type, repo_url, project_name, vfs_svn, server_profile=None, ssh_passphrase_provider=None):
        FakeRouter.destroyed.append(project_name)
        return True, "VCS repository removed."

    def get_adapter(self):
        return object()


class FakeProvisioner:
    ok = True
    message = "VCS repository initialized."
    calls = 0
    repo_names = []

    def __init__(self, vcs_router, is_enabled=True) -> None:
        self.vcs_router = vcs_router
        self.is_enabled = is_enabled

    def initialize_and_commit(self, repository_name, vfs_svn, username, password, ignore_patterns):
        FakeProvisioner.calls += 1
        FakeProvisioner.repo_names.append(repository_name)
        return FakeProvisioner.ok, FakeProvisioner.message


def _make_service(monkeypatch, tmp_path, kitsu):
    monkeypatch.setattr(mod, "VCSRouter", FakeRouter)
    monkeypatch.setattr(mod, "VCSProvisioner", FakeProvisioner)
    FakeRouter.health = (True, "VCS server reachable.")
    FakeRouter.destroyed = []
    FakeProvisioner.ok = True
    FakeProvisioner.calls = 0
    FakeProvisioner.repo_names = []
    return ProjectCreationService(FakeConfig(tmp_path), kitsu_manager=kitsu)


def _create(service):
    return service.create_project(
        project_name="Neon",
        blender_version="4.2",
        dependencies={},
        kitsu_template="standard",
    )


def test_kitsu_preflight_failure_has_no_side_effects(monkeypatch, tmp_path):
    kitsu = FakeKitsu(health=(False, "Kitsu server unreachable."))
    service = _make_service(monkeypatch, tmp_path, kitsu)

    outcome = _create(service)

    assert outcome.success is False
    assert outcome.failed_step == "preflight_kitsu"
    assert outcome.can_retry is True
    assert outcome.can_rollback is False
    assert outcome.has_side_effects is False
    assert kitsu.created == []
    assert not (tmp_path / "neon").exists()


def test_vcs_preflight_failure_aborts_before_kitsu(monkeypatch, tmp_path):
    kitsu = FakeKitsu()
    service = _make_service(monkeypatch, tmp_path, kitsu)
    FakeRouter.health = (False, "VCS server unreachable at vcs.example.com:3690")

    outcome = _create(service)

    assert outcome.success is False
    assert outcome.failed_step == "preflight_vcs"
    assert outcome.can_retry is True
    assert kitsu.created == []
    assert not (tmp_path / "neon").exists()


def test_vcs_repository_uses_normalized_folder_name(monkeypatch, tmp_path):
    kitsu = FakeKitsu()
    service = _make_service(monkeypatch, tmp_path, kitsu)

    outcome = service.create_project(
        project_name="MIDEQ_promo",
        blender_version="4.2",
        dependencies={},
        kitsu_template="standard",
    )

    assert outcome.success is True
    # The VCS repository must match the lowercased URL segment, not the display name.
    assert FakeProvisioner.repo_names == ["mideq_promo"]
    assert kitsu.created == [("MIDEQ_promo", "standard")]


def test_vcs_step_failure_returns_recoverable_outcome(monkeypatch, tmp_path):
    kitsu = FakeKitsu()
    service = _make_service(monkeypatch, tmp_path, kitsu)
    FakeProvisioner.ok = False
    FakeProvisioner.message = "SVN Failure: Connection refused"

    outcome = _create(service)

    assert outcome.success is False
    assert outcome.failed_step == "vcs"
    assert outcome.has_side_effects is True
    assert outcome.can_retry is True
    assert outcome.can_rollback is True
    assert outcome.context is not None
    assert kitsu.created == [("Neon", "standard")]
    assert (tmp_path / "neon").exists()


def test_retry_skips_completed_steps(monkeypatch, tmp_path):
    kitsu = FakeKitsu()
    service = _make_service(monkeypatch, tmp_path, kitsu)
    FakeProvisioner.ok = False
    FakeProvisioner.message = "SVN Failure: Connection refused"

    first = _create(service)
    assert first.success is False

    FakeProvisioner.ok = True
    second = service.retry(first.context)

    assert second.success is True
    assert len(kitsu.created) == 1  # Kitsu was not recreated
    assert FakeProvisioner.calls == 2  # VCS was retried


def test_rollback_deletes_all_created_data(monkeypatch, tmp_path):
    kitsu = FakeKitsu()
    service = _make_service(monkeypatch, tmp_path, kitsu)
    FakeProvisioner.ok = False

    outcome = _create(service)
    assert (tmp_path / "neon").exists()

    ok, report = service.rollback(outcome.context)

    assert ok is True
    assert kitsu.deleted == ["k1"]
    assert not (tmp_path / "neon").exists()
    assert FakeRouter.destroyed == ["neon"]
    assert report


def test_validation_failure_is_not_retryable(monkeypatch, tmp_path):
    kitsu = FakeKitsu()
    service = _make_service(monkeypatch, tmp_path, kitsu)

    outcome = service.create_project("", "4.2", {})

    assert outcome.success is False
    assert outcome.can_retry is False
    assert outcome.can_rollback is False


class _Adapter:
    def __init__(self, create_ok: bool) -> None:
        self.create_ok = create_ok

    def create_server_repository(self, project_name, vfs_svn):
        return self.create_ok

    def full_pull(self, username=None, password=None):
        return True

    def setup_ignore(self, patterns):
        return True

    def add_all(self, path="."):
        return True

    def commit(self, message, paths=None, username=None, password=None):
        return True


class _Router:
    def __init__(self, adapter) -> None:
        self._adapter = adapter

    def get_adapter(self):
        return self._adapter


def test_vcs_provisioner_surfaces_repository_creation_failure():
    provisioner = VCSProvisioner(_Router(_Adapter(create_ok=False)), is_enabled=True)

    ok, message = provisioner.initialize_and_commit("Neon", "svn", "", "", [])

    assert ok is False
    assert "repository" in message.lower()


def test_vcs_provisioner_success():
    provisioner = VCSProvisioner(_Router(_Adapter(create_ok=True)), is_enabled=True)

    ok, message = provisioner.initialize_and_commit("Neon", "svn", "", "", [])

    assert ok is True
    assert message
