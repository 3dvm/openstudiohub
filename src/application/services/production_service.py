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

import glob
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.domain.production.naming import NamingPolicy
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

    def list_all_projects(self) -> List[dict]:
        """Return all projects (open + closed) for the project grid."""
        try:
            return self.kitsu.all_projects()
        except Exception as error:  # noqa: BLE001
            print(f"[ProductionService] Error listing all projects: {error}")
            return []

    def audit_shots(self, project_id: str, project_root: Path, vfs_svn: str) -> Tuple[List[dict], List[str]]:
        """Cross-reference shots/tasks against physical files (PM batch audit)."""
        shots = self.kitsu.all_shots_for_project(project_id)
        sequences = self.kitsu.all_sequences_for_project(project_id)
        all_tasks = self.kitsu.all_tasks_for_project(project_id)
        task_types = self.kitsu.all_task_types()

        seq_map = {seq["id"]: seq["name"] for seq in sequences}
        tt_map = {tt["id"]: tt["name"] for tt in task_types}

        tasks_by_entity: Dict[str, list] = {}
        for task in all_tasks:
            tasks_by_entity.setdefault(task.get("entity_id"), []).append(task)

        result = []
        project_task_types = set()

        for shot in shots:
            shot_id = shot["id"]
            shot_tasks = tasks_by_entity.get(shot_id, [])
            shot_tasks_data = {}
            shot_has_all_files = bool(shot_tasks)

            for task in shot_tasks:
                tt_name = tt_map.get(task["task_type_id"], "Unknown")
                project_task_types.add(tt_name)

                task_data = task.get("data") or {}
                kitsu_filepath = task_data.get("filepath")
                has_file = bool(kitsu_filepath) and (project_root / vfs_svn / kitsu_filepath).exists()

                shot_tasks_data[tt_name] = {"task_id": task["id"], "has_file": has_file, "raw_task": task}
                if not has_file:
                    shot_has_all_files = False

            result.append({
                "id": shot_id,
                "name": shot.get("name", "Unknown"),
                "type": "Shot",
                "parent": seq_map.get(shot.get("parent_id"), "Unknow"),
                "frame_in": shot.get("nb_frames", 0),
                "tasks": shot_tasks_data,
                "has_file": shot_has_all_files,
                "raw_data": shot,
            })

        return result, list(project_task_types)

    def audit_sequences(self, project_id: str, project_root: Path, vfs_svn: str) -> List[dict]:
        """Check storyboard .blend existence for each sequence."""
        sequences = self.kitsu.all_sequences_for_project(project_id)
        result = []
        for seq in sequences:
            name = seq.get("name", "").upper()
            file_path = project_root / vfs_svn / "edit" / "storyboards" / f"{name.lower()}-storyboard.blend"
            result.append({"name": name, "has_file": file_path.exists()})
        return result

    def audit_assets(self, project_id: str, project_root: Path, vfs_svn: str) -> List[dict]:
        """Audit assets against physical files and normalize dirty names in Kitsu."""
        assets = self.kitsu.all_assets_for_project(project_id)
        asset_types_map = {at["id"]: at for at in self.kitsu.all_asset_types()}

        result = []
        for asset in assets:
            raw_name = asset.get("name", "Unknown")
            clean_name = NamingPolicy.sanitize_name(raw_name)

            has_file = False
            asset_data = asset.get("data") or {}
            kitsu_filepath = asset_data.get("filepath")
            if kitsu_filepath:
                physical_path = project_root / vfs_svn / kitsu_filepath
                has_file = physical_path.exists()
                if not has_file:
                    print(f"[AUDITORIA ASSETS] ⚠️ Ruta registrada en Kitsu, pero no existe en disco: {physical_path}")

            type_id = asset.get("entity_type_id")
            if type_id and type_id in asset_types_map:
                asset["asset_type_id"] = type_id
                asset["asset_type_name"] = asset_types_map[type_id].get("name", "")
            else:
                asset["asset_type_id"] = ""
                asset["asset_type_name"] = ""

            final_name = raw_name
            if not has_file and raw_name != clean_name:
                try:
                    asset["name"] = clean_name
                    self.kitsu.update_asset(asset)
                    final_name = clean_name
                except Exception as error:  # noqa: BLE001
                    print(f"⚠️ Error actualizando nombre en Kitsu para {raw_name}: {error}")

            asset["name"] = final_name
            result.append({
                "id": asset["id"],
                "name": final_name,
                "type": asset["asset_type_name"],
                "has_file": has_file,
                "raw_data": asset,
            })

        return result

    def audit_edit(self, project_id: str, project_name: str, project_root: Path, vfs_svn: str) -> dict:
        """Audit the master Edit entity against physical .blend files."""
        edits = self.kitsu.all_edits_for_project(project_id)
        main_edit = edits[0] if edits else None

        status_name = "Not Created"
        assignees_names = "Unassigned"

        if main_edit:
            tasks = self.kitsu.all_tasks_for_edit(main_edit["id"])
            task = tasks[0] if tasks else None
            if task:
                status_name = (task.get("task_status") or {}).get("name", "N/A")
                assignees = task.get("assignees", [])
                if assignees:
                    assignees_names = ", ".join([a.get("full_name", "Unknown") for a in assignees])

        edit_dir = project_root / vfs_svn / "edit"
        has_file = False
        file_name = "File not found"
        version = "N/A"

        if edit_dir.exists():
            blend_files = [f for f in glob.glob(str(edit_dir / "*.blend")) if "blend1" not in f]
            if blend_files:
                has_file = True
                blend_files.sort()
                latest_file = Path(blend_files[-1])
                file_name = latest_file.name
                match = re.search(r"(v\d+)", file_name, re.IGNORECASE)
                if match:
                    version = match.group(1).lower()

        return {
            "has_file": has_file,
            "file_name": file_name,
            "version": version,
            "assignees": assignees_names,
            "status": status_name,
        }

    def get_recent_activity(self, limit: int = 15) -> List[dict]:
        # TODO(Phase 3): implement against the ProductionRepository.
        return []

    def acknowledge_activity(self, task_id: str, comment_id: str) -> bool:
        # TODO(Phase 3): implement against the ProductionRepository.
        return True

    # ------------------------------------------------------------------
    # Project utilities / provisioning passthroughs (single Kitsu facade)
    # ------------------------------------------------------------------
    def set_host(self, host_url: str) -> None:
        self.kitsu.set_host(host_url)

    def list_templates(self) -> list:
        try:
            return self.kitsu.get_all_templates()
        except Exception as error:  # noqa: BLE001
            print(f"[ProductionService] Error fetching templates: {error}")
            return []

    def build_web_url(self, host_url: str, project_id: str, sub_path: str) -> str:
        return self.kitsu.build_web_url(host_url, project_id, sub_path)

    def delete_project(self, project_id: str) -> Tuple[bool, str]:
        return self.kitsu.delete_project(project_id)

    def download_project_thumbnail(self, project_id: str, token: str, host_url: str) -> Optional[bytes]:
        return self.kitsu.download_project_thumbnail(project_id, token, host_url)

    def seed_test_database(self, admin_email: str, admin_pwd: str) -> Tuple[bool, str]:
        return self.kitsu.seed_test_database(admin_email=admin_email, admin_pwd=admin_pwd)
