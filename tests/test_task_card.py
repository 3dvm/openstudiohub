"""Unit tests for the task-card VCS lock badge."""

from src.interfaces.qt.components.task_card import TaskCard


def _card(qapp) -> TaskCard:
    # No ``entity_id`` keeps the thumbnail worker from hitting the network.
    return TaskCard(
        parent=None,
        task_data={"id": "t1", "entity_name": "Monkey", "task_type_name": "Modeling"},
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
