# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/vcs_audit_viewmodel.py
# Architectural role: MVVM ViewModel / TD VCS audit viewer
# =========================================================================================

"""Read-only ViewModel for the TD VCS audit trail."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal

from src.infrastructure.vcs.vcs_audit import VcsAuditLogger
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink


class VcsAuditViewModel(BaseViewModel):
    events_loaded = Signal(list)  # list[dict], newest first

    def __init__(
        self,
        audit_logger: Optional[VcsAuditLogger] = None,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.audit = audit_logger or VcsAuditLogger()

    @property
    def audit_path(self) -> Path:
        return self.audit.path

    def load(
        self,
        limit: int = 500,
        search: str = "",
        only_failures: bool = False,
    ) -> list[dict]:
        """Load and filter recent audit events (newest first)."""
        events = self.audit.read_recent(limit)
        needle = (search or "").strip().lower()
        if needle:
            events = [event for event in events if needle in self._search_text(event)]
        if only_failures:
            events = [event for event in events if not bool(event.get("ok", True))]
        events.reverse()
        self.events_loaded.emit(events)
        return events

    @staticmethod
    def _search_text(event: dict) -> str:
        paths = " ".join(str(path) for path in event.get("paths", []) or [])
        return " ".join(
            (
                str(event.get("operation", "")),
                str(event.get("project", "")),
                str(event.get("server", "")),
                str(event.get("user", "")),
                paths,
                str(event.get("message", "")),
            )
        ).lower()
