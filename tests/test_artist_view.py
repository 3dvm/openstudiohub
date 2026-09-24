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


class FakeViewModel(QObject):
    tasks_loaded = Signal(list)
    tasks_load_started = Signal()
    tasks_load_finished = Signal(bool)
    vcs_changes_ready = Signal(str, list)
    vcs_publish_finished = Signal(str, bool, str)

    def __init__(self):
        super().__init__()
        self.load_calls = 0

    def load_tasks(self):
        self.load_calls += 1

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

    def publish_vcs_changes(self, _card, _changes):
        return True


def _card(project_id: str, project_name: str) -> ArtistTaskCardModel:
    return ArtistTaskCardModel(
        task_data={"id": f"t-{project_id}", "entity_name": "Monkey", "task_type_name": "Modeling"},
        project_root=Path("/tmp/does-not-exist"),
        config_path=None,
        is_installed=False,
        can_work=True,
        blocked_reason="",
        project_id=project_id,
        project_name=project_name,
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
