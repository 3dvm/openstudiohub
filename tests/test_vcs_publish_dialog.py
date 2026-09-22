"""Unit tests for the VCS publish checklist dialog."""

from types import SimpleNamespace

from PySide6.QtCore import QObject, Qt, Signal

from src.interfaces.qt.views.vcs_publish_dialog import VcsPublishDialog


class FakeFileChange:
    def __init__(self, relative_path: str, status: str = "M") -> None:
        self.relative_path = relative_path
        self.status = status

    @property
    def is_unversioned(self) -> bool:
        return self.status == "?"


class FakeViewModel(QObject):
    vcs_publish_finished = Signal(str, bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.calls = []

    def publish_vcs_changes(self, card, selected) -> bool:
        self.calls.append((card, list(selected)))
        return True


def _card():
    return SimpleNamespace(task_data={"id": "t1"}, project_name="Neon")


def _dialog(changes):
    return VcsPublishDialog(None, FakeViewModel(), _card(), changes, task_label="Neon")


def test_all_changes_are_checked_by_default(qapp):
    changes = [FakeFileChange("pro/a.blend"), FakeFileChange("pro/tex/new.png", "?")]
    dialog = _dialog(changes)

    assert dialog.selected_changes() == changes
    dialog.deleteLater()


def test_unchecked_items_are_excluded(qapp):
    changes = [FakeFileChange("pro/a.blend"), FakeFileChange("pro/tex/new.png", "?")]
    dialog = _dialog(changes)
    dialog.list_widget.item(1).setCheckState(Qt.Unchecked)

    assert dialog.selected_changes() == [changes[0]]
    dialog.deleteLater()


def test_publish_forwards_selected_changes(qapp):
    changes = [FakeFileChange("pro/a.blend")]
    dialog = _dialog(changes)

    dialog._publish()

    assert dialog.vm.calls == [(dialog.card, changes)]
    dialog.deleteLater()
