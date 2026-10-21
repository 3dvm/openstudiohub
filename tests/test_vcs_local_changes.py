"""Unit tests for the SVN adapter's local-change scan and add staging."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure.dev_defaults import DEV_SVN_PASSWORD, DEV_SVN_USER
from src.infrastructure.vcs import svn_adapter
from src.infrastructure.vcs.svn_adapter import SVNAdapter
from src.infrastructure.vcs.svn_runner import SvnResult


def _adapter() -> SVNAdapter:
    return SVNAdapter("svn://localhost/repos/proj/svn", Path("/tmp/workspace"))


def _fake_run(output: str, calls: list, stdin_calls: list | None = None):
    def fake_run(_runner, args, **kwargs):
        cwd = kwargs.get("cwd")
        calls.append((["svn", *args], str(cwd) if cwd is not None else None))
        if stdin_calls is not None:
            stdin_calls.append(kwargs.get("stdin_text"))
        return SvnResult(ok=True, returncode=0, stdout=output, stderr="")

    return fake_run


def test_get_status_parses_changed_and_new_files(monkeypatch):
    output = "\n".join([
        f"{'M':<8}pro/assets/char/monkey/monkey-model.blend",
        f"{'?':<8}pro/assets/char/monkey/tex/new.png",
        f"{'A':<8}pro/assets/char/monkey/extra.blend",
        f"{'!':<8}pro/assets/char/monkey/gone.blend",
    ])
    calls = []
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run(output, calls))

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
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run("", calls))

    _adapter().get_status("pro/assets")

    assert calls[0][0] == ["svn", "status", "pro/assets"]


def test_add_stages_selected_paths(monkeypatch):
    calls = []
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run("", calls))

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
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run("", calls))

    assert _adapter().add([]) is True
    assert calls == []


def test_commit_builds_expected_command(monkeypatch):
    calls = []
    stdin_calls = []
    monkeypatch.setattr(
        svn_adapter.SvnCommandRunner,
        "run",
        _fake_run("", calls, stdin_calls),
    )

    assert _adapter().commit("msg", ["pro/a.blend"], "artist", "secret") is True

    # Local Docker URLs force the dev bootstrap credentials. The password is
    # sent over stdin instead of being exposed in the process list.
    assert calls[0][0] == [
        "svn", "commit", "-m", "msg", "pro/a.blend",
        "--non-interactive",
        "--username", DEV_SVN_USER, "--no-auth-cache", "--password-from-stdin",
    ]
    assert stdin_calls == [DEV_SVN_PASSWORD + "\n"]
    assert calls[0][1] == "/tmp/workspace"


def test_assert_no_conflicts_raises_on_tree_conflict(monkeypatch):
    output = "\n".join([
        "D     C pro",
        "      >   local unversioned, incoming dir add upon update",
    ])
    calls = []
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run(output, calls))

    with pytest.raises(RuntimeError):
        _adapter()._assert_no_conflicts()


def test_assert_no_conflicts_passes_when_clean(monkeypatch):
    calls = []
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run("", calls))

    _adapter()._assert_no_conflicts()  # must not raise
    assert calls[0][0] == ["svn", "status"]


def test_full_pull_raises_when_conflicts_remain(monkeypatch):
    output = "\n".join([
        "D     C tools",
        "      >   local unversioned, incoming dir add upon update",
    ])
    calls = []
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run(output, calls))

    with pytest.raises(RuntimeError):
        _adapter().full_pull("artist", "secret")


def test_assert_no_conflicts_raises_on_obstructed_path(monkeypatch):
    output = "~       pro/assets/monkey/monkey-model.blend"
    calls = []
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run(output, calls))

    with pytest.raises(RuntimeError):
        _adapter()._assert_no_conflicts()


def test_get_status_entries_parses_xml_and_normalizes_paths(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    xml = (
        f'<status><target path="{workspace}">'
        f'<entry path="{workspace}/pro/a.blend">'
        '<wc-status item="modified" props="conflicted" tree-conflicted="false"/>'
        '</entry></target></status>'
    )
    calls = []
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run(xml, calls))

    adapter = SVNAdapter("svn://localhost/repos/proj/svn", workspace)
    entries = adapter.get_status_entries()

    assert entries[0].path == "pro/a.blend"
    assert entries[0].props == "conflicted"
    assert calls[0][0] == ["svn", "status", "--xml"]


def test_local_ignores_are_added_to_svn_commands(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run("", calls))
    adapter = SVNAdapter("svn://localhost/repos/proj/svn", workspace)
    adapter.set_local_ignores(["cache.tmp"])

    adapter.get_status()

    command = calls[0][0]
    assert "--config-option" in command
    assert "config:miscellany:global-ignores=cache.tmp" in command
