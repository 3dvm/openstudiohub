"""Unit tests for the VCS history dialog."""

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog

from src.interfaces.qt.views.vcs_history_dialog import VcsHistoryDialog


class FakeViewModel(QObject):
    vcs_history_ready = Signal(str, list)
    vcs_history_failed = Signal(str, str)
    vcs_diff_ready = Signal(str, str, str)
    vcs_export_finished = Signal(str, bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.history_requests = []
        self.diff_requests = []
        self.export_requests = []

    def request_vcs_history(self, card):
        self.history_requests.append(card)
        return True

    def request_vcs_diff(self, card, revision):
        self.diff_requests.append((card, revision))
        return True

    def export_vcs_revision(self, card, revision, destination):
        self.export_requests.append((card, revision, destination))
        return True


def _card():
    return SimpleNamespace(
        task_data={"id": "t1"},
        task_file_path="pro/a.blend",
        project_name="Neon",
    )


def _dialog(qapp):
    vm = FakeViewModel()
    dialog = VcsHistoryDialog(None, vm, _card(), task_label="Neon")
    return dialog, vm


def test_history_is_requested_and_rendered(qapp):
    dialog, vm = _dialog(qapp)
    assert vm.history_requests

    dialog._on_history_ready(
        "t1",
        [
            {"revision": "7", "author": "ana", "date": "2026-01-01", "message": "Update"},
            {"revision": "5", "author": "bo", "date": "2026-01-01", "message": "Initial"},
        ],
    )

    assert dialog.revision_list.count() == 2
    assert dialog.revision_list.currentItem() is not None
    assert "r7" in dialog.revision_list.item(0).text()
    dialog.deleteLater()


def test_diff_is_rendered_for_selected_revision(qapp):
    dialog, vm = _dialog(qapp)
    dialog._on_history_ready(
        "t1", [{"revision": "7", "author": "ana", "date": "", "message": "Update"}]
    )

    dialog._show_diff()
    assert vm.diff_requests == [(dialog.card, 7)]

    dialog._on_diff_ready("t1", "7", "--- a\n+++ b")
    assert "--- a" in dialog.diff_view.toPlainText()
    dialog.deleteLater()


def test_export_uses_selected_revision(qapp, monkeypatch, tmp_path):
    dialog, vm = _dialog(qapp)
    dialog._on_history_ready(
        "t1", [{"revision": "7", "author": "ana", "date": "", "message": "Update"}]
    )
    destination = tmp_path / "exported.blend"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), ""),
    )

    dialog._export_revision()

    assert vm.export_requests == [(dialog.card, 7, destination)]
    dialog._on_export_finished("t1", True, "Revision 7 exported.")
    assert "exported" in dialog.lbl_status.text().lower()
    dialog.deleteLater()


def test_other_task_signals_are_ignored(qapp):
    dialog, _vm = _dialog(qapp)
    dialog._on_history_ready(
        "t1", [{"revision": "7", "author": "ana", "date": "", "message": "Update"}]
    )

    dialog._on_history_ready(
        "other", [{"revision": "1", "author": "x", "date": "", "message": "Other"}]
    )

    assert dialog.revision_list.count() == 1
    dialog.deleteLater()
