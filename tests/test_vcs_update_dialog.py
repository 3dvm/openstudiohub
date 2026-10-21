"""Unit tests for the VCS update cleanup dialog."""

from types import SimpleNamespace

from src.domain.production.value_objects import FileChange
from src.interfaces.qt.views.vcs_update_dialog import VcsUpdateDialog


class FakeViewModel:
    def __init__(self) -> None:
        self.moved = []
        self.ignored = []
        self.updates = []

    def move_vcs_path_aside(self, project_root, relative_path):
        self.moved.append((project_root, relative_path))
        return True, "Moved aside."

    def ignore_vcs_path(self, project_root, relative_path):
        self.ignored.append((project_root, relative_path))
        return True, "Ignored."

    def update_vcs(self, project_id, project_root):
        self.updates.append((project_id, project_root))
        return True


def _report():
    return SimpleNamespace(
        message="Update needs attention.",
        issues=[
            FileChange("pro/cache.tmp", "~"),
            FileChange("pro/a.blend", "C", tree_conflicted=True),
        ],
    )


def test_update_dialog_lists_issues(qapp, tmp_path):
    dialog = VcsUpdateDialog(None, FakeViewModel(), "p1", tmp_path, _report())

    assert dialog.issue_list.count() == 2
    assert dialog.btn_move.isEnabled() is True
    dialog.deleteLater()


def test_conflicts_cannot_be_moved_aside(qapp, tmp_path):
    dialog = VcsUpdateDialog(None, FakeViewModel(), "p1", tmp_path, _report())
    dialog.issue_list.setCurrentRow(1)

    assert dialog.btn_move.isEnabled() is False
    assert dialog.btn_ignore.isEnabled() is False
    dialog.deleteLater()


def test_move_aside_removes_the_issue(qapp, tmp_path):
    vm = FakeViewModel()
    dialog = VcsUpdateDialog(None, vm, "p1", tmp_path, _report())
    dialog.issue_list.setCurrentRow(0)

    dialog._move_aside()

    assert vm.moved == [(tmp_path, "pro/cache.tmp")]
    assert dialog.issue_list.count() == 1
    dialog.deleteLater()


def test_ignore_keeps_the_issue_visible(qapp, tmp_path):
    vm = FakeViewModel()
    dialog = VcsUpdateDialog(None, vm, "p1", tmp_path, _report())
    dialog.issue_list.setCurrentRow(0)

    dialog._ignore()

    assert vm.ignored == [(tmp_path, "pro/cache.tmp")]
    assert dialog.issue_list.count() == 2
    dialog.deleteLater()


def test_retry_starts_the_update_and_closes(qapp, tmp_path):
    vm = FakeViewModel()
    dialog = VcsUpdateDialog(None, vm, "p1", tmp_path, _report())

    dialog._retry()

    assert vm.updates == [("p1", tmp_path)]
    assert dialog.result() == 1
    dialog.deleteLater()
