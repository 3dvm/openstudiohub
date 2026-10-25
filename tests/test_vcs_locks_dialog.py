"""Unit tests for the TD VCS lock administration dialog."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from src.interfaces.qt.views.vcs_locks_dialog import VcsLocksDialog


class FakeViewModel(QObject):
    vcs_lock_broken = Signal(str, str, bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.break_requests = []

    def break_vcs_lock(self, project_name, path):
        self.break_requests.append((project_name, path))
        return True


def _locks():
    return [
        {"path": "/svn/pro/a.blend", "owner": "ana", "comment": "editing"},
        {"path": "/svn/pro/b.blend", "owner": "bo"},
    ]


def test_locks_are_rendered(qapp):
    dialog = VcsLocksDialog(None, FakeViewModel(), "Neon", _locks())

    assert dialog.lock_list.count() == 2
    assert "ana" in dialog.lock_list.item(0).text()
    dialog.deleteLater()


def test_break_lock_confirms_and_requests_removal(qapp, monkeypatch):
    vm = FakeViewModel()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    dialog = VcsLocksDialog(None, vm, "Neon", _locks())

    dialog._break_lock()

    assert vm.break_requests == [("Neon", "/svn/pro/a.blend")]
    dialog.deleteLater()


def test_successful_break_removes_the_row(qapp):
    dialog = VcsLocksDialog(None, FakeViewModel(), "Neon", _locks())

    dialog._on_lock_broken("Neon", "/svn/pro/a.blend", True, "Lock removed.")

    assert dialog.lock_list.count() == 1
    assert "bo" in dialog.lock_list.item(0).text()
    dialog.deleteLater()


def test_other_project_break_is_ignored(qapp):
    dialog = VcsLocksDialog(None, FakeViewModel(), "Neon", _locks())

    dialog._on_lock_broken("Other", "/svn/pro/a.blend", True, "Lock removed.")

    assert dialog.lock_list.count() == 2
    dialog.deleteLater()
