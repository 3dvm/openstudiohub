"""Unit tests for the per-project VCS migration orchestration."""

import json
from pathlib import Path

from src.application.services import vcs_migration_service as mod
from src.application.services.vcs_migration_service import VCSMigrationService
from src.domain.workspace.vcs_server import VCSServer, VCSServerRegistry
from src.domain.workspace.vcs_server_profile import (
    REMOTE_SSH,
    RemoteSSHConfig,
    VCSServerProfile,
)


def _local_server() -> VCSServer:
    return VCSServer(
        id="local",
        name="Local",
        adapter="svn",
        repository_url="svn://localhost",
        profile=VCSServerProfile(mode="local_docker"),
    )


def _remote_server() -> VCSServer:
    return VCSServer(
        id="vps",
        name="VPS",
        adapter="svn",
        repository_url="svn://svn-vps",
        profile=VCSServerProfile(
            mode=REMOTE_SSH,
            remote=RemoteSSHConfig(host="svn-vps", ssh_user="ops", container="estudio_svn", repo_root="/srv/svn"),
        ),
    )


class FakeConfig:
    def __init__(self, servers, default_id: str, project_server_id: str) -> None:
        self._servers = list(servers)
        self._default = default_id
        self._project_server = project_server_id

    def get_vfs_svn_name(self) -> str:
        return "svn"

    def get_vfs_pipeline_name(self) -> str:
        return "pipeline"

    def get_vcs_servers(self) -> VCSServerRegistry:
        return VCSServerRegistry(servers=tuple(self._servers), default_server_id=self._default)

    def get_server(self, server_id):
        return self.get_vcs_servers().get(server_id)

    def get_default_server(self):
        return self.get_vcs_servers().default()

    def get_server_for_project(self, project_root):
        return self.get_vcs_servers().get(self._project_server) or self.get_vcs_servers().default()


class StubService(VCSMigrationService):
    """Migration service with the heavy I/O replaced by recorders."""

    def __init__(self, config, working_copy_url="svn://localhost/neon/svn") -> None:
        super().__init__(config)
        self.created = []
        self.destroyed = []
        self.transferred = False
        self._url = working_copy_url
        self._youngest_value = None

    def _working_copy_url(self, workspace):  # noqa: D102
        return self._url

    def _youngest(self, server, path):  # noqa: D102
        return self._youngest_value

    def _admin(self, server):  # noqa: D102
        svc = self

        class _Admin:
            def create(self, repo_name, vfs_svn):
                svc.created.append(server.id)
                return True

            def destroy(self, repo_name, vfs_svn):
                svc.destroyed.append(server.id)
                return True, "removed"

        return _Admin()

    def _transfer(self, source, target, repo_name):  # noqa: D102
        self.transferred = True
        return True, "ok"


class FakeSvnAdapter:
    relocated = []

    def __init__(self, repo_url, workspace, server_profile=None, ssh_passphrase_provider=None) -> None:
        self.repo_url = repo_url
        self.workspace = workspace

    def relocate(self, new_url, username=None, password=None):
        FakeSvnAdapter.relocated.append(new_url)
        return True


def _make_project(tmp_path) -> Path:
    project_root = tmp_path / "Neon"
    (project_root / "svn" / ".svn").mkdir(parents=True)
    (project_root / "pipeline").mkdir(parents=True)
    with open(project_root / "pipeline" / "project_init.json", "w", encoding="utf-8") as handle:
        json.dump({"project_name": "Neon"}, handle)
    return project_root


def test_migrate_project_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    FakeSvnAdapter.relocated = []

    project_root = _make_project(tmp_path)
    service = StubService(FakeConfig([_local_server(), _remote_server()], "vps", "local"))

    ok, message = service.migrate_project(project_root, "artist", "secret", target_server_id="vps")

    assert ok is True
    assert "migrated" in message.lower()
    assert service.created == ["vps"]
    assert service.transferred is True
    assert FakeSvnAdapter.relocated == ["svn://svn-vps/neon/svn"]

    blueprint = json.loads((project_root / "pipeline" / "project_init.json").read_text(encoding="utf-8"))
    assert blueprint["vcs_server_id"] == "vps"
    assert blueprint["vcs_base_url"] == "svn://svn-vps"


def test_migrate_project_rejects_same_server(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    project_root = _make_project(tmp_path)
    service = StubService(FakeConfig([_local_server(), _remote_server()], "vps", "local"))

    ok, message = service.migrate_project(project_root, target_server_id="local")

    assert ok is False
    assert "already bound" in message.lower()
    assert service.created == []


def test_migrate_project_requires_a_server(tmp_path):
    service = StubService(FakeConfig([], "", ""))

    ok, message = service.migrate_project(_make_project(tmp_path))

    assert ok is False
    assert "no vcs server" in message.lower()


def test_migrate_project_skips_when_working_copy_already_on_target(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    project_root = _make_project(tmp_path)
    service = StubService(
        FakeConfig([_local_server(), _remote_server()], "vps", "local"),
        working_copy_url="svn://svn-vps/neon/svn",
    )

    ok, message = service.migrate_project(project_root, target_server_id="vps")

    assert ok is True
    assert "already" in message.lower()
    assert service.created == []
