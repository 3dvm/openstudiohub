"""Unit tests for the artist dashboard VCS publish flow."""

from src.application.credential_vault import CredentialVault
from src.interfaces.qt.viewmodels.artist_viewmodel import (
    ArtistTaskCardModel,
    ArtistViewModel,
)


class FakeConfig:
    def __init__(self, vcs_type: str = "svn") -> None:
        self._vcs_type = vcs_type

    def get_vcs_adapter_type(self) -> str:
        return self._vcs_type


class FakeChange:
    def __init__(self, relative_path: str, status: str = "M") -> None:
        self.relative_path = relative_path
        self.status = status

    @property
    def is_unversioned(self) -> bool:
        return self.status == "?"


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


def _vm(tmp_path, vcs_type="svn"):
    return ArtistViewModel(
        production_service=None,
        auth_service=None,
        credential_vault=CredentialVault(),
        config_factory=FakeConfig(vcs_type),
        installation_service=None,
        register_instance=lambda active: None,
    )


def test_launch_finish_triggers_vcs_scan(tmp_path, qapp):
    vm = _vm(tmp_path)
    card = _card(tmp_path)
    vm._launching_card = card
    seen = []
    vm.check_vcs_changes = lambda c: seen.append(c)

    vm._on_launch_finished(True, "Session finished.")

    assert seen == [card]
    assert vm._launching_card is None


def test_launch_finish_skips_scan_without_linked_file(tmp_path, qapp):
    vm = _vm(tmp_path)
    card = _card(tmp_path, task_file_path=None)
    vm._launching_card = card
    seen = []
    vm.check_vcs_changes = lambda c: seen.append(c)

    vm._on_launch_finished(True, "Session finished.")

    assert seen == []


def test_launch_finish_skips_scan_when_vcs_disabled(tmp_path, qapp):
    vm = _vm(tmp_path, vcs_type="none")
    card = _card(tmp_path)
    vm._launching_card = card
    seen = []
    vm.check_vcs_changes = lambda c: seen.append(c)

    vm._on_launch_finished(True, "Session finished.")

    assert seen == []


def test_changes_ready_updates_card_and_emits(tmp_path, qapp):
    vm = _vm(tmp_path)
    card = _card(tmp_path)
    vm._cards = [card]
    received = []
    vm.vcs_changes_ready.connect(lambda task_id, changes: received.append((task_id, changes)))
    changes = [FakeChange("pro/a.blend")]

    vm._on_vcs_changes_ready("t1", changes)

    assert card.pending_changes == changes
    assert received == [("t1", changes)]


def test_publish_finished_clears_pending_on_success(tmp_path, qapp):
    vm = _vm(tmp_path)
    card = _card(tmp_path)
    card.pending_changes = [FakeChange("pro/a.blend")]
    vm._cards = [card]

    vm._on_vcs_publish_finished("t1", True, "Published 1 file(s) to the VCS.")

    assert card.pending_changes == []


def test_publish_finished_keeps_pending_on_failure(tmp_path, qapp):
    vm = _vm(tmp_path)
    card = _card(tmp_path)
    pending = [FakeChange("pro/a.blend")]
    card.pending_changes = pending
    vm._cards = [card]

    vm._on_vcs_publish_finished("t1", False, "SVN Failure: out of date")

    assert card.pending_changes == pending
