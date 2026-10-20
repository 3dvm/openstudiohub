"""Unit tests for comment ordering and unread computation."""

from src.domain.production.comments import (
    checklist_progress,
    comment_author_id,
    comment_parent_id,
    newest_comment_timestamp,
    normalize_checklist,
    parse_timestamp,
    sort_comments,
    to_iso,
    unread_comment_count,
)


def _comment(comment_id, created, person_id="u2", parent_id=""):
    data = {"id": comment_id, "created_at": created, "person_id": person_id, "text": comment_id}
    if parent_id:
        data["parent_id"] = parent_id
    return data


def test_parse_timestamp_accepts_z_and_naive_values():
    assert parse_timestamp("2026-10-20T10:00:00Z").isoformat() == "2026-10-20T10:00:00+00:00"
    assert parse_timestamp("2026-10-20T10:00:00").tzinfo is not None
    assert parse_timestamp("not-a-date") is None
    assert parse_timestamp(None) is None


def test_sort_comments_keeps_parents_before_replies():
    parent = _comment("p", "2026-10-20T10:00:00Z")
    reply = _comment("r", "2026-10-20T09:00:00Z", parent_id="p")

    ordered = sort_comments([reply, parent])

    assert [item["id"] for item in ordered] == ["p", "r"]


def test_comment_parent_and_author_helpers():
    expanded = {"person": {"id": "u9"}, "reply_to": {"id": "c1"}}
    assert comment_parent_id(expanded) == "c1"
    assert comment_author_id(expanded) == "u9"
    assert comment_author_id({"person_id": "u3"}) == "u3"


def test_unread_excludes_own_comments_and_older_ones():
    comments = [
        _comment("old", "2026-10-20T09:00:00Z", person_id="u2"),
        _comment("mine", "2026-10-20T11:00:00Z", person_id="me"),
        _comment("new", "2026-10-20T12:00:00Z", person_id="u2"),
    ]

    assert unread_comment_count(comments, "me", to_iso(parse_timestamp("2026-10-20T10:00:00Z"))) == 1


def test_unread_without_last_seen_is_zero_outside_baseline():
    comments = [_comment("new", "2026-10-20T12:00:00Z")]
    assert unread_comment_count(comments, "me", None) == 0


def test_newest_comment_timestamp():
    comments = [
        _comment("a", "2026-10-20T09:00:00Z"),
        _comment("b", "2026-10-20T12:00:00Z"),
    ]
    assert to_iso(newest_comment_timestamp(comments)) == "2026-10-20T12:00:00+00:00"


def test_normalize_checklist_accepts_list_string_and_mapping():
    expected = [
        {"text": "Check lighting", "checked": True},
        {"text": "Verify textures", "checked": False},
    ]
    value = [
        {"text": "Check lighting", "checked": True},
        {"text": "Verify textures", "checked": False},
    ]
    assert normalize_checklist(value) == expected
    assert normalize_checklist('[{"text": "Check lighting", "checked": true}, '
                               '{"text": "Verify textures", "checked": false}]') == expected
    assert normalize_checklist(
        {"item1": "Check lighting", "item2": "Verify textures"}
    ) == [
        {"text": "Check lighting", "checked": False},
        {"text": "Verify textures", "checked": False},
    ]
    assert normalize_checklist(None) == []
    assert normalize_checklist("not-json") == []


def test_checklist_progress_counts_checked_items():
    comments = [
        {"checklist": [{"text": "a", "checked": True}, {"text": "b", "checked": False}]},
        {"checklist": [{"text": "c", "checked": True}]},
    ]
    assert checklist_progress(comments) == (2, 3)
    assert checklist_progress([]) == (0, 0)
