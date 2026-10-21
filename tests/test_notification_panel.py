"""Unit tests for the notification popover."""

from src.domain.notifications import Notification
from src.interfaces.qt.components.notification_panel import NotificationPanel


def test_panel_shows_empty_state(qapp):
    panel = NotificationPanel(None)

    panel.set_notifications([])

    assert panel.lbl_empty.isHidden() is False
    assert panel.scroll.isHidden() is True
    panel.deleteLater()


def test_panel_renders_items(qapp):
    panel = NotificationPanel(None)
    notifications = [
        Notification(
            id="1",
            kind="vcs",
            severity="error",
            title="Commit failed",
            message="Out of date",
            timestamp="2026-01-01T10:00:00+00:00",
        )
    ]

    panel.set_notifications(notifications)

    assert panel.lbl_empty.isHidden() is True
    assert panel.list_layout.count() == 2  # item + stretch
    panel.deleteLater()
