"""Unit tests for the task-card status badge and VCS lock badge."""

from src.interfaces.qt.components.task_card import TaskCard, resolve_task_status


def _card(qapp, task_data: dict | None = None) -> TaskCard:
    # No ``entity_id`` keeps the thumbnail worker from hitting the network.
    return TaskCard(
        parent=None,
        task_data=task_data
        or {"id": "t1", "entity_name": "Monkey", "task_type_name": "Modeling"},
        project_root="/tmp/does-not-exist",
        is_installed=True,
        can_work=True,
        blocked_reason="",
        token="",
        host="",
        on_launch_callback=lambda: None,
        on_install_callback=lambda: None,
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

