"""Unit tests for the PM/TD task-board ViewModel state."""

from types import SimpleNamespace

from src.infrastructure.comment_read_store import CommentReadStore
from src.infrastructure.ui_prefs_store import UiPrefsStore
from src.interfaces.qt.viewmodels.task_board_viewmodel import TaskBoardViewModel


class FakeUser:
    id = "me"


class FakeAuth:
    def __init__(self, role="manager"):
        self.current_user = FakeUser()
        self._role = role

    def current_role(self):
        return SimpleNamespace(value=self._role)

    def access_token(self):
        return "token"

    @property
    def host(self):
        return "https://kitsu.test/api"


class FakeProduction:
    def list_persons(self):
        return [{"id": "me", "full_name": "Me"}]


def _vm(tmp_path, role="manager"):
    return TaskBoardViewModel(
        FakeProduction(),
        FakeAuth(role),
        read_store=CommentReadStore(path=tmp_path / "seen.json"),
        prefs_store=UiPrefsStore(path=tmp_path / "prefs.json"),
    )


def test_assignment_is_limited_to_managers(qapp, tmp_path):
    assert _vm(tmp_path, "manager").assignment_allowed() is True
    assert _vm(tmp_path, "td").assignment_allowed() is False


def test_view_mode_is_persisted_per_user(qapp, tmp_path):
    prefs_path = tmp_path / "prefs.json"
    vm = TaskBoardViewModel(
        FakeProduction(),
        FakeAuth("manager"),
        read_store=CommentReadStore(path=tmp_path / "seen.json"),
        prefs_store=UiPrefsStore(path=prefs_path),
    )
    assert vm.view_mode == "table"

    vm.set_view_mode("cards")

    reloaded = TaskBoardViewModel(
        FakeProduction(),
        FakeAuth("manager"),
        read_store=CommentReadStore(path=tmp_path / "seen.json"),
        prefs_store=UiPrefsStore(path=prefs_path),
    )
    assert reloaded.view_mode == "cards"


def test_project_comments_compute_unread_and_baseline(qapp, tmp_path):
    store = CommentReadStore(path=tmp_path / "seen.json")
    store.set_last_seen("me", "t1", "2026-10-20T10:00:00+00:00")
    vm = TaskBoardViewModel(
        FakeProduction(),
        FakeAuth("manager"),
        read_store=store,
        prefs_store=UiPrefsStore(path=tmp_path / "prefs.json"),
    )
    vm._current_project_id = "p1"
    vm._tasks = [{"id": "t1"}, {"id": "t2"}]
    captured = {}
    vm.comment_counts_ready.connect(lambda counts: captured.update(counts))

    vm._on_project_comments(
        "p1",
        [
            {
                "id": "c1",
                "task_id": "t1",
                "person_id": "u2",
                "created_at": "2026-10-20T12:00:00Z",
            },
            {
                "id": "c2",
                "task_id": "t2",
                "person_id": "u2",
                "created_at": "2026-10-20T09:00:00Z",
            },
        ],
    )

    assert captured["t1"] == {"total": 1, "unread": 1}
    assert captured["t2"] == {"total": 1, "unread": 0}
    assert store.get_last_seen("me", "t2") == "2026-10-20T09:00:00+00:00"
