"""Unit tests for the in-app notification service."""

from src.application.services.notification_service import NotificationService
from src.domain.notifications import Notification
from src.infrastructure.vcs.vcs_audit import VcsAuditLogger


def _service(tmp_path, user="artist-1"):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")
    service = NotificationService(
        audit_logger=logger,
        user_id_provider=lambda: user,
        state_dir=tmp_path,
    )
    return service, logger


def test_first_refresh_baselines_existing_audit_events(tmp_path):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")
    logger.log("commit", project="Neon", ok=False, error_code="E160028")
    service = NotificationService(
        audit_logger=logger,
        user_id_provider=lambda: "artist-1",
        state_dir=tmp_path,
    )

    assert service.refresh_from_audit() == []
    assert service.unread_count() == 0


def test_new_failures_become_unread_notifications(tmp_path):
    service, logger = _service(tmp_path)
    service.refresh_from_audit()

    logger.log(
        "lock",
        project="Neon",
        ok=False,
        error_code="E160039",
        message="already locked",
        paths=["pro/a.blend"],
    )
    created = service.refresh_from_audit()

    assert len(created) == 1
    assert created[0].severity == "error"
    assert created[0].project == "Neon"
    assert created[0].paths == ("pro/a.blend",)
    assert service.unread_count() == 1


def test_events_are_deduplicated(tmp_path):
    service, logger = _service(tmp_path)
    service.refresh_from_audit()
    logger.log("commit", project="Neon", ok=False, error_code="E160028", message="stale")

    assert len(service.refresh_from_audit()) == 1
    assert len(service.refresh_from_audit()) == 0
    assert service.unread_count() == 1


def test_read_state_persists_per_user(tmp_path):
    service, logger = _service(tmp_path)
    service.refresh_from_audit()
    logger.log("commit", project="Neon", ok=False, error_code="E160028", message="stale")
    notification = service.refresh_from_audit()[0]

    assert service.mark_read(notification.id) is True

    restored = NotificationService(
        audit_logger=logger,
        user_id_provider=lambda: "artist-1",
        state_dir=tmp_path,
    )
    assert restored.unread_count() == 0
    assert restored.list()[0].read is True


def test_mark_all_read(tmp_path):
    service, logger = _service(tmp_path)
    service.refresh_from_audit()
    logger.log("one", project="A", ok=False, error_code="E1")
    logger.log("two", project="B", ok=False, error_code="E2")
    service.refresh_from_audit()

    service.mark_all_read()

    assert service.unread_count() == 0


def test_add_deduplicates_by_id(tmp_path):
    service, _logger = _service(tmp_path)
    notification = Notification(
        id="fixed-id",
        kind="system",
        severity="info",
        title="Title",
        message="Message",
        timestamp="2026-01-01T00:00:00+00:00",
    )

    service.add(notification)
    service.add(notification)

    assert len(service.list()) == 1


def test_administrative_failures_are_td_only(tmp_path):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")
    artist = NotificationService(
        audit_logger=logger,
        user_id_provider=lambda: "artist-1",
        role_provider=lambda: "artist",
        state_dir=tmp_path,
    )
    artist.refresh_from_audit()
    logger.log("repository.create", project="Neon", ok=False, error_code="E170001", message="denied")
    logger.log("commit", project="Neon", ok=False, error_code="E160028", message="stale")

    created = artist.refresh_from_audit()

    assert len(created) == 1
    assert created[0].title.startswith("Commit")

    td = NotificationService(
        audit_logger=logger,
        user_id_provider=lambda: "td-1",
        role_provider=lambda: "td",
        state_dir=tmp_path,
    )
    td.refresh_from_audit()
    assert td.unread_count() == 0


def test_td_sees_administrative_failures(tmp_path):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")
    service = NotificationService(
        audit_logger=logger,
        user_id_provider=lambda: "td-1",
        role_provider=lambda: "td",
        state_dir=tmp_path,
    )
    service.refresh_from_audit()
    logger.log("repository.create", project="Neon", ok=False, error_code="E170001", message="denied")

    created = service.refresh_from_audit()

    assert len(created) == 1
    assert "Repository Create" in created[0].title
