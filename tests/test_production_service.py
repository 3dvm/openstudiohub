"""Unit tests for the ProductionService (artist task board + project listing)."""

from src.application.services.production_service import ProductionService


class FakeKitsu:
    def get_all_projects(self):
        return [{"id": "p1", "name": "Neon"}]

    def get_current_user(self):
        return {"id": "u1"}

    def all_tasks_for_person(self, user):
        return [
            {"id": "t1", "entity_type_name": "Shot", "task_status_name": "Todo"},
            {"id": "t2", "entity_type_name": "Asset", "entity_id": "a1", "task_status_name": "Todo"},
            {"id": "t3", "entity_type_name": "Shot", "task_status_name": "Done"},
        ]

    def get_asset(self, asset_id):
        return {"id": "a1", "entity_type_id": "at1"}

    def get_asset_type(self, asset_type_id):
        return {"id": "at1", "name": "Character"}


def test_list_open_projects():
    svc = ProductionService(FakeKitsu())
    assert svc.list_open_projects()[0]["name"] == "Neon"


def test_get_artist_task_board_filters_and_enriches():
    svc = ProductionService(FakeKitsu())
    tasks = svc.get_artist_task_board()

    # "Done" task is filtered out.
    assert len(tasks) == 2
    assert {t["id"] for t in tasks} == {"t1", "t2"}

    asset_task = next(t for t in tasks if t["id"] == "t2")
    assert asset_task["asset_type_id"] == "at1"
    assert asset_task["asset_type_name"] == "Character"


def test_audit_assets_renames_dirty_names(tmp_path):
    class FakeKitsuAssets:
        def __init__(self):
            self.updated = None

        def all_assets_for_project(self, project_id):
            return [{"id": "a1", "name": "My Asset", "entity_type_id": "at1", "data": {}}]

        def all_asset_types(self):
            return [{"id": "at1", "name": "Character"}]

        def update_asset(self, asset):
            self.updated = asset
            return asset

    kitsu = FakeKitsuAssets()
    result = ProductionService(kitsu).audit_assets("p1", tmp_path, "svn")

    assert result[0]["name"] == "my_asset"
    assert result[0]["type"] == "Character"
    assert kitsu.updated["name"] == "my_asset"
