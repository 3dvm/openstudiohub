"""Unit tests for the batch builder task cells and spawn gating."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPushButton

# Import the views package first: the widgets package has an eager circular
# import that only resolves when views is loaded beforehand.
import src.interfaces.qt.views  # noqa: F401
from src.interfaces.qt.widgets.blend_builder_widget import BlendBuilderWidget


class FakeViewModel(QObject):
    projects_loaded = Signal(list)
    editorial_status_loaded = Signal(dict)
    assets_loaded = Signal(list)
    shots_loaded = Signal(list, list)
    sequences_loaded = Signal(list)
    install_progress = Signal(str, str)
    install_finished = Signal(bool, str)
    spawn_progress = Signal(int, str)
    spawn_log = Signal(str)
    spawn_finished = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.spawned = []
        self.current_project_id = "p1"
        self.current_project_name = "MIDEQ_promo"

    def load_projects(self):
        pass

    def select_project(self, _name):
        pass

    def spawn_batch(self, entities, task_types):
        self.spawned.append((entities, task_types))


def _asset(name, tasks):
    return {
        "id": name,
        "name": name,
        "type": "Character",
        "asset_type_id": "type-1",
        "asset_type_name": "Character",
        "has_file": False,
        "tasks": tasks,
    }


def _shot(name, tasks):
    return {
        "id": name,
        "name": name,
        "type": "Shot",
        "parent": "SQ010",
        "has_file": False,
        "tasks": tasks,
    }


def _task(filepath=""):
    return {"has_file": bool(filepath), "filepath": filepath, "raw_task": {}}


def test_render_assets_builds_task_cells_and_checkboxes(qapp):
    vm = FakeViewModel()
    widget = BlendBuilderWidget(None, vm)

    widget._render_assets([_asset("hero", {"Modeling": _task()})])

    assert set(widget.task_checkboxes) == {"Modeling"}
    cell = widget.table.cellWidget(0, 3)
    assert cell is not None
    assert cell.findChild(QPushButton, "TaskLinkButton") is not None


def test_render_shots_replaces_asset_checkboxes(qapp):
    vm = FakeViewModel()
    widget = BlendBuilderWidget(None, vm)

    widget._render_assets([_asset("hero", {"Modeling": _task()})])
    widget._render_shots([_shot("sh010", {"Layout": _task()})], ["Layout"])

    assert set(widget.task_checkboxes) == {"Layout"}


def test_batch_assets_without_tasks_is_blocked(qapp, monkeypatch):
    vm = FakeViewModel()
    widget = BlendBuilderWidget(None, vm)
    widget._render_assets([_asset("hero", {})])

    prompts = []
    monkeypatch.setattr(widget, "_prompt_missing_tasks", lambda names: prompts.append(names))

    widget._trigger_batch_creation(3)

    assert prompts == [["hero"]]
    assert vm.spawned == []


def test_asset_selection_is_forwarded(qapp):
    vm = FakeViewModel()
    widget = BlendBuilderWidget(None, vm)
    widget._render_assets(
        [_asset("hero", {"Modeling": _task(), "Rigging": _task()})]
    )
    widget.task_checkboxes["Rigging"].setChecked(False)

    widget._trigger_batch_creation(3)

    assert vm.spawned
    _entities, task_types = vm.spawned[0]
    assert task_types == ["Modeling"]
    widget.progress_modal.accept()
