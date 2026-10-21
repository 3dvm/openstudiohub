"""Unit tests for the VCS publish checklist dialog."""

from types import SimpleNamespace

from PySide6.QtCore import QObject, Qt, Signal

from src.interfaces.qt.views.vcs_publish_dialog import VcsPublishDialog


class FakeFileChange:
    def __init__(
        self,
        relative_path: str,
        status: str = "M",
        conflict: bool = False,
    ) -> None:
        self.relative_path = relative_path
        self.status = status
        self.conflict = conflict

    @property
    def is_unversioned(self) -> bool:
        return self.status == "?"

    @property
    def is_conflicted(self) -> bool:
        return self.conflict or self.status == "C"


class FakeViewModel(QObject):
    vcs_publish_finished = Signal(str, bool, str)
    vcs_conflict_resolved = Signal(str, bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.calls = []
        self.resolve_calls = []

    def completed_checklist_items(self, _task_id):
        return ["Model approved"]

    def publish_vcs_changes(self, card, selected, message="") -> bool:
        self.calls.append((card, list(selected), message))
        return True

    def resolve_vcs_conflict(self, card, change, strategy) -> bool:
        self.resolve_calls.append((card, change, strategy))
        return True


def _card():
    return SimpleNamespace(
        task_data={"id": "t1"},
        project_name="Neon",
        task_file_path="pro/a.blend",
    )


def _dialog(changes):
    return VcsPublishDialog(None, FakeViewModel(), _card(), changes, task_label="Neon")


def test_only_versioned_changes_are_checked_by_default(qapp):
    changes = [FakeFileChange("pro/a.blend"), FakeFileChange("pro/tex/new.png", "?")]
    dialog = _dialog(changes)

    assert dialog.selected_changes() == [changes[0]]
    assert dialog.list_widget.count() == 1
    assert dialog.untracked_list.count() == 1
    assert dialog.untracked_list.item(0).checkState() == Qt.Unchecked
    dialog.deleteLater()


def test_selecting_untracked_file_includes_it(qapp):
    changes = [FakeFileChange("pro/a.blend"), FakeFileChange("pro/tex/new.png", "?")]
    dialog = _dialog(changes)
    dialog.untracked_list.item(0).setCheckState(Qt.Checked)

    assert dialog.selected_changes() == changes
    dialog.deleteLater()


def test_hiding_untracked_files_excludes_them(qapp):
    changes = [FakeFileChange("pro/a.blend"), FakeFileChange("pro/tex/new.png", "?")]
    dialog = _dialog(changes)
    dialog.untracked_list.item(0).setCheckState(Qt.Checked)

    dialog.chk_show_untracked.setChecked(False)

    assert dialog.selected_changes() == [changes[0]]
    assert dialog.untracked_list.item(0).checkState() == Qt.Unchecked
    dialog.deleteLater()


def test_checklist_items_are_included_in_the_default_message(qapp):
    changes = [FakeFileChange("pro/a.blend")]
    dialog = _dialog(changes)

    assert "Completed checklist" in dialog.commit_message()
    assert "- [x] Model approved" in dialog.commit_message()
    dialog.deleteLater()


def test_publish_forwards_selected_changes_and_edited_message(qapp):
    changes = [FakeFileChange("pro/a.blend")]
    dialog = _dialog(changes)
    dialog.entry_message.setPlainText("Custom message")

    dialog._publish()

    assert dialog.vm.calls == [(dialog.card, changes, "Custom message")]
    dialog.deleteLater()


def test_conflicts_are_separated_and_excluded_from_publish(qapp):
    changes = [
        FakeFileChange("pro/a.blend"),
        FakeFileChange("pro/b.blend", "C", conflict=True),
    ]
    dialog = _dialog(changes)

    assert dialog.selected_changes() == [changes[0]]
    assert dialog.conflict_list.count() == 1
    assert dialog.btn_resolve_conflict.isHidden() is False
    dialog.deleteLater()


def test_conflict_resolution_signal_closes_the_dialog(qapp):
    changes = [FakeFileChange("pro/b.blend", "C", conflict=True)]
    dialog = _dialog(changes)

    dialog._on_conflict_resolved("t1", True, "Conflict resolved.")

    assert dialog.result() == 1  # QDialog.Accepted
    dialog.deleteLater()
