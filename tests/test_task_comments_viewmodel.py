"""Unit tests for the checklist toggle flow in the comments ViewModel."""

from types import SimpleNamespace

from src.interfaces.qt.viewmodels.task_comments_viewmodel import TaskCommentsViewModel


class FakeAuth:
    current_user = SimpleNamespace(id="me")


class FakeProduction:
    def list_persons(self):
        return []

    def update_comment_checklist(self, comment_id, checklist):
        return {"id": comment_id, "checklist": checklist}


def _vm():
    return TaskCommentsViewModel(FakeProduction(), FakeAuth())


def _comment(checked=False):
    return {"id": "c1", "checklist": [{"text": "Check lighting", "checked": checked}]}


def test_toggle_checklist_updates_optimistically(qapp, monkeypatch):
    vm = _vm()
    vm._task_id = "t1"
    vm._comments = [_comment()]
    monkeypatch.setattr(vm.workers, "start", lambda *args, **kwargs: True)

    emitted = []
    updating = []
    vm.comments_loaded.connect(lambda _tid, comments: emitted.append(comments))
    vm.checklist_updating.connect(updating.append)

    vm.toggle_checklist("c1", 0, True)

    assert vm._comments[0]["checklist"][0]["checked"] is True
    assert emitted[-1][0]["_checklist"][0]["checked"] is True
    assert updating == [True]


def test_checklist_failure_reverts_to_previous_state(qapp):
    vm = _vm()
    vm._task_id = "t1"
    vm._comments = [_comment(checked=True)]
    vm._checklist_revert = ("c1", [{"text": "Check lighting", "checked": False}])

    emitted = []
    updating = []
    vm.comments_loaded.connect(lambda _tid, comments: emitted.append(comments))
    vm.checklist_updating.connect(updating.append)

    vm._on_checklist_updated("c1", False, "permission denied", None)

    assert vm._comments[0]["checklist"][0]["checked"] is False
    assert emitted[-1][0]["_checklist"][0]["checked"] is False
    assert updating == [False]


def test_checklist_success_uses_server_state(qapp):
    vm = _vm()
    vm._task_id = "t1"
    vm._comments = [_comment(checked=True)]

    vm._on_checklist_updated(
        "c1", True, "ok", {"checklist": [{"text": "Check lighting", "checked": True}]}
    )

    assert vm._comments[0]["checklist"][0]["checked"] is True
