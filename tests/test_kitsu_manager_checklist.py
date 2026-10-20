"""Regression test for the minimal checklist update payload Kitsu requires."""

import gazu

from src.infrastructure.kitsu_manager import KitsuManager


def test_update_comment_checklist_sends_only_checklist(monkeypatch):
    captured = {}

    def fake_put(path, data, **kwargs):
        captured["path"] = path
        captured["data"] = data
        return {"id": "c1", "checklist": data["checklist"]}

    monkeypatch.setattr(gazu.raw, "put", fake_put)

    checklist = [{"text": "Check lighting", "checked": True}]
    result = KitsuManager().update_comment_checklist("c1", checklist)

    assert result["checklist"] == checklist
    assert captured == {
        "path": "data/comments/c1",
        "data": {"checklist": checklist},
    }
