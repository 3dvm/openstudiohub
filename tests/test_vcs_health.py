"""Unit tests for the VCS server health probe and repository rollback."""

import socket
from pathlib import Path
from types import SimpleNamespace

from src.domain.workspace.vcs_server_profile import (
    REMOTE_SSH,
    RemoteSSHConfig,
    VCSServerProfile,
)
from src.infrastructure.vcs import ssh_runner, svn_adapter
from src.infrastructure.vcs.svn_adapter import SVNAdapter
from src.infrastructure.vcs.vcs_router import VCSRouter


def _adapter(url: str) -> SVNAdapter:
    return SVNAdapter(url, Path("/tmp/workspace"))


def _remote_adapter(url: str) -> SVNAdapter:
    profile = VCSServerProfile(
        mode=REMOTE_SSH,
        remote=RemoteSSHConfig(
            host="svn.example.com",
            ssh_user="ops",
            container="estudio_svn",
            repo_root="/srv/svn",
        ),
    )
    return SVNAdapter(url, Path("/tmp/workspace"), server_profile=profile)


def test_endpoint_defaults_to_svn_port():
    assert _adapter("svn://svn.example.com/repo")._server_endpoint() == ("svn.example.com", 3690)


def test_endpoint_respects_explicit_port():
    assert _adapter("svn://svn.example.com:1234/repo")._server_endpoint() == ("svn.example.com", 1234)


def test_endpoint_https_default_port():
    assert _adapter("https://svn.example.com/repo")._server_endpoint() == ("svn.example.com", 443)


def test_health_success_uses_socket(monkeypatch):
    adapter = _adapter("svn://svn.example.com/repo")
    seen = {}

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_connect(address, timeout=None):
        seen["address"] = address
        seen["timeout"] = timeout
        return _Conn()

    monkeypatch.setattr(socket, "create_connection", fake_connect)

    ok, message = adapter.check_server_health(timeout=3.0)

    assert ok is True
    assert seen["address"] == ("svn.example.com", 3690)
    assert seen["timeout"] == 3.0
    assert "reachable" in message.lower()


def test_health_failure_reports_unreachable(monkeypatch):
    adapter = _adapter("svn://svn.example.com/repo")

    def fake_connect(address, timeout=None):
        raise OSError("Connection refused")

    monkeypatch.setattr(socket, "create_connection", fake_connect)

    ok, message = adapter.check_server_health()

    assert ok is False
    assert "unreachable" in message.lower()
    assert "Connection refused" in message


def test_remote_repository_deletion_is_supported(monkeypatch):
    adapter = _remote_adapter("svn://svn.example.com/repo")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    ok, message = adapter.destroy_server_repository("Neon", "svn")

    assert ok is True
    assert "removed" in message.lower()
    # The remote command must target the configured server path.
    assert any("rm -rf" in str(part) for part in calls)


def test_remote_repository_creation_uses_ssh(monkeypatch):
    adapter = _remote_adapter("svn://svn.example.com/repo")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        # `test -d` reports "not found" so creation proceeds.
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    ok = adapter.create_server_repository("MIDEQ_promo", "svn")

    assert ok is True
    flat = " ".join(" ".join(str(a) for a in call) for call in calls)
    assert "svnadmin create" in flat
    assert "mideq_promo" in flat


def test_probe_health_when_vcs_disabled():
    ok, _ = VCSRouter.probe_health("none", "")
    assert ok is True


def test_repo_name_normalization_matches_url_segment():
    assert SVNAdapter._normalized_repo_name("MIDEQ_promo") == "mideq_promo"
    assert SVNAdapter._normalized_repo_name("  My Project  ") == "my-project"


def test_destroy_uses_normalized_local_path(monkeypatch):
    adapter = _adapter("svn://localhost/projects")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return None

    monkeypatch.setattr(svn_adapter.subprocess, "run", fake_run)

    ok, _ = adapter.destroy_server_repository("MIDEQ_promo", "svn")

    assert ok is True
    assert "/home/svn/mideq_promo" in calls[0]
