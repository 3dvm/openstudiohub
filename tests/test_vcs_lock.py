"""Unit tests for SVN locking helpers (svn info / propset / relocate)."""

from pathlib import Path
from types import SimpleNamespace

from src.infrastructure.vcs import svn_adapter
from src.infrastructure.vcs.svn_adapter import SVNAdapter


def _adapter() -> SVNAdapter:
    return SVNAdapter("svn://localhost/repos/proj/svn", Path("/tmp/workspace"))


def _fake_run(output: str, calls: list):
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout=output)

    return fake_run


def test_get_lock_info_parses_owner_and_token(monkeypatch):
    output = "\n".join([
        "Path: pro/assets/monkey/monkey-model.blend",
        "Lock Token: opaquelocktoken:abc-123",
        "Lock Owner: artist@studio.com",
        "Lock Created: 2026-01-01",
    ])
    calls = []
    monkeypatch.setattr(svn_adapter.subprocess, "run", _fake_run(output, calls))

    info = _adapter().get_lock_info("pro/assets/monkey/monkey-model.blend")

    assert info["owner"] == "artist@studio.com"
    assert info["token"].endswith("abc-123")
    assert calls[0] == ["svn", "info", "pro/assets/monkey/monkey-model.blend"]


def test_get_lock_info_returns_none_when_unlocked(monkeypatch):
    calls = []
    monkeypatch.setattr(svn_adapter.subprocess, "run", _fake_run("Path: pro/a.blend\n", calls))

    assert _adapter().get_lock_info("pro/a.blend") is None


def test_set_needs_lock_is_recursive(monkeypatch):
    calls = []
    monkeypatch.setattr(svn_adapter.subprocess, "run", _fake_run("", calls))

    assert _adapter().set_needs_lock("pro") is True
    assert calls[0] == ["svn", "propset", "svn:needs-lock", "yes", "-R", "pro"]


def test_relocate_targets_new_url(monkeypatch):
    calls = []
    monkeypatch.setattr(svn_adapter.subprocess, "run", _fake_run("", calls))

    assert _adapter().relocate("svn://vps/neon/svn") is True
    assert calls[0][:3] == ["svn", "relocate", "svn://vps/neon/svn"]
