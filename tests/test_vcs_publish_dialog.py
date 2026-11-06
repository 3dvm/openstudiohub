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
    task_checklist_ready = Signal(str, list)
    task_checklist_saving = Signal(str, bool)
    vcs_paths_handled = Signal(str, bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.calls = []
        self.resolve_calls = []
        self.restore_calls = []
        self.delete_calls = []
        self.checklist = [
            {"comment_id": "c1", "index": 0, "text": "Model approved", "checked": True},
            {"comment_id": "c1", "index": 1, "text": "Pending item", "checked": False},
        ]

    def completed_checklist_items(self, _task_id):
        return [item["text"] for item in self.checklist if item["checked"]]

    def task_checklist_items(self, _task_id):
        return [dict(item) for item in self.checklist]

    def refresh_task_checklist(self, _card):
        return True

    def set_task_checklist_item(self, _task_id, _comment_id, index, checked) -> bool:
        self.checklist[index]["checked"] = bool(checked)
        self.task_checklist_ready.emit("t1", self.task_checklist_items("t1"))
        return True

    def publish_vcs_changes(self, card, selected, message="") -> bool:
        self.calls.append((card, list(selected), message))
        return True

    def resolve_vcs_conflict(self, card, change, strategy) -> bool:
        self.resolve_calls.append((card, change, strategy))
        return True

    def restore_vcs_paths(self, card, changes) -> bool:
        self.restore_calls.append((card, list(changes)))
        return True

    def schedule_delete_vcs_paths(self, card, changes) -> bool:
        self.delete_calls.append((card, list(changes)))
        return True


def _card():
    return SimpleNamespace(
        task_data={"id": "t1"},
        project_name="Neon",
        task_file_path="pro/a.blend",
    )


def _dialog(changes, vm=None):
    return VcsPublishDialog(None, vm or FakeViewModel(), _card(), changes, task_label="Neon")


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
    assert "Pending item" not in dialog.commit_message()
    assert dialog.checklist_layout.count() == 2
    dialog.deleteLater()


def test_ticking_a_checklist_item_updates_the_message(qapp):
    vm = FakeViewModel()
    dialog = _dialog([FakeFileChange("pro/a.blend")], vm)

    dialog._checklist_boxes[("c1", 1)].setChecked(True)

    assert vm.checklist[1]["checked"] is True
    assert "Pending item" in dialog.commit_message()
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


def test_missing_files_are_unchecked_and_not_selected_by_default(qapp):
    changes = [
        FakeFileChange("pro/a.blend"),
        FakeFileChange("pro/old.blend", "!"),
    ]
    dialog = _dialog(changes)

    assert dialog.missing_list.count() == 1
    assert dialog.missing_list.item(0).checkState() == Qt.Unchecked
    assert dialog.selected_changes() == [changes[0]]
    dialog.deleteLater()


def test_select_all_missing_includes_them_for_publish(qapp):
    changes = [
        FakeFileChange("pro/a.blend"),
        FakeFileChange("pro/old.blend", "!"),
    ]
    dialog = _dialog(changes)

    dialog._select_all_missing()

    assert dialog.selected_missing_changes() == [changes[1]]
    assert dialog.selected_changes() == changes
    dialog.deleteLater()


def test_restore_missing_calls_the_viewmodel(qapp):
    vm = FakeViewModel()
    changes = [FakeFileChange("pro/old.blend", "!")]
    dialog = _dialog(changes, vm)
    dialog._select_all_missing()

    dialog._restore_missing()

    assert vm.restore_calls == [(dialog.card, [changes[0]])]
    vm.vcs_paths_handled.emit("t1", True, "Restored.")
    assert dialog.result() == 1  # QDialog.Accepted
    dialog.deleteLater()


def test_delete_missing_schedules_after_confirmation(qapp, monkeypatch):
    import src.interfaces.qt.views.vcs_publish_dialog as dialog_module

    confirm = object()

    class FakeMessageBox:
        DestructiveRole = object()
        Cancel = object()

        def __init__(self, *_args, **_kwargs):
            pass

        def setWindowTitle(self, *_args):
            pass

        def setText(self, *_args):
            pass

        def addButton(self, *_args):
            return confirm

        def exec(self):
            return 0

        def clickedButton(self):
            return confirm

    monkeypatch.setattr(dialog_module, "QMessageBox", FakeMessageBox)
    vm = FakeViewModel()
    changes = [FakeFileChange("pro/old.blend", "!")]
    dialog = _dialog(changes, vm)
    dialog._select_all_missing()

    dialog._delete_missing()

    assert vm.delete_calls == [(dialog.card, [changes[0]])]
    dialog.deleteLater()
