"""Unit tests for server-side repository lifecycle strategies."""

from types import SimpleNamespace

import pytest

from src.domain.workspace.vcs_server_profile import (
    REMOTE_SSH,
    RemoteSSHConfig,
    VCSServerProfile,
)
from src.infrastructure.vcs import ssh_runner
from src.infrastructure.vcs.repository_admin import (
    RemoteSSHRepositoryAdmin,
    normalize_repo_name,
    validate_repo_name,
)
from src.infrastructure.vcs.ssh_runner import SshRunner


def test_normalize_repo_name_matches_url_segment():
    assert normalize_repo_name("MIDEQ_promo") == "mideq_promo"
    assert normalize_repo_name("  My Project  ") == "my-project"


@pytest.mark.parametrize("bad_name", ["bad/name", "bad name", "..", "", "UPPER", "a;rm -rf /"])
def test_validate_repo_name_rejects_unsafe_values(bad_name):
    with pytest.raises(ValueError):
        validate_repo_name(bad_name)


def _remote_profile() -> VCSServerProfile:
    return VCSServerProfile(
        mode=REMOTE_SSH,
        remote=RemoteSSHConfig(
            host="svn-vps",
            ssh_user="ops",
            container="estudio_svn",
            repo_root="/var/opt/svn",
        ),
    )


def _flat(calls) -> str:
    return " ".join(" ".join(str(part) for part in call) for call in calls)


def test_wrap_runs_commands_inside_container():
    profile = _remote_profile()
    admin = RemoteSSHRepositoryAdmin(profile, SshRunner(profile.remote))

    wrapped = admin._wrap("svnadmin create /var/opt/svn/neon")

    assert wrapped.startswith("docker exec estudio_svn sh -c ")
    assert "svnadmin create" in wrapped

    interactive = admin._wrap("cat > /var/opt/svn/neon/conf/svnserve.conf", interactive=True)
    assert interactive.startswith("docker exec -i estudio_svn sh -c ")


def test_wrap_requires_container():
    profile = VCSServerProfile(
        mode=REMOTE_SSH,
        remote=RemoteSSHConfig(host="h", ssh_user="u"),
    )
    admin = RemoteSSHRepositoryAdmin(profile, SshRunner(profile.remote))

    with pytest.raises(RuntimeError):
        admin._wrap("echo hi")


def test_remote_create_provisions_repo_and_topology(monkeypatch):
    calls = []
    inputs = []

    def fake_run(args, **kwargs):
        calls.append(args)
        inputs.append(kwargs.get("input"))
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    admin = RemoteSSHRepositoryAdmin(_remote_profile(), SshRunner(_remote_profile().remote))
    assert admin.create("Neon", "svn") is True

    flat = _flat(calls)
    assert "docker exec" in flat
    assert "svnadmin create /var/opt/svn/neon" in flat
    assert "svn mkdir file:///var/opt/svn/neon/svn" in flat
    # A fresh repo points at the studio-wide passwd by default (written via stdin).
    written = b"".join(part for part in inputs if part)
    assert b"password-db = /var/opt/svn/passwd" in written


def test_remote_create_can_skip_topology(monkeypatch):
    calls = []
    inputs = []

    def fake_run(args, **kwargs):
        calls.append(args)
        inputs.append(kwargs.get("input"))
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    admin = RemoteSSHRepositoryAdmin(_remote_profile(), SshRunner(_remote_profile().remote))
    assert admin.create("Neon", "svn", initialize_topology=False) is True

    flat = _flat(calls)
    assert "svnadmin create /var/opt/svn/neon" in flat
    # Migration targets are created empty so the dump restores revision 1.
    assert "svn mkdir" not in flat


def test_remote_create_is_idempotent(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    admin = RemoteSSHRepositoryAdmin(_remote_profile(), SshRunner(_remote_profile().remote))
    assert admin.create("Neon", "svn") is True
    # Only the existence probe ran; no creation command.
    assert "svnadmin create" not in _flat(calls)


def test_remote_destroy_reports_absent_repo(monkeypatch):
    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    admin = RemoteSSHRepositoryAdmin(_remote_profile(), SshRunner(_remote_profile().remote))
    ok, message = admin.destroy("Neon", "svn")

    assert ok is True
    assert "absent" in message.lower()
