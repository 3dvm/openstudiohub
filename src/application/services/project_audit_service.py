# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/project_audit_service.py
# Architectural role: Application service / Auditing of HubProject
# =========================================================================================

""" Checks the heatlh status of a HubProject
"""

import json
from pathlib import Path

from src.domain.workspace.entities import HubProject, ProjectHealth
from src.domain.workspace.blueprint import ProjectBlueprint

class ProjectAuditService:
    def __init__(self, nas_manager, kitsu_manager):
        self.nas_manager = nas_manager
        self.kitsu_manager = kitsu_manager

    def audit_project(self, project_name: str, kitsu_id: str = "") -> HubProject:

        print(f"[ProjectAuditService] Auditing project_name='{project_name}' kitsu_id='{kitsu_id}'")

        health = ProjectHealth()
        hub_project = HubProject(name=project_name)

        # 1. Kitsu Check
        if kitsu_id:
            kitsu_data = self.kitsu_manager.get_project(kitsu_id)
            if kitsu_data:
                hub_project.kitsu_info = kitsu_data
                health.has_kitsu_project = True

        # 2. NAS Check
        project_dir = self.nas_manager.resolve_project_dir(project_name)

        print(f"[ProjectAuditService] project_dir = {project_dir}")

        if project_dir:
            health.is_accessible_on_nas = True

            # 3. Blueprint Check
            status, raw_blueprint = self.nas_manager.load_project_blueprint(project_dir)

            print(f"[ProjectAuditService] blueprint status='{status}' raw_blueprint = {json.dumps(raw_blueprint, indent=2, ensure_ascii=False)}")

            health.has_blueprint = status != "missing"

            if status == "ok" and ProjectBlueprint.is_valid(raw_blueprint):
                health.has_valid_blueprint = True
                hub_project.blueprint = ProjectBlueprint.from_dict(raw_blueprint)

                print(f"[ProjectAuditService] parsed blueprint.to_dict() = {hub_project.blueprint.to_dict()}")

                # Check Local Install based on the blueprint's topography
                local_dir = project_dir / hub_project.blueprint.topography.vfs_local
                health.is_installed_locally = local_dir.exists()

                print(f"[ProjectAuditService] vfs_local -> {local_dir} exists={local_dir.exists()}")

                # Check critical folders
                for vfs_dir in [hub_project.blueprint.topography.vfs_svn,
                                hub_project.blueprint.topography.vfs_shared]:

                    full = project_dir / vfs_dir
                    print(f"[ProjectAuditService] critical -> {full} exists={full.exists()}")

                    if not (project_dir / vfs_dir).exists():
                        health.missing_critical_folders.append(vfs_dir)

                # self._debug_dump_tree(project_dir)

        hub_project.health = health
        return hub_project

    def _debug_dump_tree(self, project_dir: Path) -> None:
        print(f"[ProjectAuditService] Files found under {project_dir}:")
        for item in sorted(project_dir.rglob("*")):
            kind = "DIR " if item.is_dir() else "FILE"
            print(f"    [{kind}] {item.relative_to(project_dir)}")
