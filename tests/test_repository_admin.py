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
    AUTO_PROPS,
    PRE_COMMIT_HOOK,
    LocalDockerRepositoryAdmin,
    RemoteSSHRepositoryAdmin,
    normalize_repo_name,
    parse_locks,
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


def test_repository_policy_marks_blend_files_as_needs_lock():
    assert "*.blend = svn:needs-lock=yes" in AUTO_PROPS
    assert "svn:needs-lock" in PRE_COMMIT_HOOK
    assert "*.blend1" in PRE_COMMIT_HOOK
    assert "*.cache" in PRE_COMMIT_HOOK


def test_local_create_applies_policy_and_installs_hook(monkeypatch):
    calls = []
    inputs = []

    def fake_run(args, **kwargs):
        calls.append(args)
        inputs.append(kwargs.get("input"))
        if args[:3] == ["docker", "exec", "openstudio_local_svn"] and args[3:5] == ["test", "-d"]:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("src.infrastructure.vcs.repository_admin.subprocess.run", fake_run)

    admin = LocalDockerRepositoryAdmin()
    assert admin.create("Neon", "svn") is True

    flat = " ".join(" ".join(str(part) for part in call) for call in calls)
    assert "svnmucc" in flat
    assert "svn:auto-props" in flat
    assert "svn:global-ignores" in flat
    assert "hooks/pre-commit" in flat
    assert any(part and b"needs-lock" in part for part in inputs)


def test_local_ensure_policy_refreshes_hooks_and_auto_props(monkeypatch):
    calls = []
    inputs = []

    def fake_run(args, **kwargs):
        calls.append(args)
        inputs.append(kwargs.get("input"))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("src.infrastructure.vcs.repository_admin.subprocess.run", fake_run)

    admin = LocalDockerRepositoryAdmin()
    ok, message = admin.ensure_policy("Neon")

    assert ok is True
    assert "policy" in message.lower()
    flat = " ".join(" ".join(str(part) for part in call) for call in calls)
    assert "svnmucc" in flat
    assert "hooks/pre-commit" in flat
    assert any(part and b"needs-lock" in part for part in inputs)


def test_remote_ensure_policy_refreshes_hooks_and_auto_props(monkeypatch):
    calls = []
    inputs = []

    def fake_run(args, **kwargs):
        calls.append(args)
        inputs.append(kwargs.get("input"))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    admin = RemoteSSHRepositoryAdmin(_remote_profile(), SshRunner(_remote_profile().remote))
    ok, message = admin.ensure_policy("Neon")

    assert ok is True
    assert "policy" in message.lower()
    flat = _flat(calls)
    assert "svnmucc" in flat
    assert "pre-commit" in flat
    assert any(part and b"needs-lock" in part for part in inputs)


LOCKS_OUTPUT = """Path: /svn/pro/a.blend
UUID Token: opaquelocktoken:abc
Owner: ana
Created: 2026-01-01 10:00:00 +0000 (Thu, 01 Jan 2026)
Expires:
Comment (1 line):
editing

Path: /svn/pro/b.blend
UUID Token: opaquelocktoken:def
Owner: bo
Created: 2026-01-01 11:00:00 +0000 (Thu, 01 Jan 2026)
Expires:
"""


def test_parse_locks_reads_owner_and_comment():
    locks = parse_locks(LOCKS_OUTPUT)

    assert len(locks) == 2
    assert locks[0]["path"] == "/svn/pro/a.blend"
    assert locks[0]["owner"] == "ana"
    assert locks[0]["comment"] == "editing"
    assert locks[1]["owner"] == "bo"


def test_local_list_and_break_locks(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if "lslocks" in args:
            return SimpleNamespace(returncode=0, stdout=LOCKS_OUTPUT, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.infrastructure.vcs.repository_admin.subprocess.run", fake_run)
    admin = LocalDockerRepositoryAdmin()

    ok, locks, _ = admin.list_locks("Neon")
    assert ok is True
    assert len(locks) == 2

    ok, message = admin.break_lock("Neon", "/svn/pro/a.blend")
    assert ok is True
    assert "removed" in message.lower()
    assert any("rmlocks" in args for args in calls)


def test_remote_list_and_break_locks(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=LOCKS_OUTPUT.encode(), stderr=b"")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)
    admin = RemoteSSHRepositoryAdmin(_remote_profile(), SshRunner(_remote_profile().remote))

    ok, locks, _ = admin.list_locks("Neon")
    assert ok is True
    assert len(locks) == 2

    ok, message = admin.break_lock("Neon", "/svn/pro/a.blend")
    assert ok is True
    assert "removed" in message.lower()
    assert any("rmlocks" in str(part) for part in calls)
