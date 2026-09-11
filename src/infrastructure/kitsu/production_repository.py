# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/kitsu/production_repository.py
# Architectural role: Infrastructure / Kitsu ProductionRepository
# =========================================================================================

"""Kitsu-backed ``ProductionRepository``.

This is the translation boundary between Kitsu's raw dict schema and the typed
``src.domain.production`` entities. All gazu access goes through the
``KitsuManager`` anti-corruption layer; no gazu call or raw Kitsu dict escapes
this module.
"""

from typing import List, Optional

from src.application.ports import ProductionRepository
from src.domain.production.entities import (
    Project,
    Sequence,
    Shot,
    Asset,
    AssetType,
    TaskType,
    Task,
)
from src.infrastructure.kitsu_manager import KitsuManager


class KitsuProductionRepository(ProductionRepository):
    def __init__(self, kitsu: KitsuManager) -> None:
        self.kitsu = kitsu

    # --- Projects ---
    def all_projects(self) -> List[Project]:
        return [Project.from_kitsu_dict(p) for p in self.kitsu.all_projects()]

    def get_project(self, project_id: str) -> Optional[Project]:
        raw = self.kitsu.get_project(project_id)
        return Project.from_kitsu_dict(raw) if raw else None

    # --- Sequences / Shots / Assets ---
    def all_sequences_for_project(self, project_id: str) -> List[Sequence]:
        return [Sequence.from_kitsu_dict(s) for s in self.kitsu.all_sequences_for_project(project_id)]

    def get_sequence(self, sequence_id: str) -> Optional[Sequence]:
        raw = self.kitsu.get_sequence(sequence_id)
        return Sequence.from_kitsu_dict(raw) if raw else None

    def all_shots_for_project(self, project_id: str) -> List[Shot]:
        return [Shot.from_kitsu_dict(s) for s in self.kitsu.all_shots_for_project(project_id)]

    def all_assets_for_project(self, project_id: str) -> List[Asset]:
        return [Asset.from_kitsu_dict(a) for a in self.kitsu.all_assets_for_project(project_id)]

    def get_asset_type(self, asset_type_id: str) -> Optional[AssetType]:
        raw = self.kitsu.get_asset_type(asset_type_id)
        return AssetType.from_kitsu_dict(raw) if raw else None

    # --- Task types / tasks ---
    def all_task_types(self) -> List[TaskType]:
        return [TaskType.from_kitsu_dict(t) for t in self.kitsu.all_task_types()]

    def get_task_type_by_name(self, name: str) -> Optional[TaskType]:
        raw = self.kitsu.get_task_type_by_name(name)
        return TaskType.from_kitsu_dict(raw) if raw else None

    def new_task_type(self, name: str, color: str = "#000000", for_entity: str = "Asset") -> TaskType:
        raw = self.kitsu.new_task_type(name, color=color, for_entity=for_entity)
        return TaskType.from_kitsu_dict(raw) if raw else TaskType(name=name, for_entity=for_entity)

    def create_task(self, entity_id: str, task_type_name: str) -> Optional[Task]:
        task_type = self.kitsu.get_task_type_by_name(task_type_name)
        if not task_type:
            return None
        raw = self.kitsu.create_task(entity_id, task_type)
        return Task.from_kitsu_dict(raw) if raw else None

    # --- Metadata ---
    def update_entity_data(self, entity_id: str, data: dict) -> bool:
        try:
            self.kitsu.update_entity_data(entity_id, data)
            return True
        except Exception:  # noqa: BLE001 - surfaced as False to the caller
            return False
