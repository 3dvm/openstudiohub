# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/project_audit_service.py
# Architectural role: Application service / Auditing of HubProject
# =========================================================================================

""" Checks the heatlh status of a HubProject
"""

from pathlib import Path
from src.domain.workspace.entities import HubProject, ProjectHealth
from src.domain.workspace.blueprint import ProjectBlueprint

class ProjectAuditService:
    def __init__(self, nas_manager, kitsu_manager):
        self.nas_manager = nas_manager
        self.kitsu_manager = kitsu_manager

    def audit_project(self, project_name: str, kitsu_id: str = "") -> HubProject:
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
        if project_dir:
            health.is_accessible_on_nas = True

            # 3. Blueprint Check
            raw_blueprint = self.nas_manager.get_project_blueprint(project_dir)
            if raw_blueprint:
                hub_project.blueprint = ProjectBlueprint.from_dict(raw_blueprint)
                health.has_blueprint = True

                # Check Local Install based on the blueprint's topography
                local_dir = project_dir / hub_project.blueprint.topography.vfs_local
                health.is_installed_locally = local_dir.exists()

                # Check critical folders
                for vfs_dir in [hub_project.blueprint.topography.vfs_svn,
                                hub_project.blueprint.topography.vfs_shared]:
                    if not (project_dir / vfs_dir).exists():
                        health.missing_critical_folders.append(vfs_dir)

        hub_project.health = health
        return hub_project
