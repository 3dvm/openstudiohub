"""Unit tests for the notification popover."""

from PySide6.QtGui import QGuiApplication

from src.domain.notifications import Notification
from src.interfaces.qt.components.notification_panel import NotificationPanel


def _notification():
    return Notification(
        id="1",
        kind="vcs",
        severity="error",
        title="Commit failed",
        message="Out of date",
        timestamp="2026-01-01T10:00:00+00:00",
        project="Neon",
        paths=("pro/a.blend",),
        error_code="E160028",
    )


def _item(panel):
    return panel.list_layout.itemAt(0).widget()


def test_panel_shows_empty_state(qapp):
    panel = NotificationPanel(None)

    panel.set_notifications([])

    assert panel.lbl_empty.isHidden() is False
    assert panel.scroll.isHidden() is True
    assert panel.btn_clear_all.isHidden() is True
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
    assert panel.btn_clear_all.isHidden() is False
    panel.deleteLater()


def test_item_copy_writes_to_clipboard(qapp):
    panel = NotificationPanel(None)
    panel.set_notifications([_notification()])
    copied = []
    _item(panel).copy_requested.connect(copied.append)
    QGuiApplication.clipboard().clear()

    _item(panel).btn_copy.click()

    text = QGuiApplication.clipboard().text()
    assert "Commit failed" in text
    assert "Error code: E160028" in text
    assert "- pro/a.blend" in text
    assert copied == ["1"]
    panel.deleteLater()


def test_item_dismiss_emits_notification_id(qapp):
    panel = NotificationPanel(None)
    panel.set_notifications([_notification()])
    dismissed = []
    panel.dismiss_notification.connect(dismissed.append)

    _item(panel).btn_dismiss.click()

    assert dismissed == ["1"]
    panel.deleteLater()


def test_clear_all_emits(qapp):
    panel = NotificationPanel(None)
    panel.set_notifications([_notification()])
    cleared = []
    panel.clear_all.connect(lambda: cleared.append(True))

    panel.btn_clear_all.click()

    assert cleared == [True]
    panel.deleteLater()

