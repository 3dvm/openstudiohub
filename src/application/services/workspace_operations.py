# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/workspace_operations.py
# Architectural role: Application service / project creation saga
# =========================================================================================


import json
#import shutil
from pathlib import Path
from src.domain.workspace.blueprint import ProjectBlueprint

class WorkspaceScaffolder:
    """Creates the folder structure based only on the topography Blueprint."""

    @staticmethod
    def build_directories(project_root: Path, blueprint: ProjectBlueprint) -> bool:

        try:
            folders_to_create = blueprint.topography.base_folders()

            for folder in folders_to_create:
                (project_root / folder).mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            print(f"[Scaffolder] Error: {e}")
            return False

class BlueprintGenerator:
    """Write/overwrites the JSON manifest."""

    @staticmethod
    def write_manifests(project_root: Path, blueprint: ProjectBlueprint) -> bool:
        try:
            vfs_pipe = blueprint.topography.vfs_pipeline
            payload = blueprint.to_dict()


            manifest_file = project_root / vfs_pipe / "project_init.json"
            manifest_file.parent.mkdir(parents=True, exist_ok=True)

            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=4)

            return True
        except Exception as e:
            print(f"[BlueprintGenerator] Error: {e}")
            return False


class EnvironmentPatcher:
    """This is not being used currently. Will verify if it's really needed."""
    @staticmethod
    def apply_vfs_patch(project_root: Path, blueprint: ProjectBlueprint, template_path: Path) -> bool:
        try:
            startup_dir = project_root / blueprint.topography.vfs_local / "blender_data" / "scripts" / "startup"
            startup_dir.mkdir(parents=True, exist_ok=True)

            if template_path.exists():
                with open(template_path, "r", encoding="utf-8") as t_file:
                    content = t_file.read()

                content = content.replace("{VFS_SVN_PLACEHOLDER}", blueprint.topography.vfs_svn)

                with open(startup_dir / "00_openstudio_vfs_patch.py", "w", encoding="utf-8") as f:
                    f.write(content)
            return True
        except Exception as e:
            print(f"[EnvironmentPatcher] Error: {e}")
            return False


class VCSProvisioner:
    """Initialazes and makes the first commit of the VCS when enabled."""

    def __init__(self, vcs_router, is_enabled: bool = True):
        self.vcs_router = vcs_router
        self.is_enabled = is_enabled

    def initialize_and_commit(self, project_name: str, vfs_svn: str, username: str, password: str, ignore_patterns: list) -> bool:
        if not self.is_enabled:
            print("[VCSProvisioner] Version Control is disabled (NAS only). Skipping VCS initialization.")
            return True

        try:

            adapter = self.vcs_router.get_adapter()
            adapter.create_server_repository(project_name, vfs_svn)
            adapter.full_pull(username, password)
            adapter.setup_ignore(ignore_patterns)
            adapter.add_all(".")
            adapter.commit("Initial Blueprint commit.", ["."], username, password)

            return True
        except Exception as e:
            print(f"[VCSProvisioner] Error: {e}")
            return False
