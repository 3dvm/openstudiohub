"""Unit tests for the SVN adapter's local-change scan and add staging."""

from pathlib import Path
from types import SimpleNamespace

from src.infrastructure.vcs import svn_adapter
from src.infrastructure.vcs.svn_adapter import SVNAdapter


def _adapter() -> SVNAdapter:
    return SVNAdapter("svn://localhost/repos/proj/svn", Path("/tmp/workspace"))


def _fake_run(output: str, calls: list):
    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs.get("cwd")))
        return SimpleNamespace(stdout=output)

    return fake_run


def test_get_status_parses_changed_and_new_files(monkeypatch):
    output = "\n".join([
        f"{'M':<8}pro/assets/char/monkey/monkey-model.blend",
        f"{'?':<8}pro/assets/char/monkey/tex/new.png",
        f"{'A':<8}pro/assets/char/monkey/extra.blend",
        f"{'!':<8}pro/assets/char/monkey/gone.blend",
    ])
    calls = []
    monkeypatch.setattr(svn_adapter.subprocess, "run", _fake_run(output, calls))

    status = _adapter().get_status()

    assert status == {
        "pro/assets/char/monkey/monkey-model.blend": "M",
        "pro/assets/char/monkey/tex/new.png": "?",
        "pro/assets/char/monkey/extra.blend": "A",
        "pro/assets/char/monkey/gone.blend": "!",
    }
    assert calls[0][0] == ["svn", "status"]
    assert calls[0][1] == "/tmp/workspace"


def test_get_status_accepts_scoped_path(monkeypatch):
    calls = []
    monkeypatch.setattr(svn_adapter.subprocess, "run", _fake_run("", calls))

    _adapter().get_status("pro/assets")

    assert calls[0][0] == ["svn", "status", "pro/assets"]


def test_add_stages_selected_paths(monkeypatch):
    calls = []
    monkeypatch.setattr(svn_adapter.subprocess, "run", _fake_run("", calls))

    assert _adapter().add(["pro/tex/new.png", "pro/tex/other.png"]) is True

    assert calls[0][0] == [
        "svn",
        "add",
        "--force",
        "--parents",
        "pro/tex/new.png",
        "pro/tex/other.png",
    ]
    assert calls[0][1] == "/tmp/workspace"


def test_add_with_no_paths_is_a_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(svn_adapter.subprocess, "run", _fake_run("", calls))

    assert _adapter().add([]) is True
    assert calls == []
