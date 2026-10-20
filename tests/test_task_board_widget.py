"""Unit tests for the PM/TD task-board widget (table/cards/comments)."""

from PySide6.QtCore import QObject, Signal

# Import the views package first: the widgets package has an eager import cycle.
import src.interfaces.qt.views  # noqa: F401
from src.interfaces.qt.widgets.task_board_widget import TaskBoardWidget


class FakeWorkers:
    def is_running(self, _key):
        return True

    def start(self, _key, _worker, **_kwargs):
        return True


class FakeComments(QObject):
    comments_loaded = Signal(str, list)
    comments_failed = Signal(str)
    comment_posted = Signal(str, bool, str)
    checklist_updating = Signal(bool)
    seen_updated = Signal(str)

    def __init__(self):
        super().__init__()
        self.loaded = []

    def load(self, task, **_kwargs):
        self.loaded.append(str(task.get("id", "")))
        self.comments_loaded.emit(str(task.get("id", "")), [{"id": "c1", "text": "hi"}])

    def post(self, *_args, **_kwargs):
        self.comment_posted.emit("t1", True, "ok")

    def mark_seen(self, *_args, **_kwargs):
        pass

    def toggle_checklist(self, *_args, **_kwargs):
        pass


class FakeVM(QObject):
    projects_loaded = Signal(list)
    tasks_loaded = Signal(str, list)
    comment_counts_ready = Signal(dict)
    assignment_finished = Signal(str, bool, str)
    view_mode_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.comments = FakeComments()
        self.workers = FakeWorkers()
        self.view_mode = "table"
        self.current_project_id = ""
        self.persons = [{"id": "u1", "full_name": "Ada"}]
        self.tasks = []
        self.applied = []

    def load_projects(self):
        pass

    def select_project(self, project_id):
        self.current_project_id = project_id

    def load_tasks(self, _project_id=""):
        pass

    def set_view_mode(self, mode):
        self.view_mode = mode
        self.view_mode_changed.emit(mode)

    def assignment_allowed(self):
        return True

    def apply_assignees(self, task, add_ids, remove_ids):
        self.applied.append((str(task.get("id")), list(add_ids), list(remove_ids)))

    @property
    def token(self):
        return ""

    @property
    def host(self):
        return ""


def _tasks():
    return [
        {
            "id": "t1",
            "entity_id": "e1",
            "entity_name": "Monkey",
            "task_type_name": "Modeling",
            "task_status": {"name": "In Progress", "color": "#3B82F6"},
            "assignees": [{"id": "u1", "full_name": "Ada"}],
            "_comment_count": 2,
            "_unread_count": 1,
            "_checklist_done": 1,
            "_checklist_total": 2,
        },
        {
            "id": "t2",
            "entity_id": "e2",
            "entity_name": "Tree",
            "task_type_name": "Rigging",
            "task_status": {"name": "Todo", "color": "#64748B"},
            "assignees": [],
            "_comment_count": 0,
            "_unread_count": 0,
        },
    ]


def _board(qapp):
    vm = FakeVM()
    widget = TaskBoardWidget(None, vm)
    tasks = _tasks()
    vm.tasks = tasks
    vm.projects_loaded.emit([{"id": "p1", "name": "Neon"}])
    vm.tasks_loaded.emit("p1", tasks)
    vm.comment_counts_ready.emit(
        {
            "t1": {
                "total": 2,
                "unread": 1,
                "checklist_done": 1,
                "checklist_total": 2,
            },
            "t2": {
                "total": 0,
                "unread": 0,
                "checklist_done": 0,
                "checklist_total": 0,
            },
        }
    )
    return widget, vm


def test_table_renders_all_tasks(qapp):
    widget, _vm = _board(qapp)

    assert widget.table.rowCount() == 2
    assert "#F97316" in widget._comment_buttons["t1"].styleSheet()
    assert "1/2" in widget._checklist_labels["t1"].text()


def test_view_toggle_switches_to_cards(qapp):
    widget, vm = _board(qapp)

    vm.set_view_mode("cards")

    assert widget.stack.currentIndex() == 1
    assert set(widget._card_widgets) == {"t1", "t2"}
    assert "1/2" in widget._card_widgets["t1"].lbl_checklist.text()


def test_comment_button_opens_drawer(qapp):
    widget, vm = _board(qapp)

    widget._comment_buttons["t1"].click()

    assert vm.comments.loaded == ["t1"]
