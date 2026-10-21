# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/notification_service.py
# Architectural role: Application service / in-app notification center
# =========================================================================================

"""Persist and deduplicate in-app notifications.

The first version feeds from the VCS audit trail. The service is deliberately
UI-free so additional sources (Kitsu activity, publish events) can be added
without changing the presentation layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.domain.notifications import Notification
from src.infrastructure.json_state import default_state_dir, load_json, save_json_atomic
from src.infrastructure.vcs.vcs_audit import VcsAuditLogger


class NotificationService:
    def __init__(
        self,
        audit_logger: Optional[VcsAuditLogger] = None,
        *,
        user_id_provider: Optional[Callable[[], str]] = None,
        role_provider: Optional[Callable[[], str]] = None,
        state_dir: Optional[Path] = None,
        max_items: int = 100,
    ) -> None:
        self.audit = audit_logger or VcsAuditLogger()
        self._user_id_provider = user_id_provider or (lambda: "default")
        self._role_provider = role_provider or (lambda: "")
        self._state_dir = Path(state_dir) if state_dir is not None else default_state_dir()
        self.max_items = max(10, int(max_items))
        self._user_id = ""
        self._items: list[Notification] = []
        self._seen: set[str] = set()
        self._baseline_done = False
        self._ensure_loaded()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list(self) -> list[Notification]:
        self._ensure_loaded()
        return list(self._items)

    def unread_count(self) -> int:
        self._ensure_loaded()
        return sum(1 for item in self._items if not item.read)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    def add(self, notification: Notification) -> Notification:
        self._ensure_loaded()
        if not notification.id:
            return notification
        if any(item.id == notification.id for item in self._items):
            return notification
        self._items.insert(0, notification)
        del self._items[self.max_items :]
        self._save()
        return notification

    def mark_read(self, notification_id: str) -> bool:
        self._ensure_loaded()
        changed = False
        updated: list[Notification] = []
        for item in self._items:
            if item.id == notification_id and not item.read:
                updated.append(item.with_read(True))
                changed = True
            else:
                updated.append(item)
        if changed:
            self._items = updated
            self._save()
        return changed

    def mark_all_read(self) -> None:
        self._ensure_loaded()
        if not any(not item.read for item in self._items):
            return
        self._items = [item.with_read(True) for item in self._items]
        self._save()

    def refresh_from_audit(self) -> list[Notification]:
        """Create notifications for new failed VCS operations."""
        self._ensure_loaded()
        events = self.audit.read_recent(200)
        if not self._baseline_done:
            self._seen.update(self._fingerprint(event) for event in events)
            self._baseline_done = True
            self._save()
            return []

        new_notifications: list[Notification] = []
        for event in events:
            fingerprint = self._fingerprint(event)
            if fingerprint in self._seen:
                continue
            self._seen.add(fingerprint)
            if bool(event.get("ok", True)):
                continue
            if not self._is_visible_to_current_role(event):
                continue
            new_notifications.append(self._from_audit_event(event, fingerprint))

        for notification in reversed(new_notifications):
            if any(item.id == notification.id for item in self._items):
                continue
            self._items.insert(0, notification)
        if new_notifications:
            del self._items[self.max_items :]
            self._save()
        return new_notifications

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        current_user = str(self._user_id_provider() or "default")
        if current_user != self._user_id:
            self._user_id = current_user
            self._load()

    def _state_path(self) -> Path:
        safe_user = "".join(
            character if character.isalnum() or character in ("-", "_") else "_"
            for character in self._user_id
        ) or "default"
        return self._state_dir / f"notifications_{safe_user}.json"

    def _load(self) -> None:
        data = load_json(self._state_path())
        items = data.get("items") or []
        self._items = [
            Notification.from_dict(item)
            for item in items
            if isinstance(item, dict)
        ][: self.max_items]
        seen = data.get("seen") or []
        self._seen = {str(value) for value in seen if str(value)}
        self._baseline_done = bool(data.get("baseline_done", False))

    def _save(self) -> None:
        try:
            save_json_atomic(
                self._state_path(),
                {
                    "items": [item.to_dict() for item in self._items],
                    "seen": list(self._seen)[-500:],
                    "baseline_done": self._baseline_done,
                },
            )
        except OSError:
            # Notifications are best effort and must never break the UI.
            pass

    # ------------------------------------------------------------------
    # Audit mapping
    # ------------------------------------------------------------------
    def _is_visible_to_current_role(self, event: dict) -> bool:
        role = str(self._role_provider() or "").strip().lower()
        if role == "td":
            return True
        operation = str(event.get("operation", "") or "")
        return not operation.startswith("repository.") and operation != "locks.break"

    @staticmethod
    def _fingerprint(event: dict) -> str:
        values = (
            event.get("timestamp", ""),
            event.get("operation", ""),
            event.get("project", ""),
            event.get("error_code", ""),
            event.get("returncode", ""),
            str(event.get("message", ""))[:120],
        )
        return "|".join(str(value) for value in values)

    @staticmethod
    def _from_audit_event(event: dict, fingerprint: str) -> Notification:
        operation = str(event.get("operation", "") or "VCS operation")
        title = operation.replace(".", " ").replace("_", " ").title() + " failed"
        message = str(event.get("message", "") or "See VCS Audit for details.")
        paths = event.get("paths") or []
        if isinstance(paths, str):
            paths = [paths]
        timestamp = str(event.get("timestamp", "")) or datetime.now(timezone.utc).isoformat()
        return Notification(
            id=fingerprint,
            kind="vcs",
            severity="error",
            title=title,
            message=message,
            timestamp=timestamp,
            project=str(event.get("project", "") or ""),
            paths=Notification.dedupe_paths(paths),
            target=f"project:{event.get('project', '')}" if event.get("project") else "",
        )
