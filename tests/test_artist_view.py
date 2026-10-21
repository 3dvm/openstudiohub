"""Unit tests for the artist dashboard task-list refresh button."""

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from src.interfaces.qt.viewmodels.artist_viewmodel import ArtistTaskCardModel
from src.interfaces.qt.views.artist_view import ViewArtist


class FakeRole:
    label = "Artist"


class FakeUser:
    first_name = "Ada"


class FakeAuth:
    def __init__(self):
        self.current_user = FakeUser()

    def access_token(self):
        return ""

    @property
    def host(self):
        return ""

    def current_role(self):
        return FakeRole()


class FakeConfig:
    def get_studio_name(self):
        return "Test Studio"


class FakeComments(QObject):
    comments_loaded = Signal(str, list)
    comments_failed = Signal(str)
    comment_posted = Signal(str, bool, str)
    checklist_updating = Signal(bool)
    seen_updated = Signal(str)

    def load(self, *_args, **_kwargs):
        pass

    def post(self, *_args, **_kwargs):
        pass

    def mark_seen(self, *_args, **_kwargs):
        pass

    def toggle_checklist(self, *_args, **_kwargs):
        pass


class FakeViewModel(QObject):
    tasks_loaded = Signal(list)
    projects_loaded = Signal(list)
    comment_counts_ready = Signal(dict)
    tasks_load_started = Signal()
    tasks_load_finished = Signal(bool)
    vcs_changes_ready = Signal(str, list)
    vcs_publish_finished = Signal(str, bool, str)
    vcs_update_finished = Signal(str, bool, str)
    vcs_update_review_required = Signal(str, object)
    task_locks_ready = Signal(dict)
    task_statuses_loaded = Signal(str, list)

    def __init__(self):
        super().__init__()
        self.load_calls = 0
        self.update_calls = []
        self.status_calls = []
        self._update_running = False
        self.comments = FakeComments()

    def thumbnail_fetcher(self, _project_id, _token, _host):
        return None

    def load_tasks(self):
        self.load_calls += 1

    def load_task_statuses(self, project_id):
        self.status_calls.append(project_id)

    def list_servers(self):
        return []

    def vcs_settings(self, _server_id):
        return "", False

    def has_ssh_passphrase(self, _server_id):
        return False

    def save_vcs_settings(self, *args):
        pass

    def launch(self, _card):
        pass

    def install(self, _card):
        pass

    def check_vcs_changes(self, _card):
        pass

    def publish_vcs_changes(self, _card, _changes, message=""):
        return True

    def can_break_foreign_locks(self):
        return False

    def completed_checklist_items(self, _task_id):
        return []

    def release_task_lock(self, _card):
        pass

    def break_task_lock(self, _card):
        pass

    def is_vcs_update_running(self):
        return self._update_running

    def update_vcs(self, project_id, project_root):
        self.update_calls.append((project_id, project_root))
        return True

    def move_vcs_path_aside(self, project_root, relative_path):
        return True, "Moved aside."

    def ignore_vcs_path(self, project_root, relative_path):
        return True, "Ignored."

    def comment_panel_width(self):
        return 360

    def set_comment_panel_width(self, width):
        self.comment_width = width


def _card(
    project_id: str,
    project_name: str,
    vcs_enabled: bool = False,
    status: str = "Todo",
) -> ArtistTaskCardModel:
    return ArtistTaskCardModel(
        task_data={
            "id": f"t-{project_id}",
            "entity_name": "Monkey",
            "task_type_name": "Modeling",
            "task_status": {"name": status, "color": "#444444"},
        },
        project_root=Path("/tmp/does-not-exist"),
        config_path=None,
        is_installed=False,
        can_work=True,
        blocked_reason="",
        project_id=project_id,
        project_name=project_name,
        vcs_enabled=vcs_enabled,
    )


def _view():
    vm = FakeViewModel()
    view = ViewArtist(None, vm, FakeAuth(), FakeConfig(), on_logout=None)
    vm.load_calls = 0  # ignore the initial load triggered by construction
    return view, vm


def test_refresh_button_triggers_load(qapp):
    view, vm = _view()

    view.btn_refresh.click()

    assert vm.load_calls == 1


def test_project_card_opens_project_tasks(qapp):
    view, vm = _view()
    vm.tasks_loaded.emit([_card("p1", "Neon")])
    vm.projects_loaded.emit(
        [{"id": "p1", "name": "Neon", "task_count": 1, "installed": False}]
    )

    assert len(view._project_widgets) == 1

    view._project_widgets[0].btn_primary_action.click()

    assert view.stacked_content.currentIndex() == 1
    assert view.combo_projects.currentData() == "p1"


def test_refresh_button_disabled_while_loading(qapp):
    view, vm = _view()

    vm.tasks_load_started.emit()
    assert view.btn_refresh.isEnabled() is False

    vm.tasks_load_finished.emit(True)
    assert view.btn_refresh.isEnabled() is True

    vm.tasks_load_started.emit()
    vm.tasks_load_finished.emit(False)
    assert view.btn_refresh.isEnabled() is True


def test_project_filter_preserved_across_refresh(qapp):
    view, _ = _view()
    cards = [_card("p1", "Alpha"), _card("p2", "Beta")]

    view._on_tasks_loaded(cards)
    view.combo_projects.setCurrentIndex(view.combo_projects.findData("p2"))
    assert view.combo_projects.currentData() == "p2"

    view._on_tasks_loaded(cards)

    assert view.combo_projects.currentData() == "p2"


def test_update_vcs_disabled_on_all_projects(qapp):
    view, _ = _view()
    view._on_tasks_loaded([_card("p1", "Alpha", vcs_enabled=True)])

    assert view.combo_projects.currentData() == "ALL"
    assert view.btn_update_vcs.isEnabled() is False


def test_update_vcs_enabled_for_selected_vcs_project(qapp):
    view, _ = _view()
    view._on_tasks_loaded(
        [_card("p1", "Alpha", vcs_enabled=True), _card("p2", "Beta", vcs_enabled=False)]
    )

    view.combo_projects.setCurrentIndex(view.combo_projects.findData("p1"))
    assert view.btn_update_vcs.isEnabled() is True

    view.combo_projects.setCurrentIndex(view.combo_projects.findData("p2"))
    assert view.btn_update_vcs.isEnabled() is False


def test_update_vcs_click_invokes_viewmodel(qapp):
    view, vm = _view()
    view._on_tasks_loaded([_card("p1", "Alpha", vcs_enabled=True)])
    view.combo_projects.setCurrentIndex(view.combo_projects.findData("p1"))

    view.btn_update_vcs.click()

    assert vm.update_calls == [("p1", Path("/tmp/does-not-exist"))]


def test_update_vcs_disabled_while_running(qapp):
    view, vm = _view()
    view._on_tasks_loaded([_card("p1", "Alpha", vcs_enabled=True)])
    view.combo_projects.setCurrentIndex(view.combo_projects.findData("p1"))

    vm._update_running = True
    view._sync_update_vcs_button()

    assert view.btn_update_vcs.isEnabled() is False


def test_tasks_loaded_requests_statuses_for_current_project(qapp):
    view, vm = _view()

    view._on_tasks_loaded([_card("p1", "Alpha")])

    assert vm.status_calls[-1] == "ALL"


def test_status_combo_populated_from_viewmodel(qapp):
    view, vm = _view()
    view._on_tasks_loaded([_card("p1", "Alpha")])

    vm.task_statuses_loaded.emit(
        "ALL",
        [{"id": "s1", "name": "Todo"}, {"id": "s2", "name": "Retake"}],
    )

    labels = [view.combo_status.itemText(i) for i in range(view.combo_status.count())]
    assert labels == ["All Statuses", "Todo", "Retake"]


def test_status_filter_narrows_grid(qapp):
    view, vm = _view()
    view._on_tasks_loaded(
        [_card("p1", "Alpha", status="Todo"), _card("p1", "Alpha", status="Retake")]
    )
    vm.task_statuses_loaded.emit(
        "ALL", [{"id": "s1", "name": "Todo"}, {"id": "s2", "name": "Retake"}]
    )

    view.combo_status.setCurrentIndex(view.combo_status.findData("Retake"))

    assert len(view._task_widgets) == 1


def test_status_filter_combines_with_project_filter(qapp):
    view, vm = _view()
    view._on_tasks_loaded(
        [
            _card("p1", "Alpha", status="Retake"),
            _card("p2", "Beta", status="Retake"),
            _card("p2", "Beta", status="Todo"),
        ]
    )
    vm.task_statuses_loaded.emit(
        "ALL", [{"id": "s1", "name": "Todo"}, {"id": "s2", "name": "Retake"}]
    )

    view.combo_projects.setCurrentIndex(view.combo_projects.findData("p2"))
    view.combo_status.setCurrentIndex(view.combo_status.findData("Retake"))

    assert len(view._task_widgets) == 1


def test_status_filter_preserved_across_refresh(qapp):
    view, vm = _view()
    cards = [_card("p1", "Alpha", status="Todo"), _card("p1", "Alpha", status="Retake")]
    view._on_tasks_loaded(cards)
    vm.task_statuses_loaded.emit(
        "ALL", [{"id": "s1", "name": "Todo"}, {"id": "s2", "name": "Retake"}]
    )
    view.combo_status.setCurrentIndex(view.combo_status.findData("Retake"))

    view._on_tasks_loaded(cards)
    vm.task_statuses_loaded.emit(
        "ALL", [{"id": "s1", "name": "Todo"}, {"id": "s2", "name": "Retake"}]
    )

    assert view.combo_status.currentData() == "Retake"


def test_checklist_enablement_follows_busy_signal(qapp):
    view, vm = _view()
    view.comment_panel.set_comments(
        [{"id": "c1", "_checklist": [{"text": "Check lighting", "checked": False}]}]
    )

    vm.comments.checklist_updating.emit(False)
    assert view.comment_panel._checklist_boxes[0].isEnabled() is True

    vm.comments.checklist_updating.emit(True)
    assert view.comment_panel._checklist_boxes[0].isEnabled() is False


def test_web_context_is_lazy_and_keeps_the_shell(qapp):
    view, _vm = _view()

    assert view.content_stack.count() == 2
    assert view.web_context is None


def test_comment_drawer_uses_splitter(qapp):
    view, vm = _view()
    view._on_tasks_loaded([_card("p1", "Neon")])

    view._task_widgets[0].comment_badge.click()

    assert view.comment_panel.isHidden() is False
    assert view.comment_splitter.count() == 2

    view.comment_panel.close_requested.emit()
    assert view.comment_panel.isHidden() is True

