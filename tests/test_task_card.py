"""Unit tests for the task-card status badge, thumbnail and VCS lock badge."""

import struct
import zlib

from src.interfaces.qt.components.task_card import TaskCard, resolve_task_status


def _png_bytes() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


_PNG_1X1 = _png_bytes()


def _card(
    qapp,
    task_data: dict | None = None,
    thumbnail_bytes: bytes | None = None,
) -> TaskCard:
    return TaskCard(
        parent=None,
        task_data=task_data
        or {"id": "t1", "entity_name": "Monkey", "task_type_name": "Modeling"},
        project_root="/tmp/does-not-exist",
        is_installed=True,
        can_work=True,
        blocked_reason="",
        on_launch_callback=lambda: None,
        on_install_callback=lambda: None,
        thumbnail_bytes=thumbnail_bytes,
    )


def test_lock_badge_hidden_when_unlocked(qapp):
    card = _card(qapp)

    card.set_lock_state("", False)

    assert card.lock_badge.isHidden() is True


def test_lock_badge_shows_foreign_owner(qapp):
    card = _card(qapp)

    card.set_lock_state("ana@studio.com", False)

    assert card.lock_badge.isHidden() is False
    assert "ana@studio.com" in card.lock_badge.text()
    assert card.lock_badge.toolTip() == "Locked by ana@studio.com"
    assert "#EF4444" in card.lock_badge.styleSheet()


def test_lock_badge_shows_mine(qapp):
    card = _card(qapp)

    card.set_lock_state("me@studio.com", True)

    assert card.lock_badge.isHidden() is False
    assert "You" in card.lock_badge.text()
    assert card.lock_badge.toolTip() == "Locked by you"
    assert "#10B981" in card.lock_badge.styleSheet()


def test_resolve_task_status_prefers_nested_status(qapp):
    name, color = resolve_task_status(
        {"task_status_name": "Todo", "task_status": {"name": "Work In Progress", "color": "#F59E0B"}}
    )

    assert name == "Work In Progress"
    assert color == "#F59E0B"


def test_resolve_task_status_flat_fallback(qapp):
    name, color = resolve_task_status({"task_status_name": "Retake", "task_status_color": "#EF4444"})

    assert name == "Retake"
    assert color == "#EF4444"


def test_resolve_task_status_defaults(qapp):
    name, color = resolve_task_status({})

    assert name == "TODO"
    assert color == "#444444"


def test_status_badge_shows_nested_status(qapp):
    card = _card(
        qapp,
        {"id": "t1", "task_status": {"name": "Ready To Start", "color": "#3B82F6"}},
    )

    assert card.status_badge.text() == "READY TO START"
    assert "#3B82F6" in card.status_badge.styleSheet()



def test_task_card_does_not_spawn_a_thumbnail_worker(qapp):
    card = _card(qapp, {"id": "t1", "entity_id": "e1"})

    assert not hasattr(card, "worker")
    assert card.thumb_stack.currentIndex() == 0


def test_task_card_applies_prefetched_thumbnail(qapp):
    card = _card(qapp, {"id": "t1", "entity_id": "e1"}, thumbnail_bytes=_PNG_1X1)

    assert card.thumb_stack.currentIndex() == 1
    assert card.thumb_label.pixmap().isNull() is False
