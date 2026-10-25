"""Unit tests for the per-user comment read state and UI preferences."""

from src.infrastructure.comment_read_store import CommentReadStore
from src.infrastructure.ui_prefs_store import UiPrefsStore


def _comment(comment_id, created, person_id="u2"):
    return {"id": comment_id, "created_at": created, "person_id": person_id}


def test_comment_read_store_is_per_user_and_persistent(tmp_path):
    path = tmp_path / "seen.json"
    store = CommentReadStore(path=path)
    store.set_last_seen("u1", "t1", "2026-10-20T10:00:00+00:00")

    assert store.get_last_seen("u1", "t1") == "2026-10-20T10:00:00+00:00"
    assert store.get_last_seen("u2", "t1") is None

    reloaded = CommentReadStore(path=path)
    assert reloaded.get_last_seen("u1", "t1") == "2026-10-20T10:00:00+00:00"


def test_comment_read_store_mark_seen_uses_newest_comment(tmp_path):
    store = CommentReadStore(path=tmp_path / "seen.json")
    comments = [
        _comment("a", "2026-10-20T09:00:00Z"),
        _comment("b", "2026-10-20T12:00:00Z"),
    ]

    value = store.mark_seen("u1", "t1", comments)

    assert value == "2026-10-20T12:00:00+00:00"
    assert store.get_last_seen("u1", "t1") == value


def test_ui_prefs_store_persists_values(tmp_path):
    path = tmp_path / "prefs.json"
    store = UiPrefsStore(path=path)
    assert store.get("u1", "task_board_view", "table") == "table"

    store.set("u1", "task_board_view", "cards")

    assert store.get("u1", "task_board_view") == "cards"
    assert UiPrefsStore(path=path).get("u1", "task_board_view") == "cards"
    assert UiPrefsStore(path=path).get("u2", "task_board_view", "table") == "table"
