"""Unlock must be safe when the file was already unlocked elsewhere."""

from src.infrastructure.vcs.svn_adapter import SVNAdapter
from src.infrastructure.vcs.svn_errors import VcsError


def test_unlock_skips_svn_when_the_file_has_no_lock(tmp_path):
    adapter = SVNAdapter("svn://example/repo", tmp_path)
    calls = []

    adapter.get_lock_info = lambda path: None
    adapter._run_subprocess = lambda *args, **kwargs: calls.append(args)

    assert adapter.unlock("pro/a.blend") is True
    assert calls == []


def test_unlock_ignores_a_race_that_removed_the_lock(tmp_path):
    adapter = SVNAdapter("svn://example/repo", tmp_path)
    infos = [
        {"owner": "artist", "token": "token"},  # pre-check
        None,  # another client released it before the command
    ]

    adapter.get_lock_info = lambda path: infos.pop(0)

    def fail_unlock(*args, **kwargs):
        raise VcsError("is not locked in this working copy", code="E195013")

    adapter._run_subprocess = fail_unlock

    assert adapter.unlock("pro/a.blend") is True
