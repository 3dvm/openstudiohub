"""Unit tests for the artist project summaries and comment badges."""

from pathlib import Path
from types import SimpleNamespace

from src.application.credential_vault import CredentialVault
from src.infrastructure.comment_read_store import CommentReadStore
from src.interfaces.qt.viewmodels.artist_viewmodel import (
    ArtistTaskCardModel,
    ArtistViewModel,
)


class FakeConfig:
    def get_workspace_root(self):
        return Path("/tmp/does-not-exist")

    def get_vfs_pipeline_name(self):
        return "pipeline"

    def get_vfs_local_name(self):
        return "local"

    def get_vcs_adapter_type(self):
        return "svn"


class FakeUser:
    id = "me"


class FakeAuth:
    current_user = FakeUser()


def _card(task_id, project_id="p1", project_name="Neon", installed=False):
    return ArtistTaskCardModel(
        task_data={
            "id": task_id,
            "project_id": project_id,
            "project_name": project_name,
            "entity_name": "Monkey",
            "task_type_name": "Modeling",
        },
        project_root=None,
        config_path=None,
        is_installed=installed,
        can_work=True,
        blocked_reason="",
        project_id=project_id,
        project_name=project_name,
    )


def _vm(store):
    return ArtistViewModel(
        production_service=None,
        auth_service=FakeAuth(),
        credential_vault=CredentialVault(),
        config_factory=FakeConfig(),
        installation_service=None,
        register_instance=lambda active: None,
        comment_read_store=store,
    )


def test_project_summaries_are_unique_sorted_and_counted():
    cards = [
        _card("t1", "p2", "Zeta", installed=True),
        _card("t2", "p1", "Alpha"),
        _card("t3", "p1", "Alpha"),
    ]

    summaries = ArtistViewModel._project_summaries(cards)

    assert [item["id"] for item in summaries] == ["p1", "p2"]
    assert summaries[0]["task_count"] == 2
    assert summaries[1]["installed"] is True


def test_comment_summary_baselines_unseen_tasks_and_counts_new(qapp, tmp_path):
    store = CommentReadStore(path=tmp_path / "seen.json")
    store.set_last_seen("me", "t1", "2026-10-20T10:00:00+00:00")
    vm = _vm(store)
    vm._cards = [_card("t1"), _card("t2")]
    captured = {}
    vm.comment_counts_ready.connect(lambda counts: captured.update(counts))

    vm._on_comment_summary(
        {
            "p1": [
                {
                    "id": "c1",
                    "task_id": "t1",
                    "person_id": "u2",
                    "created_at": "2026-10-20T12:00:00Z",
                    "text": "new",
                },
                {
                    "id": "c2",
                    "task_id": "t2",
                    "person_id": "u2",
                    "created_at": "2026-10-20T09:00:00Z",
                    "text": "old",
                },
            ]
        }
    )

    assert captured["t1"] == {
        "total": 1,
        "unread": 1,
        "checklist_done": 0,
        "checklist_total": 0,
    }
    assert captured["t2"] == {
        "total": 1,
        "unread": 0,
        "checklist_done": 0,
        "checklist_total": 0,
    }
    assert store.get_last_seen("me", "t2") == "2026-10-20T09:00:00+00:00"
