# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/comment_read_store.py
# Architectural role: Infrastructure / per-user task comment read state
# =========================================================================================

"""Local "last seen" timestamps for task comments.

Kitsu/gazu expose no per-user read state, so the Hub tracks it locally per
Kitsu person (``user_id``) and task. The file lives under ``~/.openstudio`` and
is written atomically; it is per machine (a second machine will re-show what is
new there).
"""

from typing import Iterable, Optional

from src.domain.production.comments import newest_comment_timestamp, to_iso
from src.infrastructure.json_state import default_state_dir, load_json, save_json_atomic


class CommentReadStore:
    def __init__(self, path=None) -> None:
        self.path = path or (default_state_dir() / "task_comments_seen.json")
        self._data = load_json(self.path)

    def _user_entry(self, user_id: str) -> dict:
        return self._data.setdefault(str(user_id or ""), {})

    def get_last_seen(self, user_id: str, task_id: str) -> Optional[str]:
        entry = self._data.get(str(user_id or "")) or {}
        return entry.get(str(task_id or "")) or None

    def set_last_seen(self, user_id: str, task_id: str, value: Optional[str]) -> None:
        if not value:
            return
        self._user_entry(user_id)[str(task_id or "")] = value
        save_json_atomic(self.path, self._data)

    def mark_seen(self, user_id: str, task_id: str, comments: Iterable[dict]) -> Optional[str]:
        """Store the newest comment timestamp of ``comments`` for this task."""
        newest = newest_comment_timestamp(comments)
        value = to_iso(newest)
        self.set_last_seen(user_id, task_id, value)
        return value
