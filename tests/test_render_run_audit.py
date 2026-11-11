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


def test_node_event_writes_a_dedicated_log_even_on_success(tmp_path):
    logger = RenderRunAuditLogger(tmp_path / "render_runs.jsonl")

    logger.node_event("node_finished", run_id="r2", node=3, ok=True, message="done")
    summary = logger.node_summary("r2", 3, {"node": 3, "ok": True})

    node_log = logger.node_log_path("r2", 3)
    assert node_log.is_file()
    assert "node_finished" in node_log.read_text(encoding="utf-8")
    assert summary is not None and summary.name == "node-3.json"


def test_blender_output_has_its_own_file(tmp_path):
    logger = RenderRunAuditLogger(tmp_path / "render_runs.jsonl")
    path = logger.blender_log_path("r3", 1, "sh010")

    logger.append_blender_output(path, "OSFRAME::{}")

    assert path.name == "node-1-blender-sh010.log"
    assert "OSFRAME" in path.read_text(encoding="utf-8")


def test_node_zero_uses_its_real_label(tmp_path):
    logger = RenderRunAuditLogger(tmp_path / "render_runs.jsonl")

    assert logger.node_log_path("r4", 0).name == "node-0.log"
    summary = logger.node_summary("r4", 0, {"node": 0, "ok": True})
    assert summary is not None and summary.name == "node-0.json"
