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


def test_update_vcs_skips_when_vcs_disabled(tmp_path, qapp):
    vm = _vm(tmp_path, vcs_type="none")
    card = _card(tmp_path)

    assert vm.update_vcs(card.project_id, card.project_root) is False


def test_update_vcs_aborts_when_credentials_cancelled(tmp_path, qapp):
    vm = _vm(tmp_path)
    vm._ensure_vcs_credentials = lambda _root=None: None
    card = _card(tmp_path)

    assert vm.update_vcs(card.project_id, card.project_root) is False


def test_update_vcs_starts_worker(tmp_path, qapp):
    vm = _vm(tmp_path)
    vm._ensure_vcs_credentials = lambda _root=None: ("artist", "secret")
    started = {}

    def fake_start(key, worker, **kwargs):
        started["key"] = key
        started["worker"] = worker
        return True

    vm.workers.start = fake_start
    card = _card(tmp_path)

    assert vm.update_vcs(card.project_id, card.project_root) is True
    assert started["key"] == "vcs_update"
    assert started["worker"].project_id == "p1"


def test_update_finished_emits_and_rescans(tmp_path, qapp):
    vm = _vm(tmp_path)
    card = _card(tmp_path)
    vm._cards = [card]
    scanned = []
    vm.check_vcs_changes = lambda c: scanned.append(c)
    received = []
    vm.vcs_update_finished.connect(lambda *args: received.append(args))

    vm._on_vcs_update_finished("p1", True, "Workspace updated from the VCS.")

    assert scanned == [card]
    assert received == [("p1", True, "Workspace updated from the VCS.")]


def test_update_finished_skips_rescan_on_failure(tmp_path, qapp):
    vm = _vm(tmp_path)
    card = _card(tmp_path)
    vm._cards = [card]
    scanned = []
    vm.check_vcs_changes = lambda c: scanned.append(c)

    vm._on_vcs_update_finished("p1", False, "SVN Failure: out of date")

    assert scanned == []


def test_completed_checklist_items_filters_and_deduplicates(tmp_path, qapp):
    vm = _vm(tmp_path)
    vm._comments_by_task = {
        "t1": [
            {
                "checklist": [
                    {"text": "Model approved", "checked": True},
                    {"text": "Pending item", "checked": False},
                ]
            },
            {"checklist": [{"text": "Model approved", "checked": True}]},
        ]
    }

    assert vm.completed_checklist_items("t1") == ["Model approved"]


def test_can_break_foreign_locks_requires_td_role(tmp_path, qapp):
    from src.domain.identity.value_objects import Role

    class Auth:
        def __init__(self, role):
            self.role = role

        def current_role(self):
            return self.role

    vm = _vm(tmp_path)
    vm.auth_service = Auth(Role.ARTIST)
    assert vm.can_break_foreign_locks() is False
    vm.auth_service = Auth(Role.TD)
    assert vm.can_break_foreign_locks() is True


def test_conflict_resolution_emits_and_rescans(tmp_path, qapp):
    vm = _vm(tmp_path)
    card = _card(tmp_path)
    vm._cards = [card]
    received = []
    rescanned = []
    vm.vcs_conflict_resolved.connect(lambda *args: received.append(args))
    vm.check_vcs_changes = lambda candidate: rescanned.append(candidate)

    vm._on_vcs_conflict_resolved("t1", True, "Conflict resolved.")

    assert received == [("t1", True, "Conflict resolved.")]
    assert rescanned == [card]


def test_history_ready_emits_revisions(tmp_path, qapp):
    vm = _vm(tmp_path)
    received = []
    vm.vcs_history_ready.connect(lambda task_id, revisions: received.append((task_id, revisions)))

    vm._on_vcs_history_ready("t1", [{"revision": "7"}])

    assert received == [("t1", [{"revision": "7"}])]


def test_update_report_opens_review_when_issues_remain(tmp_path, qapp):
    from src.application.services.task_file_sync_service import VcsUpdateReport
    from src.domain.production.value_objects import FileChange

    vm = _vm(tmp_path)
    received = []
    vm.vcs_update_review_required.connect(
        lambda project_id, report: received.append((project_id, report))
    )
    report = VcsUpdateReport(False, "needs attention", (FileChange("a.blend", "~"),))

    vm._on_vcs_update_report("p1", report)

    assert received == [("p1", report)]


def test_update_report_without_issues_does_not_open_review(tmp_path, qapp):
    from src.application.services.task_file_sync_service import VcsUpdateReport

    vm = _vm(tmp_path)
    received = []
    vm.vcs_update_review_required.connect(
        lambda project_id, report: received.append((project_id, report))
    )

    vm._on_vcs_update_report("p1", VcsUpdateReport(True, "clean"))

    assert received == []
