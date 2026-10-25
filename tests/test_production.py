"""Unit tests for the Production bounded context."""

from pathlib import Path

import pytest

from src.domain.production.entities import Task
from src.domain.production.naming import NamingPolicy
from src.domain.production.value_objects import EntityType, FilePath
from src.infrastructure.kitsu.production_repository import KitsuProductionRepository


# ----------------------------------------------------------------------
# Value objects
# ----------------------------------------------------------------------
def test_entity_type_from_raw():
    assert EntityType.from_raw("shot") is EntityType.SHOT
    assert EntityType.from_raw("Shot") is EntityType.SHOT
    assert EntityType.from_raw("asset") is EntityType.ASSET
    assert EntityType.from_raw("sequence") is EntityType.SEQUENCE
    assert EntityType.from_raw("edit") is EntityType.EDIT
    assert EntityType.from_raw("") is EntityType.UNKNOWN
    assert EntityType.from_raw(None) is EntityType.UNKNOWN


def test_file_path_value_object():
    fp = FilePath("pro/shots/sq01/sh010")
    assert str(fp) == "pro/shots/sq01/sh010"
    assert str(Path("root") / fp) == "root/pro/shots/sq01/sh010"


# ----------------------------------------------------------------------
# NamingPolicy (single source of truth for entity -> path)
# ----------------------------------------------------------------------
def test_naming_shot():
    assert NamingPolicy.shot_dir("sq01", "sh010") == "pro/shots/sq01/sh010"
    assert NamingPolicy.shot_path("sq01", "sh010", "Animation") == "pro/shots/sq01/sh010/sh010-anim.blend"


def test_naming_asset():
    assert NamingPolicy.asset_dir("Character", "Prota") == "pro/assets/character/prota"
    assert (
        NamingPolicy.asset_path("Character", "Prota", "Modeling")
        == "pro/assets/character/prota/character-prota-model.blend"
    )


def test_naming_storyboard_and_edit():
    assert NamingPolicy.storyboard_path("sq01") == "edit/storyboards/sq01-storyboard.blend"
    # File names are always lower-cased, including the edit master.
    assert NamingPolicy.edit_path("Neon Chase") == "edit/neon-chase-edit.blend"
    assert NamingPolicy.edit_path("MIDEQ_promo") == "edit/mideq_promo-edit.blend"


def test_normalize_task_name():
    assert NamingPolicy.normalize_task_name("animación") == "anim"
    assert NamingPolicy.normalize_task_name("Modeling") == "model"
    assert NamingPolicy.normalize_task_name("Layout") == "layout"
    assert NamingPolicy.normalize_task_name("") == "generic"


def test_sparse_path():
    assert str(NamingPolicy.sparse_path(EntityType.SHOT, "sh010", "sq01")) == "pro/shots/sq01/sh010"
    assert (
        str(NamingPolicy.sparse_path(EntityType.ASSET, "Prota", asset_type_name="Character"))
        == "pro/assets/character/prota"
    )
    with pytest.raises(ValueError):
        NamingPolicy.sparse_path(EntityType.SHOT, "sh010", "")


def test_workfile_path_storyboard_uses_entity_name():
    fp = NamingPolicy.workfile_path(EntityType.SEQUENCE, "sq01", task_short_name="storyboard")
    assert str(fp) == "edit/storyboards/sq01-storyboard.blend"


# ----------------------------------------------------------------------
# Task entity
# ----------------------------------------------------------------------
def test_task_from_kitsu_dict():
    task = Task.from_kitsu_dict(
        {
            "id": "t1",
            "entity_id": "e1",
            "entity_type_name": "Shot",
            "entity_name": "sh010",
            "sequence_name": "sq01",
            "project_id": "p1",
            "project_name": "Neon",
            "task_type_id": "tt1",
            "task_type_name": "Animation",
            "task_status_name": "Todo",
        }
    )
    assert task.entity_type is EntityType.SHOT
    assert task.status == "Todo"
    assert task.task_type_short_name == "Animation"  # fallback to task_type_name
    assert str(task.workfile_path()) == "pro/shots/sq01/sh010/sh010-anim.blend"


# ----------------------------------------------------------------------
# ProductionRepository (typed translation over the gazu ACL)
# ----------------------------------------------------------------------
class FakeKitsu:
    def all_projects(self):
        return [{"id": "p1", "name": "Neon"}]

    def get_project(self, pid):
        return {"id": pid, "name": "Neon"}

    def all_sequences_for_project(self, pid):
        return [{"id": "s1", "name": "sq01", "project_id": pid}]

    def get_sequence(self, sid):
        return {"id": sid, "name": "sq01"}

    def all_shots_for_project(self, pid):
        return [{"id": "sh1", "name": "sh010", "sequence_id": "s1", "status": "Todo", "nb_frames": 48}]

    def all_assets_for_project(self, pid):
        return [{"id": "a1", "name": "Prota", "entity_type_id": "at1", "status": "Todo"}]

    def get_asset_type(self, atid):
        return {"id": atid, "name": "Character"}

    def all_task_types(self):
        return [{"id": "tt1", "name": "Animation", "for_entity": "Shot"}]

    def get_task_type_by_name(self, name):
        return {"id": "tt1", "name": name, "for_entity": "Shot"}

    def new_task_type(self, name, color="#000000", for_entity="Asset"):
        return {"id": "tt2", "name": name, "for_entity": for_entity}

    def create_task(self, entity_id, task_type):
        return {
            "id": "t1",
            "entity_id": entity_id,
            "task_type_id": task_type["id"],
            "entity_type_name": "Shot",
            "entity_name": "sh010",
            "task_type_name": task_type["name"],
            "task_status_name": "Todo",
        }

    def all_tasks_for_asset(self, asset):
        return [
            {
                "id": "t1",
                "entity_id": asset.get("id", ""),
                "entity_type_name": "Asset",
                "entity_name": asset.get("name", ""),
                "asset_type_name": "Character",
                "task_type_id": "tt1",
                "task_type_name": "Modeling",
                "data": {"filepath": "pro/assets/character/prota/character-prota-model.blend"},
            }
        ]

    def get_task(self, task_id):
        return {"id": task_id, "data": {}}

    def update_task_data(self, task, data):
        return {"id": task.get("id"), "data": data}

    def update_entity_data(self, entity_id, data):
        return {}


def test_repository_reads():
    repo = KitsuProductionRepository(FakeKitsu())
    assert repo.all_projects()[0].name == "Neon"
    shots = repo.all_shots_for_project("p1")
    assert shots[0].name == "sh010" and shots[0].nb_frames == 48
    assets = repo.all_assets_for_project("p1")
    assert assets[0].asset_type_id == "at1"
    assert repo.get_asset_type("at1").name == "Character"
    assert repo.all_task_types()[0].name == "Animation"


def test_repository_create_task():
    repo = KitsuProductionRepository(FakeKitsu())
    task = repo.create_task("sh1", "Animation")
    assert task is not None
    assert task.id == "t1"
    assert task.entity_type is EntityType.SHOT


def test_repository_update_entity_data():
    repo = KitsuProductionRepository(FakeKitsu())
    assert repo.update_entity_data("e1", {"blend_file_path": "x"}) is True


def test_repository_asset_tasks_and_task_data_update():
    repo = KitsuProductionRepository(FakeKitsu())
    tasks = repo.all_tasks_for_asset({"id": "a1", "name": "Prota"})
    assert tasks[0].filepath == "pro/assets/character/prota/character-prota-model.blend"
    assert repo.update_task_data("t1", {"filepath": "x.blend"}) is True


# ----------------------------------------------------------------------
# Task linked-file helpers
# ----------------------------------------------------------------------
def test_task_filepath_helpers(tmp_path):
    task = Task.from_kitsu_dict(
        {
            "id": "t1",
            "entity_type_name": "Asset",
            "entity_name": "Prota",
            "asset_type_name": "Character",
            "task_type_name": "Modeling",
            "data": {"filepath": "pro/assets/character/prota/character-prota-model.blend"},
        }
    )
    assert task.filepath == "pro/assets/character/prota/character-prota-model.blend"
    assert task.has_file(tmp_path, "svn") is False

    physical = tmp_path / "svn" / task.filepath
    physical.parent.mkdir(parents=True)
    physical.write_bytes(b"x")
    assert task.has_file(tmp_path, "svn") is True

    assert task.with_filepath("other.blend").filepath == "other.blend"
    assert task.without_filepath().filepath == ""
    assert task.filepath == "pro/assets/character/prota/character-prota-model.blend"


# ----------------------------------------------------------------------
# Launch target resolution (mixed-case DCC masters)
# ----------------------------------------------------------------------
def test_find_latest_versioned_matches_mixed_case_and_orders_numerically(tmp_path):
    from src.application.services.launch_service import LaunchService

    edit_dir = tmp_path / "edit"
    edit_dir.mkdir()
    for name in (
        "MIDEQ_promo-edit-v001.blend",
        "MIDEQ_promo-edit-v010.blend",
        "MIDEQ_promo-edit-v002.blend",
    ):
        (edit_dir / name).write_bytes(b"")

    latest = LaunchService._find_latest_versioned(edit_dir / "mideq_promo-edit")

    assert latest is not None
    assert latest.name == "MIDEQ_promo-edit-v010.blend"


def test_find_latest_versioned_returns_none_when_absent(tmp_path):
    from src.application.services.launch_service import LaunchService

    assert LaunchService._find_latest_versioned(tmp_path / "edit" / "missing") is None


def test_find_case_insensitive_unversioned(tmp_path):
    from src.application.services.launch_service import LaunchService

    edit_dir = tmp_path / "edit"
    edit_dir.mkdir()
    (edit_dir / "MIDEQ_promo-edit.blend").write_bytes(b"")

    found = LaunchService._find_case_insensitive(edit_dir / "mideq_promo-edit.blend")

    assert found is not None
    assert found.name == "MIDEQ_promo-edit.blend"


def test_resolve_target_file_finds_mixed_case_edit_master(tmp_path):
    from src.application.services.launch_service import LaunchService

    project_root = tmp_path / "project"
    edit_dir = project_root / "svn" / "edit"
    edit_dir.mkdir(parents=True)
    (edit_dir / "MIDEQ_promo-edit-v001.blend").write_bytes(b"")

    # The Hub often only has the lower-cased folder/project name.
    task_data = {"entity_type_name": "Edit", "project_name": "mideq_promo"}
    resolved = LaunchService._resolve_target_file(project_root, "svn", task_data, None)

    assert resolved is not None
    assert resolved.name == "MIDEQ_promo-edit-v001.blend"
