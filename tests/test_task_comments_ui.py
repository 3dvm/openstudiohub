"""Unit tests for the task comment badge and project task actions."""

from src.interfaces.qt.components.project_card import ProjectCard
from src.interfaces.qt.components.task_card import TaskCard


def _task_card(qapp, on_comments=None):
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
        comment_count=3,
        unread_count=2,
        on_comments_callback=on_comments,
    )


def _project_card(qapp, on_open_tasks, tasks_only=True):
    return ProjectCard(
        parent=None,
        project_data={"id": "p1", "name": "Neon"},
        user_role="artist" if tasks_only else "td",
        status={
            "project_dir": None,
            "is_installed": False,
            "badge_text": "4 task(s)",
            "sync_text": "🗂️ 4 task(s)",
        },
        token="",
        host="",
        thumbnail_fetcher=lambda *args: None,
        on_install=lambda *args: None,
        on_launch=lambda *args: None,
        on_delete=lambda *args: None,
        on_open_kitsu=lambda *args: None,
        on_watchtower=lambda *args: None,
        on_open_tasks=on_open_tasks,
        tasks_only=tasks_only,
    )


def test_comment_badge_shows_count_and_unread_highlight(qapp):
    card = _task_card(qapp)

    assert card.comment_badge.text() == "3"
    assert "#F97316" in card.comment_badge.styleSheet()

    card.set_comment_counts(5, 0)

    assert card.comment_badge.text() == "5"
    assert "#F97316" not in card.comment_badge.styleSheet()


def test_comment_badge_click_invokes_callback(qapp):
    calls = []
    card = _task_card(qapp, on_comments=lambda: calls.append(True))

    card.comment_badge.click()

    assert calls == [True]


def test_artist_project_card_opens_tasks(qapp):
    calls = []
    card = _project_card(qapp, lambda pid: calls.append(pid), tasks_only=True)

    assert card.btn_primary_action.text() == "Open Tasks"
    assert card.btn_primary_action.isEnabled() is True
    card.btn_primary_action.click()

    assert calls == ["p1"]


def test_td_project_card_exposes_view_tasks_action(qapp):
    calls = []
    card = _project_card(qapp, lambda pid: calls.append(pid), tasks_only=False)

    actions = [action.text() for action in card.options_menu.actions()]
    assert any("View Tasks" in text for text in actions)

    next(a for a in card.options_menu.actions() if "View Tasks" in a.text()).trigger()
    assert calls == ["p1"]
