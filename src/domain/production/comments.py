# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/production/comments.py
# Architectural role: Production domain helpers (task comments)
# =========================================================================================

"""Comment ordering and unread computation for task timelines.

Kitsu stores comments/replies as a flat list where replies point at their parent
through ``parent_id`` (older exports used other names). The helpers here are
pure functions so both the artist and the PM/TD task boards share one policy.
"""

import json
from datetime import datetime, timezone
from typing import Iterable, List, Optional


def parse_timestamp(value) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (accepts ``Z``) into an aware UTC datetime."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_iso(value: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime as a UTC ISO string, or ``None``."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def comment_created_at(comment: dict) -> Optional[datetime]:
    return parse_timestamp(comment.get("created_at") or comment.get("createdAt"))


def comment_parent_id(comment: dict) -> str:
    """Kitsu/older exports may name the parent link differently."""
    for key in ("parent_id", "reply_to_id", "reply_to", "parent"):
        value = comment.get(key)
        if isinstance(value, dict):
            value = value.get("id")
        if value:
            return str(value)
    return ""


def comment_author_id(comment: dict) -> str:
    person = comment.get("person")
    if isinstance(person, dict) and person.get("id"):
        return str(person["id"])
    return str(comment.get("person_id") or "")


def sort_comments(comments: Iterable[dict]) -> List[dict]:
    """Return parents before their replies, stable by ``created_at``."""
    items = [comment for comment in comments or [] if isinstance(comment, dict)]
    by_id = {str(comment.get("id", "")): comment for comment in items}
    ordered: List[dict] = []
    seen = set()

    def visit(comment: dict) -> None:
        comment_id = str(comment.get("id", ""))
        if comment_id in seen:
            return
        parent_id = comment_parent_id(comment)
        parent = by_id.get(parent_id)
        if parent is not None and parent is not comment:
            visit(parent)
        seen.add(comment_id)
        ordered.append(comment)

    for comment in sorted(items, key=lambda c: str(c.get("created_at", ""))):
        visit(comment)
    return ordered


def newest_comment_timestamp(comments: Iterable[dict]) -> Optional[datetime]:
    dates = [comment_created_at(comment) for comment in comments or []]
    dates = [date for date in dates if date is not None]
    return max(dates) if dates else None


def normalize_checklist(value) -> List[dict]:
    """Normalize a Kitsu checklist to ``[{"text", "checked", ...}]``.

    Kitsu stores the checklist as JSONB but some payloads (and older exports)
    serialize it as a JSON string; hand-made payloads may also use a mapping.
    Extra keys are preserved so a later update does not drop server metadata.
    """
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else []
        except ValueError:
            return []
    if isinstance(value, dict):
        if isinstance(value.get("items"), list):
            value = value["items"]
        elif all(isinstance(item, str) for item in value.values()):
            value = [{"text": text, "checked": False} for text in value.values()]
        elif "text" in value:
            value = [value]
        else:
            return []
    if not isinstance(value, list):
        return []

    normalized: List[dict] = []
    for entry in value:
        if isinstance(entry, str):
            normalized.append({"text": entry, "checked": False})
            continue
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        item["text"] = str(item.get("text") or item.get("label") or item.get("name") or "")
        item["checked"] = bool(item.get("checked"))
        normalized.append(item)
    return normalized


def checklist_progress(comments: Iterable[dict]) -> tuple[int, int]:
    """Return ``(checked, total)`` across every checklist in ``comments``."""
    checked = total = 0
    for comment in comments or []:
        value = comment.get("checklist")
        if not value:
            value = comment.get("_checklist")
        for item in normalize_checklist(value):
            total += 1
            if item["checked"]:
                checked += 1
    return checked, total


def unread_comment_count(
    comments: Iterable[dict], current_user_id: str, last_seen: Optional[str]
) -> int:
    """Count comments newer than ``last_seen``, excluding the current user's own.

    ``last_seen is None`` means the task has never been observed; callers should
    baseline it (see ``newest_comment_timestamp``) instead of flagging every
    historical comment as new.
    """
    seen = parse_timestamp(last_seen)
    if seen is None:
        return 0
    me = str(current_user_id or "")
    count = 0
    for comment in comments or []:
        if me and comment_author_id(comment) == me:
            continue
        created = comment_created_at(comment)
        if created is not None and created > seen:
            count += 1
    return count
