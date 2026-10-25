"""Unit tests for the VCS audit trail."""

import pytest

from src.infrastructure.vcs.svn_runner import SvnCommandRunner
from src.infrastructure.vcs.vcs_audit import VcsAuditLogger


def test_audit_logger_writes_and_reads_events(tmp_path):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")

    assert logger.log(
        "commit",
        project="Neon",
        server="svn.example.com",
        user="ana",
        paths=["pro/a.blend"],
        ok=True,
        revision="42",
        duration_ms=12,
    )

    events = logger.read_recent()
    assert len(events) == 1
    assert events[0]["operation"] == "commit"
    assert events[0]["project"] == "Neon"
    assert events[0]["user"] == "ana"
    assert events[0]["paths"] == ["pro/a.blend"]
    assert events[0]["revision"] == "42"


def test_audit_logger_redacts_password_arguments(tmp_path):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")

    logger.log(
        "commit",
        command=["commit", "--password", "secret", "pro/a.blend"],
        message="failed with --password secret",
    )

    event = logger.read_recent()[0]
    assert event["command"] == ["commit", "--password", "***", "pro/a.blend"]
    assert "secret" not in event["message"]


def test_runner_records_successful_operations(tmp_path):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")
    runner = SvnCommandRunner(
        "/bin/echo",
        audit=logger,
        project="Neon",
        server="svn.example.com",
    )

    runner.run(["commit", "-m", "msg", "pro/a.blend"], non_interactive=False)

    event = logger.read_recent()[0]
    assert event["operation"] == "commit"
    assert event["project"] == "Neon"
    assert event["server"] == "svn.example.com"
    assert event["paths"] == ["pro/a.blend"]
    assert event["ok"] is True


def test_runner_records_failures_and_error_codes(tmp_path):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")
    runner = SvnCommandRunner("/bin/sh", audit=logger)

    with pytest.raises(Exception):
        runner.run(
            ["-c", "echo 'svn: E170001: Authorization failed' >&2; exit 1"],
            non_interactive=False,
        )

    event = logger.read_recent()[0]
    assert event["ok"] is False
    assert event["error_code"] == "E170001"


def test_runner_records_timeouts(tmp_path):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")
    runner = SvnCommandRunner("/bin/sleep", audit=logger)

    with pytest.raises(Exception):
        runner.run(["2"], timeout=0.1, non_interactive=False)

    event = logger.read_recent()[0]
    assert event["ok"] is False
    assert "timed out" in event["message"].lower()
