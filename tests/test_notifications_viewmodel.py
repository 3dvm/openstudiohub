"""Unit tests for the notification ViewModel."""

from src.application.services.notification_service import NotificationService
from src.infrastructure.vcs.vcs_audit import VcsAuditLogger
from src.interfaces.qt.viewmodels.notifications_viewmodel import NotificationsViewModel


def _vm(tmp_path):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")
    service = NotificationService(
        audit_logger=logger,
        user_id_provider=lambda: "artist-1",
        state_dir=tmp_path,
    )
    vm = NotificationsViewModel(service, auto_refresh=False)
    return vm, logger


def test_refresh_emits_notifications_and_unread_count(tmp_path, qapp):
    vm, logger = _vm(tmp_path)
    vm.refresh()
    logger.log("commit", project="Neon", ok=False, error_code="E160028", message="stale")
    counts = []
    items = []
    vm.unread_count_changed.connect(counts.append)
    vm.notifications_changed.connect(lambda values: items.append(list(values)))

    vm.refresh()

    assert counts[-1] == 1
    assert len(items[-1]) == 1


def test_mark_read_updates_count(tmp_path, qapp):
    vm, logger = _vm(tmp_path)
    vm.refresh()
    logger.log("commit", project="Neon", ok=False, error_code="E160028", message="stale")
    vm.refresh()
    notification = vm.list()[0]

    vm.mark_read(notification.id)

    assert vm.unread_count() == 0
