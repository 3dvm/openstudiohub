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
        self.created_with_topology = []
        self.destroyed = []
        self.transferred = False
        self._url = working_copy_url
        self._urls = None  # optional FIFO of working-copy URLs
        self._wc_reads = 0
        self._source_id = getattr(config, "_project_server", "")
        self._source_youngest = 3
        self._target_youngest = None  # absent until the transfer "loads" it
        self._target_youngest_after = None  # force a mismatch when set
        self._uuids_match = True

    def _working_copy_url(self, workspace):  # noqa: D102
        if self._urls is not None:
            return self._urls.pop(0) if self._urls else self._url
        self._wc_reads += 1
        if self._wc_reads > 1 and FakeSvnAdapter.relocated:
            return FakeSvnAdapter.relocated[-1]
        return self._url

    def _youngest(self, server, path):  # noqa: D102
        if server.id == self._source_id:
            return self._source_youngest
        return self._target_youngest

    def _admin(self, server):  # noqa: D102
        svc = self

        class _Admin:
            def create(self, repo_name, vfs_svn, initialize_topology=True):
                svc.created.append(server.id)
                svc.created_with_topology.append(initialize_topology)
                return True

            def destroy(self, repo_name, vfs_svn):
                svc.destroyed.append(server.id)
                return True, "removed"

        return _Admin()

    def _repo_size_bytes(self, server, path):  # noqa: D102
        return None

    def _uuid(self, server, path):  # noqa: D102
        uuid = "same-uuid" if self._uuids_match else f"uuid-{server.id}"
        return uuid

    def _transfer(self, source, target, repo_name, total_revisions=None, total_bytes=None):  # noqa: D102
        self.transferred = True
        if self._target_youngest_after is not None:
            self._target_youngest = self._target_youngest_after
        else:
            self._target_youngest = self._source_youngest
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
    # The target must be created empty so the dump can restore revision 1.
    assert service.created_with_topology == [False]
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
    assert "current vcs server" in message.lower()


def test_migrate_project_rejects_unknown_target(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    project_root = _make_project(tmp_path)
    service = StubService(FakeConfig([_local_server(), _remote_server()], "vps", "local"))

    ok, message = service.migrate_project(project_root, target_server_id="ghost")

    assert ok is False
    assert "not found" in message.lower()


def test_migrate_project_rejects_non_svn_target(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    git_server = VCSServer(id="git", name="Git", adapter="git-lfs", repository_url="git@host/repo")
    project_root = _make_project(tmp_path)
    service = StubService(FakeConfig([_local_server(), _remote_server(), git_server], "vps", "local"))

    ok, message = service.migrate_project(project_root, target_server_id="git")

    assert ok is False
    assert "only svn" in message.lower()


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


def test_migrate_project_resumes_when_target_already_matches(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    FakeSvnAdapter.relocated = []
    project_root = _make_project(tmp_path)
    service = StubService(FakeConfig([_local_server(), _remote_server()], "vps", "local"))
    service._target_youngest = service._source_youngest  # a previous attempt already loaded it

    ok, message = service.migrate_project(project_root, target_server_id="vps")

    assert ok is True
    assert service.transferred is False
    assert service.created == []
    assert FakeSvnAdapter.relocated == ["svn://svn-vps/neon/svn"]


def test_migrate_project_rejects_preexisting_mismatched_target(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    project_root = _make_project(tmp_path)
    service = StubService(FakeConfig([_local_server(), _remote_server()], "vps", "local"))
    service._target_youngest = service._source_youngest
    service._uuids_match = False

    ok, message = service.migrate_project(project_root, target_server_id="vps")

    assert ok is False
    assert "does not match" in message.lower()
    assert service.transferred is False


def test_migrate_project_fails_when_revision_verification_mismatches(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    project_root = _make_project(tmp_path)
    service = StubService(FakeConfig([_local_server(), _remote_server()], "vps", "local"))
    service._target_youngest_after = 99  # simulate a bad load

    ok, message = service.migrate_project(project_root, target_server_id="vps")

    assert ok is False
    assert "verification failed" in message.lower()
    assert service.transferred is True


def test_migrate_project_fails_when_working_copy_not_repointed(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    project_root = _make_project(tmp_path)
    service = StubService(FakeConfig([_local_server(), _remote_server()], "vps", "local"))
    # First read (pre-check) is the old URL; second read (post-relocate) is wrong.
    service._urls = ["svn://localhost/neon/svn", "svn://stale/neon/svn"]

    ok, message = service.migrate_project(project_root, target_server_id="vps")

    assert ok is False
    assert "verification failed" in message.lower()


class ProbeService(VCSMigrationService):
    """Probe service with server I/O replaced by deterministic stubs."""

    def __init__(self, config, online=True, youngest=3, dirs=("svn",)) -> None:
        super().__init__(config)
        self._online = online
        self._probe_youngest = youngest
        self._dirs = list(dirs)

    def test_remote_svn(self, server=None):  # noqa: D102
        return (True, "reachable") if self._online else (False, "unreachable")

    def _youngest(self, server, path):  # noqa: D102
        return self._probe_youngest

    def _repo_top_level_dirs(self, server, repo_path):  # noqa: D102
        return list(self._dirs)


def test_probe_repository_topography_healthy():
    service = ProbeService(FakeConfig([_local_server()], "local", "local"))
    ok, message = service.probe_repository_topography(_local_server(), "Neon")
    assert ok is True
    assert "healthy" in message.lower()


def test_probe_repository_topography_unreachable():
    service = ProbeService(FakeConfig([_local_server()], "local", "local"), online=False)
    ok, message = service.probe_repository_topography(_local_server(), "Neon")
    assert ok is False
    assert "unreachable" in message.lower()


def test_probe_repository_topography_missing_repo():
    service = ProbeService(FakeConfig([_local_server()], "local", "local"), youngest=None)
    ok, message = service.probe_repository_topography(_local_server(), "Neon")
    assert ok is False
    assert "not found" in message.lower()


def test_probe_repository_topography_missing_vfs_folder():
    service = ProbeService(FakeConfig([_local_server()], "local", "local"), dirs=("shared",))
    ok, message = service.probe_repository_topography(_local_server(), "Neon")
    assert ok is False
    assert "no 'svn' folder" in message.lower()


def test_probe_repository_topography_disabled_server():
    disabled = VCSServer(id="off", name="Off", adapter="none")
    service = ProbeService(FakeConfig([disabled], "off", "off"))
    ok, message = service.probe_repository_topography(disabled, "Neon")
    assert ok is True
    assert "disabled" in message.lower()
