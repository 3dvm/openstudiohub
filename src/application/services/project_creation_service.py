# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/project_creation_service.py
# Architectural role: Application service / project creation saga
# =========================================================================================

"""Project creation saga.

Orchestrates: Kitsu project -> physical folder tree -> template copy ->
project_init.json blueprint -> VCS repository + initial commit.
"""

from src.domain.workspace import blueprint
from utils import _

import json
import shutil
from pathlib import Path

from src.infrastructure.dev_defaults import DEV_SVN_PASSWORD, DEV_SVN_USER
from src.infrastructure.kitsu_manager import KitsuManager
from src.infrastructure.vcs.vcs_router import VCSRouter

from src.domain.workspace.blueprint import ProjectBlueprint
from src.application.services.workspace_operations import (
    WorkspaceScaffolder,
    BlueprintGenerator,
    VCSProvisioner,
    EnvironmentPatcher
)


class ProjectCreationService:
    def __init__(self, config_factory) -> None:
        self.config_factory = config_factory
        self.base_dir = config_factory.get_workspace_root()
        #self.vault_templates_dir = config_factory.get_vault_path() / "project_templates"

    # @property
    # def base_dir(self) -> Path:
    #     return self.config_factory.get_workspace_root()
    #
    # @property
    # def vault_templates_dir(self) -> Path:
    #     return self.config_factory.get_vault_path() / "project_templates"
    #
    def create_project(
        self,
        project_name: str,
        blender_version: str,
        dependencies: dict,
        kitsu_template: str = "",
        splash_image_path: str = "",
        vcs_user: str = "",
        vcs_pwd: str = "",
        topography=None,
        vcs_enabled: bool = True
    ) -> tuple[bool, str]:

        if not project_name.strip():
            return False, _("Project name cannot be empty.")
        if not blender_version.strip():
            return False, _("You must specify a Blender version.")

        folder_name = project_name.strip().lower().replace(" ", "-")
        project_path = self.base_dir / folder_name

        if project_path.exists():
            return False, _(f"Folder '{folder_name}' already exists on the NAS.")

        kitsu = KitsuManager()

        success, kitsu_msg, kitsu_project = kitsu.create_project_from_template(
            project_name.strip(), kitsu_template
        )
        if not success:
            return False, _(f"Aborted by Kitsu: {kitsu_msg}")

        project_id = kitsu_project.get("id", "")
        # Debugging prints
        print( _(f"[ProjectCreationService] Kitsu project created. ID: {project_id}") )


        try:
            blueprint = ProjectBlueprint(
                project_name=project_name.strip(),
                kitsu_project_id=kitsu_project.get("id", ""),
                blender_version=blender_version.strip(),
                template=kitsu_template,
                dependencies=dependencies,
                topography=topography or self.config_factory.get_topography(),
                vcs_enabled=vcs_enabled
            )

            WorkspaceScaffolder.build_directories(project_path, blueprint)
            BlueprintGenerator.write_manifests(project_path, blueprint)

            if splash_image_path and Path(splash_image_path).exists():
                shutil.copy( splash_image_path, project_path / blueprint.topography.vfs_pipeline / "splash.png")
                kitsu.upload_project_splash(blueprint.kitsu_project_id, splash_image_path)

            patch_template = Path(__file__).resolve().parent.parent.parent / "infrastructure" / "templates" / "vfs_patch.py.template"
            EnvironmentPatcher.apply_vfs_patch(project_path, blueprint, patch_template)

            base_repo_url = self.config_factory.get_vcs_repository_url()
            if "localhost" in base_repo_url and not vcs_user:
                vcs_user, vcs_pwd = DEV_SVN_USER, DEV_SVN_PASSWORD

            vcs_router = VCSRouter(
                vcs_type=self.config_factory.get_vcs_adapter_type(),
                repo_url=f"{base_repo_url}/{folder_name}/{blueprint.topography.vfs_svn}",
                workspace_dir=project_path / blueprint.topography.vfs_svn
            )

            provisioner = VCSProvisioner(vcs_router, is_enabled=vcs_enabled)
            ignore_rules = [blueprint.topography.vfs_local, blueprint.topography.vfs_shared,
                            blueprint.topography.vfs_pipeline, "*.blend1", "*.blend2"] # ignore_rules must be defined at initial config, not hardcoded

            provisioner.initialize_and_commit(project_name, blueprint.topography.vfs_svn, vcs_user, vcs_pwd, ignore_rules)

            return True, _(f"Project '{folder_name}' successfully generated.")

        except Exception as error:
            import traceback
            print(_(f"\n[ProjectCreationService] CRASH FATAL:\n{traceback.format_exc()}\n"))
            return False, _(f"System error creating directory tree: {str(error)}")

        # try:
        #     vfs_svn = self.config_factory.get_vfs_svn_name()
        #     vfs_shared = self.config_factory.get_vfs_shared_name()
        #     vfs_local = self.config_factory.get_vfs_local_name()
        #     vfs_pipe = self.config_factory.get_vfs_pipeline_name()
        #     custom_dirs = self.config_factory.get_custom_dirs()
        #
        #     base_folders = [
        #         vfs_local,
        #         vfs_shared,
        #         vfs_pipe,
        #         f"{vfs_svn}/pro",
        #         f"{vfs_svn}/tools",
        #         f"{vfs_svn}/pro/assets",
        #         f"{vfs_svn}/pro/shots",
        #         f"{vfs_svn}/pro/edit",
        #         f"{vfs_svn}/pro/strips",
        #     ] + custom_dirs
        #
        #     for folder in base_folders:
        #         (project_path / folder).mkdir(parents=True, exist_ok=True)
        #
        #     template_path = self.vault_templates_dir / project_template
        #     if template_path.exists() and template_path.is_dir():
        #         for item in template_path.iterdir():
        #             if item.is_file():
        #                 shutil.copy2(item, project_path / vfs_svn)
        #             elif item.is_dir():
        #                 shutil.copytree(item, project_path / vfs_svn / item.name, dirs_exist_ok=True)
        #
        #     payload_data = {
        #         "project_name": project_name.strip(),
        #         "kitsu_project_id": project_id,
        #         "blender_version": blender_version.strip(),
        #         "kitsu_template": kitsu_template.strip(),
        #         "dependencies": dependencies,
        #         "topography_signature": {
        #             "vfs_svn": vfs_svn,
        #             "vfs_shared": vfs_shared,
        #             "vfs_local": vfs_local,
        #             "vfs_pipeline": vfs_pipe,
        #         },
        #     }
        #
        #     payload_file_svn = project_path / vfs_svn / "project_init.json"
        #     with open(payload_file_svn, "w", encoding="utf-8") as handle:
        #         json.dump(payload_data, handle, indent=4)
        #     shutil.copy2(payload_file_svn, project_path / vfs_pipe / "project_init.json")
        #
        #     if splash_image_path:
        #         splash_source = Path(splash_image_path)
        #         if splash_source.exists() and splash_source.is_file():
        #             shutil.copy(splash_source, project_path / vfs_pipe / "splash.png")
        #             kitsu.upload_project_splash(project_id, splash_image_path)
        #
        #     base_repo_url = self.config_factory.get_vcs_repository_url()
        #
        #     try:
        #         vcs_type = self.config_factory.get_vcs_adapter_type()
        #         final_repo_url = f"{base_repo_url}/{folder_name}/{vfs_svn}"
        #
        #         vcs_root = project_path / vfs_svn
        #         router = VCSRouter(vcs_type=vcs_type, repo_url=final_repo_url, workspace_dir=vcs_root)
        #         adapter = router.get_adapter()
        #
        #         if "localhost" in base_repo_url and not vcs_user:
        #             vcs_user, vcs_pwd = DEV_SVN_USER, DEV_SVN_PASSWORD
        #
        #         adapter.create_server_repository(project_name, vfs_svn)
        #
        #         if vcs_user and vcs_pwd:
        #             adapter.full_pull(username=vcs_user, password=vcs_pwd)
        #             print("[ProjectCreationService] Repositorio VCS emparejado.")
        #
        #             ignore_patterns = [vfs_local, vfs_shared, vfs_pipe, "*.blend1", "*.blend2", "quit.blend"] # The patterns should be configurable
        #             adapter.setup_ignore(ignore_patterns)
        #
        #             startup_dir = project_path / vfs_local / "blender_data" / "scripts" / "startup"
        #             startup_dir.mkdir(parents=True, exist_ok=True)
        #             patch_file = startup_dir / "00_openstudio_vfs_patch.py"
        #
        #             template_patch_path = (
        #                 Path(__file__).resolve().parent.parent.parent
        #                 / "infrastructure"
        #                 / "templates"
        #                 / "vfs_patch.py.template"
        #             )
        #             if template_patch_path.exists():
        #                 with open(template_patch_path, "r", encoding="utf-8") as t_file:
        #                     patch_content = t_file.read()
        #                 patch_content = patch_content.replace("{VFS_SVN_PLACEHOLDER}", vfs_svn)
        #                 with open(patch_file, "w", encoding="utf-8") as handle:
        #                     handle.write(patch_content)
        #                 print("[ProjectCreationService] VFS Patch applied.")
        #
        #             adapter.add_all(".")
        #             adapter.commit(
        #                 message="Initial commit: Hub Project Blueprint established.",
        #                 paths=["."],
        #                 username=vcs_user,
        #                 password=vcs_pwd,
        #             )
        #         else:
        #             print("[ProjectCreationService] No VCS credentials provided. Skipping initial commit.")
        #     except Exception as error:  # noqa: BLE001
        #         print(f"[ProjectCreationService] Warning: Initial VCS commit failed: {error}")
        #
        #     return True, f"Project '{folder_name}' successfully generated."
        #
        # except Exception as error:  # noqa: BLE001
        #     import traceback
        #
        #     print(f"\n[ProjectCreationService] CRASH FATAL:\n{traceback.format_exc()}\n")
        #     return False, f"System error creating directory tree: {str(error)}"
