"""Unit tests for VCS history, diff and revision export."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application.services.task_file_sync_service import TaskFileSyncService
from src.infrastructure.vcs import svn_adapter
from src.infrastructure.vcs.svn_adapter import SVNAdapter
from src.infrastructure.vcs.svn_runner import SvnResult

LOG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<log>
<logentry revision="7">
  <author>ana</author>
  <date>2026-01-01T10:00:00.000000Z</date>
  <msg>Update model</msg>
  <paths><path action="M" kind="file">/pro/a.blend</path></paths>
</logentry>
<logentry revision="5">
  <author>bo</author>
  <date>2026-01-01T09:00:00.000000Z</date>
  <msg>Initial model</msg>
</logentry>
</log>
"""


def _adapter() -> SVNAdapter:
    return SVNAdapter("svn://localhost/repos/proj/svn", Path("/tmp/workspace"))


def _fake_run(output: str, calls: list):
    def fake_run(_runner, args, **kwargs):
        calls.append((["svn", *args], kwargs))
        return SvnResult(ok=True, returncode=0, stdout=output, stderr="")

    return fake_run


def test_get_log_parses_revisions_and_passes_credentials(monkeypatch):
    calls = []
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run(LOG_XML, calls))

    revisions = _adapter().get_log("pro/a.blend", limit=5, username="ana", password="secret")

    assert revisions[0]["revision"] == "7"
    assert revisions[0]["author"] == "ana"
    assert revisions[0]["message"] == "Update model"
    assert revisions[1]["revision"] == "5"
    command = calls[0][0]
    assert command[:5] == ["svn", "log", "--xml", "-l", "5"]
    assert "pro/a.blend" in command
    assert "--username" in command


def test_get_diff_targets_revision(monkeypatch):
    calls = []
    monkeypatch.setattr(svn_adapter.SvnCommandRunner, "run", _fake_run("diff text", calls))

    text = _adapter().get_diff("pro/a.blend", revision=7)

    assert text == "diff text"
    assert calls[0][0][:5] == ["svn", "diff", "-c", "7", "pro/a.blend"]


def test_export_revision_writes_binary_destination(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        kwargs["stdout"].write(b"BLEND-DATA")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(svn_adapter.subprocess, "run", fake_run)
    destination = tmp_path / "exported.blend"

    assert _adapter().export_revision("pro/a.blend", 7, destination, "ana", "secret")
    assert destination.read_bytes() == b"BLEND-DATA"
    assert calls[0][1:5] == ["cat", "-r", "7", "pro/a.blend"]


class FakeHistoryAdapter:
    def __init__(self) -> None:
        self.log_calls = []
        self.diff_calls = []
        self.export_calls = []

    def get_log(self, path, limit=20, username=None, password=None):
        self.log_calls.append((path, limit, username, password))
        return [{"revision": "7"}]

    def get_diff(self, path, revision=None, username=None, password=None):
        self.diff_calls.append((path, revision, username, password))
        return "diff"

    def export_revision(self, path, revision, destination, username=None, password=None):
        self.export_calls.append((path, revision, Path(destination), username, password))
        Path(destination).write_bytes(b"data")
        return True


class FakeConfig:
    def get_vcs_adapter_type(self) -> str:
        return "svn"

    def get_vcs_repository_url(self) -> str:
        return "svn://localhost/repos"

    def get_vfs_svn_name(self) -> str:
        return "svn"


class FakeRouter:
    adapter = None

    def __init__(self, **kwargs) -> None:
        pass

    def get_adapter(self):
        return FakeRouter.adapter


def _service(tmp_path):
    adapter = FakeHistoryAdapter()
    FakeRouter.adapter = adapter
    return TaskFileSyncService(FakeConfig(), router_factory=FakeRouter), adapter


def test_service_history_and_diff_delegate_with_credentials(tmp_path):
    service, adapter = _service(tmp_path)

    assert service.get_file_history(tmp_path / "p", "pro/a.blend", 10, "ana", "secret") == [
        {"revision": "7"}
    ]
    assert service.get_file_diff(tmp_path / "p", "pro/a.blend", 7, "ana", "secret") == "diff"
    assert adapter.log_calls == [("pro/a.blend", 10, "ana", "secret")]
    assert adapter.diff_calls == [("pro/a.blend", 7, "ana", "secret")]


def test_service_export_revision_delegates(tmp_path):
    service, adapter = _service(tmp_path)
    destination = tmp_path / "exported.blend"

    ok, message = service.export_file_revision(
        tmp_path / "p", "pro/a.blend", 7, destination, "ana", "secret"
    )

    assert ok is True
    assert "exported" in message.lower()
    assert adapter.export_calls == [
        ("pro/a.blend", 7, destination, "ana", "secret")
    ]


def test_service_history_requires_vcs(tmp_path):
    FakeRouter.adapter = FakeHistoryAdapter()
    config = FakeConfig()
    config.get_vcs_adapter_type = lambda: "none"
    service = TaskFileSyncService(config, router_factory=FakeRouter)

    with pytest.raises(RuntimeError):
        service.get_file_history(tmp_path / "p", "pro/a.blend")
