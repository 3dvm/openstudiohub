"""Unit tests for the local -> remote VCS migration orchestration."""

import io
import json
from pathlib import Path
from types import SimpleNamespace

from src.application.services import vcs_migration_service as mod
from src.application.services.vcs_migration_service import VCSMigrationService
from src.domain.workspace.vcs_server_profile import (
    REMOTE_SSH,
    RemoteSSHConfig,
    VCSServerProfile,
)


def _profile() -> VCSServerProfile:
    return VCSServerProfile(
        mode=REMOTE_SSH,
        remote=RemoteSSHConfig(
            host="svn-vps",
            ssh_user="ops",
            container="estudio_svn",
            repo_root="/srv/svn",
        ),
    )


class FakeConfig:
    def __init__(self, profile: VCSServerProfile) -> None:
        self._profile = profile

    def get_vfs_svn_name(self) -> str:
        return "svn"

    def get_vfs_pipeline_name(self) -> str:
        return "pipeline"

    def get_vcs_server_profile(self) -> VCSServerProfile:
        return self._profile

    def get_vcs_adapter_type(self) -> str:
        return "svn"

    def get_vcs_repository_url(self) -> str:
        return "svn://svn-vps"


class FakeRunner:
    instances = []

    def __init__(self, remote, passphrase_provider=None) -> None:
        self.remote = remote
        self.commands = []
        FakeRunner.instances.append(self)

    def run(self, cmd, check=True, input_data=None):
        self.commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout=b"0", stderr=b"")

    def run_stream(self, cmd, stdin):
        self.commands.append(cmd)
        return b""


class FakeSvnAdapter:
    relocated = []

    def __init__(self, repo_url, workspace, server_profile=None, ssh_passphrase_provider=None) -> None:
        self.repo_url = repo_url
        self.workspace = workspace

    def relocate(self, new_url, username=None, password=None):
        FakeSvnAdapter.relocated.append(new_url)
        return True


class FakePopen:
    created = []

    def __init__(self, *args, **kwargs) -> None:
        self.stdout = io.BytesIO(b"dump-data")
        self.returncode = 0
        FakePopen.created.append(args)

    def kill(self):
        self.returncode = -9

    def communicate(self, *args, **kwargs):
        return b"", b""


def _service(tmp_path) -> VCSMigrationService:
    service = VCSMigrationService(FakeConfig(_profile()))
    service._working_copy_url = lambda workspace: "svn://localhost/neon/svn"
    return service


def _make_project(tmp_path) -> Path:
    project_root = tmp_path / "Neon"
    (project_root / "svn" / ".svn").mkdir(parents=True)
    (project_root / "pipeline").mkdir(parents=True)
    with open(project_root / "pipeline" / "project_init.json", "w", encoding="utf-8") as handle:
        json.dump({"project_name": "Neon"}, handle)
    return project_root


def test_migrate_project_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SshRunner", FakeRunner)
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    monkeypatch.setattr(mod.subprocess, "Popen", FakePopen)
    FakeRunner.instances = []
    FakeSvnAdapter.relocated = []
    FakePopen.created = []

    project_root = _make_project(tmp_path)
    service = _service(tmp_path)

    ok, message = service.migrate_project(project_root, "artist", "secret")

    assert ok is True
    assert "migrated" in message.lower()
    # Dump/load happened and the working copy was repointed at the remote base.
    assert FakePopen.created
    assert FakeSvnAdapter.relocated == ["svn://svn-vps/neon/svn"]

    runner_commands = " ".join(FakeRunner.instances[0].commands)
    assert "docker exec -i" in runner_commands
    assert "svnadmin load" in runner_commands

    blueprint = json.loads((project_root / "pipeline" / "project_init.json").read_text(encoding="utf-8"))
    assert blueprint["vcs_base_url"] == "svn://svn-vps"


def test_migrate_project_skips_when_already_remote(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "SshRunner", FakeRunner)
    monkeypatch.setattr(mod, "SVNAdapter", FakeSvnAdapter)
    FakeRunner.instances = []
    FakeSvnAdapter.relocated = []

    project_root = _make_project(tmp_path)
    service = VCSMigrationService(FakeConfig(_profile()))
    service._working_copy_url = lambda workspace: "svn://svn-vps/neon/svn"

    ok, message = service.migrate_project(project_root, "artist", "secret")

    assert ok is True
    assert "already" in message.lower()
    assert FakeSvnAdapter.relocated == []


def test_migrate_project_requires_remote_mode(tmp_path):
    local_profile = VCSServerProfile(mode="local_docker")
    service = VCSMigrationService(FakeConfig(local_profile))

    ok, message = service.migrate_project(_make_project(tmp_path))

    assert ok is False
    assert "local" in message.lower()
