"""Unit tests for the TD VCS audit ViewModel."""

from src.infrastructure.vcs.vcs_audit import VcsAuditLogger
from src.interfaces.qt.viewmodels.vcs_audit_viewmodel import VcsAuditViewModel


def _logger(tmp_path):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")
    logger.log("commit", project="Neon", user="ana", paths=["pro/a.blend"], ok=True)
    logger.log(
        "lock",
        project="Other",
        user="bo",
        paths=["pro/b.blend"],
        ok=False,
        error_code="E160039",
        message="already locked",
    )
    return logger


def test_load_returns_events_newest_first(tmp_path, qapp):
    vm = VcsAuditViewModel(_logger(tmp_path))
    received = []
    vm.events_loaded.connect(received.append)

    events = vm.load()

    assert [event["operation"] for event in events] == ["lock", "commit"]
    assert received == [events]


def test_load_filters_by_search_text(tmp_path, qapp):
    vm = VcsAuditViewModel(_logger(tmp_path))

    events = vm.load(search="neon")

    assert len(events) == 1
    assert events[0]["project"] == "Neon"


def test_load_can_show_only_failures(tmp_path, qapp):
    vm = VcsAuditViewModel(_logger(tmp_path))

    events = vm.load(only_failures=True)

    assert len(events) == 1
    assert events[0]["operation"] == "lock"


def test_audit_path_is_exposed(tmp_path, qapp):
    logger = _logger(tmp_path)
    vm = VcsAuditViewModel(logger)

    assert vm.audit_path == logger.path
