"""Unit tests for the local render run audit trail."""

import json

from src.infrastructure.render.run_audit import RenderRunAuditLogger


def test_audit_writes_events_summary_and_node_log(tmp_path):
    logger = RenderRunAuditLogger(tmp_path / "render_runs.jsonl")

    assert logger.log("run_start", run_id="r1", backend="vast") is True
    node_log = logger.write_node_log("r1", 2, "stage: install\nboom")
    summary = logger.write_summary("r1", {"ok": False})

    events = logger.read_recent()
    assert events[-1]["event"] == "run_start"
    assert events[-1]["run_id"] == "r1"
    assert node_log is not None and "boom" in node_log.read_text(encoding="utf-8")
    assert summary is not None
    assert json.loads(summary.read_text(encoding="utf-8"))["ok"] is False
