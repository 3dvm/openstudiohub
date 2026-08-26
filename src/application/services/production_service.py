# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/production_service.py
# Architectural role: Application service / Kitsu production queries
# =========================================================================================

"""Production query service.

Interim home for the Kitsu production-data queries that previously lived on
``AuthManager``. In Phase 3 these move behind a ``ProductionRepository`` port
with typed domain entities (Project/Shot/Asset/Task); for now they keep their
existing behavior so consumers are unchanged.
"""

from typing import Dict, List, Optional

from src.infrastructure.kitsu_manager import KitsuManager


class ProductionService:
    def __init__(self, kitsu: KitsuManager) -> None:
        self.kitsu = kitsu

    def sync_studio_identity(self) -> dict:
        identity: dict = {}
        try:
            org = self.kitsu.get_organisation()
            if isinstance(org, dict) and "name" in org:
                identity["name"] = org["name"]
        except Exception as error:  # noqa: BLE001
            print(f"[ProductionService] Info: Failed to fetch Organisation from server ({error})")
        return identity

    def obtener_proyectos_activos(self) -> Dict[str, str]:
        proyectos: Dict[str, str] = {}
        try:
            for project in self.kitsu.get_all_projects():
                proyectos[project["name"].lower()] = project["id"]
        except Exception as error:  # noqa: BLE001
            print(f"[ProductionService] Error fetching active projects: {error}")
        return proyectos

    def get_task_metadata(self, task_id: str) -> Optional[Dict[str, str]]:
        try:
            return self.kitsu.get_task(task_id)
        except Exception:  # noqa: BLE001
            return None

    def get_assigned_tasks(self) -> List[dict]:
        try:
            return self.kitsu.all_tasks_to_do()
        except Exception as error:  # noqa: BLE001
            print(f"[ProductionService] Error fetching assigned tasks: {error}")
            return []

    def get_recent_activity(self, limit: int = 15) -> List[dict]:
        # TODO(Phase 3): implement against the ProductionRepository.
        return []

    def acknowledge_activity(self, task_id: str, comment_id: str) -> bool:
        # TODO(Phase 3): implement against the ProductionRepository.
        return True
