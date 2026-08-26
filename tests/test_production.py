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
    assert NamingPolicy.edit_path("Neon Chase") == "edit/neon-chase-edit.blend"


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
