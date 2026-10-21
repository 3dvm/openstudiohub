# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/notifications_viewmodel.py
# Architectural role: MVVM ViewModel / in-app notifications
# =========================================================================================

"""ViewModel for the top-bar notification center."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal

from src.application.services.notification_service import NotificationService
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink


class NotificationsViewModel(BaseViewModel):
    notifications_changed = Signal(list)
    unread_count_changed = Signal(int)

    def __init__(
        self,
        service: NotificationService,
        status_sink: StatusSink | None = None,
        parent=None,
        *,
        auto_refresh: bool = True,
        refresh_interval_ms: int = 20000,
    ) -> None:
        super().__init__(status_sink, parent)
        self.service = service
        self._timer = QTimer(self)
        self._timer.setInterval(max(1000, int(refresh_interval_ms)))
        self._timer.timeout.connect(self.refresh)
        if auto_refresh:
            self._timer.start()

    def list(self) -> list:
        return self.service.list()

    def unread_count(self) -> int:
        return self.service.unread_count()

    def refresh(self) -> None:
        self.service.refresh_from_audit()
        self._emit()

    def mark_read(self, notification_id: str) -> None:
        if self.service.mark_read(notification_id):
            self._emit()

    def mark_all_read(self) -> None:
        self.service.mark_all_read()
        self._emit()

    def _emit(self) -> None:
        items = self.service.list()
        self.notifications_changed.emit(items)
        self.unread_count_changed.emit(self.service.unread_count())

    def stop(self) -> None:
        self._timer.stop()
