"""Unit tests for the artist task-list refresh (loading signals + badge carry-over)."""

from src.application.credential_vault import CredentialVault
from src.interfaces.qt.viewmodels.artist_viewmodel import ArtistViewModel


class FakeConfig:
    def get_workspace_root(self):
        from pathlib import Path

        return Path("/tmp/does-not-exist")

    def get_vfs_pipeline_name(self):
        return "pipeline"

    def get_vfs_local_name(self):
        return "local"

    def get_vcs_adapter_type(self):
        return "svn"


def _vm():
    return ArtistViewModel(
        production_service=None,
        auth_service=None,
        credential_vault=CredentialVault(),
        config_factory=FakeConfig(),
        installation_service=None,
        register_instance=lambda active: None,
    )


def _task(task_id: str) -> dict:
    return {
        "id": task_id,
        "project_id": "p1",
        "project_name": "Neon",
        "task_type_name": "Modeling",
        "entity_name": "Monkey",
        "data": {},
    }


def test_load_tasks_is_guarded_while_loading(qapp):
    vm = _vm()
    started = []
    vm.tasks_load_started.connect(lambda: started.append(True))

    vm._tasks_loading = True
    vm.load_tasks()

    assert started == []  # guard prevented a second fetch


def test_tasks_fetched_carries_pending_changes_by_task_id(qapp):
    vm = _vm()
    previous = vm.enrich_task(_task("t1"))
    previous.pending_changes = [object(), object()]
    vm._cards = [previous]

    finished = []
    vm.tasks_load_finished.connect(finished.append)

    vm._on_tasks_fetched([_task("t1"), _task("t2")])

    by_id = {card.task_data["id"]: card for card in vm._cards}
    assert len(by_id["t1"].pending_changes) == 2
    assert by_id["t2"].pending_changes == []
    assert finished == [True]
    assert vm._tasks_loading is False


def test_tasks_fetched_empty_clears_cards(qapp):
    vm = _vm()
    vm._cards = [vm.enrich_task(_task("t1"))]
    finished = []
    loaded = []
    vm.tasks_load_finished.connect(finished.append)
    vm.tasks_loaded.connect(loaded.append)

    vm._on_tasks_fetched([])

    assert vm._cards == []
    assert loaded == [[]]
    assert finished == [True]


def test_tasks_fetch_failure_emits_finished_false(qapp):
    vm = _vm()
    finished = []
    vm.tasks_load_finished.connect(finished.append)

    vm._tasks_loading = True
    vm._on_tasks_fetch_failed("boom")

    assert finished == [False]
    assert vm._tasks_loading is False
