# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/ui_prefs_store.py
# Architectural role: Infrastructure / per-user UI preferences
# =========================================================================================

"""Tiny per-user UI preferences store (JSON under ``~/.openstudio/state``)."""

from typing import Any, Optional

from src.infrastructure.json_state import default_state_dir, load_json, save_json_atomic


class UiPrefsStore:
    def __init__(self, path=None) -> None:
        self.path = path or (default_state_dir() / "ui_prefs.json")
        self._data = load_json(self.path)

    def get(self, user_id: str, key: str, default: Optional[Any] = None) -> Any:
        entry = self._data.get(str(user_id or "")) or {}
        return entry.get(key, default)

    def set(self, user_id: str, key: str, value: Any) -> None:
        entry = self._data.setdefault(str(user_id or ""), {})
        entry[key] = value
        save_json_atomic(self.path, self._data)
