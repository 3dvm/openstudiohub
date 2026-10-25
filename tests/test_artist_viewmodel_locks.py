"""Unit tests for the artist dashboard task-file lock badges."""

from src.application.credential_vault import CredentialVault
from src.interfaces.qt.viewmodels.artist_viewmodel import (
    ArtistTaskCardModel,
    ArtistViewModel,
)


class FakeConfig:
    def get_vcs_adapter_type(self) -> str:
        return "svn"


class FakeUser:
    email = "me@studio.com"


class FakeAuth:
    current_user = FakeUser()


def _card(tmp_path, task_id="t1", task_file_path="pro/a.blend"):
    return ArtistTaskCardModel(
        task_data={"id": task_id, "entity_name": "Monkey", "task_type_name": "Modeling"},
        project_root=tmp_path,
        config_path=None,
        is_installed=True,
        can_work=True,
        blocked_reason="",
        project_id="p1",
        project_name="Neon",
        task_file_path=task_file_path,
    )


def _vm(tmp_path, auth_service=None):
    return ArtistViewModel(
        production_service=None,
        auth_service=auth_service,
        credential_vault=CredentialVault(),
        config_factory=FakeConfig(),
        installation_service=None,
        register_instance=lambda active: None,
    )


def test_task_locks_ready_marks_foreign_lock(tmp_path, qapp):
    vm = _vm(tmp_path, auth_service=FakeAuth())
    card = _card(tmp_path)
    vm._cards = [card]
    received = []
    vm.task_locks_ready.connect(lambda payload: received.append(payload))

    vm._on_task_locks_ready({"t1": "ana@studio.com"})

    assert card.lock_owner == "ana@studio.com"
    assert card.lock_is_mine is False
    assert received == [{"t1": {"owner": "ana@studio.com", "is_mine": False}}]


def test_task_locks_ready_marks_my_lock(tmp_path, qapp):
    vm = _vm(tmp_path, auth_service=FakeAuth())
    card = _card(tmp_path)
    vm._cards = [card]

    vm._on_task_locks_ready({"t1": "me@studio.com"})

    assert card.lock_owner == "me@studio.com"
    assert card.lock_is_mine is True


def test_task_locks_ready_clears_unlocked_card(tmp_path, qapp):
    vm = _vm(tmp_path, auth_service=FakeAuth())
    card = _card(tmp_path)
    card.lock_owner = "ana@studio.com"
    card.lock_is_mine = False
    vm._cards = [card]

    vm._on_task_locks_ready({})

    assert card.lock_owner == ""
    assert card.lock_is_mine is False


def test_refresh_task_locks_starts_worker_with_linkable_cards(tmp_path, qapp):
    vm = _vm(tmp_path, auth_service=FakeAuth())
    cards = [_card(tmp_path, "t1"), _card(tmp_path, "t2", task_file_path=None)]
    started = {}

    def fake_start(key, worker, **kwargs):
        started["key"] = key
        started["targets"] = worker.targets
        return True

    vm.workers.start = fake_start

    vm._refresh_task_locks(cards)

    assert started["key"] == "task_locks"
    assert started["targets"] == [("t1", tmp_path, "pro/a.blend")]


def test_refresh_task_locks_skips_without_targets(tmp_path, qapp):
    vm = _vm(tmp_path, auth_service=FakeAuth())
    started = []
    vm.workers.start = lambda *args, **kwargs: started.append(args) or True

    vm._refresh_task_locks([_card(tmp_path, "t1", task_file_path=None)])

    assert started == []


def test_emit_task_lock_sends_single_state(tmp_path, qapp):
    vm = _vm(tmp_path, auth_service=FakeAuth())
    card = _card(tmp_path)
    card.lock_owner = "me@studio.com"
    card.lock_is_mine = True
    received = []
    vm.task_locks_ready.connect(lambda payload: received.append(payload))

    vm._emit_task_lock(card)

    assert received == [{"t1": {"owner": "me@studio.com", "is_mine": True}}]
