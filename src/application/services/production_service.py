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

    def list_open_projects(self) -> List[dict]:
        """Return all open projects (raw Kitsu dicts) for the project grid."""
        try:
            return self.kitsu.get_all_projects()
        except Exception as error:  # noqa: BLE001
            print(f"[ProductionService] Error listing projects: {error}")
            return []

    def get_artist_task_board(self) -> List[dict]:
        """Assigned tasks (filtered + asset-enriched) for the artist dashboard.

        This moves the enrichment logic out of the UI worker into the
        application layer.
        """
        try:
            raw_user = self.kitsu.get_current_user()
            all_tasks = self.kitsu.all_tasks_for_person(raw_user)
        except Exception as error:  # noqa: BLE001
            print(f"[ProductionService] Error fetching artist tasks: {error}")
            return []

        status_targets = ["Todo", "Work In Progress", "Waiting For Approval", "Retake", "Ready To Start"]
        tasks = [
            task
            for task in all_tasks
            if task.get("task_status_name") in status_targets
            or (task.get("task_status") or {}).get("name") in status_targets
        ]

        for task in tasks:
            entity_type = (task.get("entity_type_name") or task.get("entity_type") or "").lower()
            if entity_type == "asset":
                try:
                    asset = self.kitsu.get_asset(task["entity_id"])
                    if asset:
                        task["asset_type_id"] = asset.get("entity_type_id", "")
                        asset_type = self.kitsu.get_asset_type(task["asset_type_id"])
                        if asset_type:
                            task["asset_type_name"] = asset_type.get("name", "")
                except Exception as inner_error:  # noqa: BLE001
                    print(f"[ProductionService] Warning: failed to enrich asset: {inner_error}")

        return tasks

    def get_recent_activity(self, limit: int = 15) -> List[dict]:
        # TODO(Phase 3): implement against the ProductionRepository.
        return []

    def acknowledge_activity(self, task_id: str, comment_id: str) -> bool:
        # TODO(Phase 3): implement against the ProductionRepository.
        return True
