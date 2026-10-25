# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/notification_panel.py
# Architectural role: UI Component / notification popover (PySide6)
# =========================================================================================

"""Popup notification list anchored to the top-bar bell."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.notifications import Notification


class NotificationItem(QFrame):
    clicked = Signal(str)
    copy_requested = Signal(str)
    dismiss_requested = Signal(str)

    def __init__(self, parent, notification: Notification) -> None:
        super().__init__(parent)
        self.notification = notification
        self.setObjectName("NotificationItem")
        self.setProperty("severity", notification.severity)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel(notification.title)
        title.setObjectName("NotificationItemTitle")
        title.setWordWrap(True)
        header.addWidget(title, stretch=1)
        timestamp = QLabel(self._format_time(notification.timestamp))
        timestamp.setObjectName("NotificationItemTime")
        header.addWidget(timestamp, alignment=Qt.AlignTop)
        self.btn_copy = QPushButton(self.tr("Copy"))
        self.btn_copy.setObjectName("NotificationItemAction")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.setToolTip(self.tr("Copy notification"))
        self.btn_copy.clicked.connect(self._copy)
        header.addWidget(self.btn_copy, alignment=Qt.AlignTop)
        self.btn_dismiss = QPushButton("×")
        self.btn_dismiss.setObjectName("NotificationItemDismiss")
        self.btn_dismiss.setCursor(Qt.PointingHandCursor)
        self.btn_dismiss.setToolTip(self.tr("Dismiss notification"))
        self.btn_dismiss.clicked.connect(
            lambda: self.dismiss_requested.emit(self.notification.id)
        )
        header.addWidget(self.btn_dismiss, alignment=Qt.AlignTop)
        layout.addLayout(header)

        message = QLabel(notification.message)
        message.setObjectName("NotificationItemMessage")
        message.setWordWrap(True)
        layout.addWidget(message)

    def _copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.notification.clipboard_text())
        self.copy_requested.emit(self.notification.id)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit(self.notification.id)
        super().mousePressEvent(event)

    @staticmethod
    def _format_time(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%H:%M")
        except (ValueError, TypeError):
            return ""


class NotificationPanel(QFrame):
    mark_all_read = Signal()
    notification_clicked = Signal(str)
    dismiss_notification = Signal(str)
    clear_all = Signal()

    def __init__(self, parent) -> None:
        super().__init__(parent, Qt.Popup)
        self.setObjectName("NotificationPanel")
        self.setFixedWidth(380)
        self.setMaximumHeight(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(self.tr("Notifications"))
        title.setObjectName("NotificationTitle")
        header.addWidget(title)
        header.addStretch()
        self.btn_clear_all = QPushButton(self.tr("Clear all"))
        self.btn_clear_all.setObjectName("GhostButton")
        self.btn_clear_all.clicked.connect(self.clear_all.emit)
        header.addWidget(self.btn_clear_all)
        self.btn_mark_all = QPushButton(self.tr("Mark all read"))
        self.btn_mark_all.setObjectName("GhostButton")
        self.btn_mark_all.clicked.connect(self.mark_all_read.emit)
        header.addWidget(self.btn_mark_all)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("InvisibleScrollArea")
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_widget)
        layout.addWidget(self.scroll, stretch=1)

        self.lbl_empty = QLabel(self.tr("You are all caught up."))
        self.lbl_empty.setObjectName("MutedLabel")
        self.lbl_empty.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_empty)

    def set_notifications(self, notifications: list) -> None:
        self._clear()
        items = list(notifications or [])
        self.scroll.setVisible(bool(items))
        self.lbl_empty.setVisible(not items)
        self.btn_clear_all.setVisible(bool(items))
        self.btn_mark_all.setVisible(bool(items))
        for notification in items:
            item = NotificationItem(self.list_widget, notification)
            item.clicked.connect(self._on_item_clicked)
            item.dismiss_requested.connect(self.dismiss_notification.emit)
            self.list_layout.insertWidget(self.list_layout.count() - 1, item)

    def _on_item_clicked(self, notification_id: str) -> None:
        self.notification_clicked.emit(notification_id)
        self.hide()

    def _clear(self) -> None:
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
