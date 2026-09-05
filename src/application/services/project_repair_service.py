
# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/project_repair_service.py
# Architectural role: Application service / fixes issues with faulty HubProjects
# =========================================================================================

from src.domain.workspace.blueprint import ProjectBlueprint

class ProjectRepairService:
    def __init__(self, kitsu_manager, nas_manager, vcs_router):
        self.kitsu = kitsu_manager
        self.nas = nas_manager
        self.vcs_router = vcs_router

    def fix_nas_ghost(self, project_name: str, blender_version: str, blueprint: ProjectBlueprint) -> tuple[bool, str]:
        """Blueprint exists on file system but not on Kitsu. Missing data is provided by TD"""
        success, msg, kitsu_proj = self.kitsu.create_project_from_template(project_name)

        if not success:
            return False, msg

        blueprint.kitsu_project_id = kitsu_proj.get("id", "")
        blueprint.blender_version = blender_version

        project_root = self.nas.resolve_project_dir(project_name)
        BlueprintGenerator.write_manifests(project_root, blueprint)
        return True, "NAS Ghost repaired: Kitsu project created and blueprint synced."

    def fix_kitsu_orphan(self, project_name: str, kitsu_id: str, blueprint: ProjectBlueprint, vcs_user: str, vcs_pwd: str) -> tuple[bool, str]:
        """Project exists on Kitsu but not on the file system"""
        project_root = self.nas.base_dir / project_name.lower().replace(" ", "-")

        WorkspaceScaffolder.build_directories(project_root, blueprint)
        BlueprintGenerator.write_manifests(project_root, blueprint)

        provisioner = VCSProvisioner(self.vcs_router)
        provisioner.initialize_and_commit(project_name, blueprint.topography.vfs_svn, vcs_user, vcs_pwd)

        return True, "Kitsu Orphan repaired: NAS topography and VCS initialized."
