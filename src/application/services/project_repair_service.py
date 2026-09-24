# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/project_repair_service.py
# Architectural role: Application service / fixes issues with faulty HubProjects
# =========================================================================================

"""Repairs faulty ``HubProject`` entities.

Two damage modes are supported:

* **NAS Ghost** — the filesystem topography exists but the Kitsu project is
  missing. The TD provides the Kitsu template to recreate the production entity
  and the existing blueprint is relinked to the new Kitsu id.

* **Kitsu Orphan** — the Kitsu project exists but the filesystem topography is
  missing. The TD provides the missing workspace data (Blender version, vault
  dependencies, template, VCS) so the topography can be rebuilt like a fresh
  creation.
"""

from pathlib import Path

from src.domain.workspace.blueprint import ProjectBlueprint
from src.application.services.addon_config_generator import AddonConfigGenerator
from src.application.services.workspace_operations import (
    WorkspaceScaffolder,
    BlueprintGenerator,
    VCSProvisioner,
)
from src.infrastructure.vcs.vcs_router import VCSRouter

class ProjectRepairService:
    def __init__(self, kitsu_manager, nas_manager, config_factory, credential_vault=None):
        self.kitsu = kitsu_manager
        self.nas = nas_manager
        self.config_factory = config_factory
        self.credential_vault = credential_vault

    def _server_profile(self):
        getter = getattr(self.config_factory, "get_vcs_server_profile", None)
        return getter() if callable(getter) else None

    def _resolve_server(self, server_id: str = ""):
        get_server = getattr(self.config_factory, "get_server", None)
        if server_id and callable(get_server):
            server = get_server(server_id)
            if server is not None:
                return server
        get_default = getattr(self.config_factory, "get_default_server", None)
        if callable(get_default):
            return get_default()
        return None

    def _ssh_passphrase_provider(self, server=None):
        if self.credential_vault is None:
            return None
        server_id = server.id if server is not None else ""
        return lambda: self.credential_vault.get_ssh_passphrase(server_id)

    # ------------------------------------------------------------------
    # NAS Ghost: filesystem exists, Kitsu project missing
    # ------------------------------------------------------------------
    def fix_nas_ghost(self, project_name: str, template_name: str = "") -> tuple[bool, str]:
        """Recreate the missing Kitsu project and relink the existing blueprint."""
        project_root = self.nas.resolve_project_dir(project_name)
        if not project_root:
            return False, f"Project folder for '{project_name}' not found on the NAS."

        raw_blueprint = self.nas.get_project_blueprint(project_root)
        blueprint = ProjectBlueprint.from_dict(raw_blueprint) if raw_blueprint else ProjectBlueprint(
            project_name=project_name,
            topography=self.config_factory.get_topography(),
        )

        success, msg, kitsu_proj = self.kitsu.create_project_from_template(project_name, template_name)
        if not success:
            return False, msg

        blueprint.kitsu_project_id = kitsu_proj.get("id", "")
        BlueprintGenerator.write_manifests(project_root, blueprint)
        AddonConfigGenerator(self.config_factory).generate(
            project_root,
            blueprint.addon_configuration,
            blueprint.topography,
        )
        return True, "NAS Ghost repaired: Kitsu project created and blueprint synced."

    # ------------------------------------------------------------------
    # Kitsu Orphan: Kitsu project exists, filesystem missing
    # ------------------------------------------------------------------
    def fix_kitsu_orphan(
        self,
        project_name: str,
        kitsu_id: str,
        blueprint: ProjectBlueprint,
        vcs_user: str,
        vcs_pwd: str,
        vcs_enabled: bool = True,
        server_id: str = "",
    ) -> tuple[bool, str]:
        """Rebuild the missing filesystem topography and initialize the VCS."""
        project_root = self.nas.resolve_project_dir(project_name)
        if not project_root:
            folder_name = project_name.strip().lower().replace(" ", "-")
            project_root = self.nas.base_dir / folder_name

        blueprint.project_name = project_name
        blueprint.kitsu_project_id = kitsu_id or blueprint.kitsu_project_id

        WorkspaceScaffolder.build_directories(project_root, blueprint)
        BlueprintGenerator.write_manifests(project_root, blueprint)
        AddonConfigGenerator(self.config_factory).generate(
            project_root,
            blueprint.addon_configuration,
            blueprint.topography,
        )

        server = self._resolve_server(server_id or blueprint.vcs_server_id)
        if server is not None:
            vcs_type, base_repo_url, profile = server.adapter, server.repository_url, server.profile
            blueprint.vcs_server_id = server.id
            blueprint.vcs_base_url = server.repository_url
        else:
            vcs_type = self.config_factory.get_vcs_adapter_type()
            base_repo_url = self.config_factory.get_vcs_repository_url()
            profile = self._server_profile()

        vfs_svn = blueprint.topography.vfs_svn
        folder_name = project_name.strip().lower().replace(" ", "-")

        vcs_router = VCSRouter(
            vcs_type=vcs_type,
            repo_url=f"{base_repo_url}/{folder_name}/{vfs_svn}",
            workspace_dir=project_root / vfs_svn,
            server_profile=profile,
            ssh_passphrase_provider=self._ssh_passphrase_provider(server),
        )

        provisioner = VCSProvisioner(vcs_router, is_enabled=vcs_enabled)
        ignore_patterns = [
            blueprint.topography.vfs_local,
            blueprint.topography.vfs_shared,
            blueprint.topography.vfs_pipeline,
            "*.blend1",
            "*.blend2",
        ]
        success, message = provisioner.initialize_and_commit(
            folder_name, vfs_svn, vcs_user, vcs_pwd, ignore_patterns
        )
        if not success:
            return False, f"Kitsu Orphan repair failed at VCS initialization: {message}"

        return True, "Kitsu Orphan repaired: NAS topography and VCS initialized."

    # ------------------------------------------------------------------
    # Missing/Invalid Blueprint: filesystem + Kitsu exist, project_init.json missing or corrupt
    # ------------------------------------------------------------------
    def fix_blueprint(
        self,
        project_name: str,
        kitsu_id: str,
        blueprint: ProjectBlueprint,
    ) -> tuple[bool, str]:
        """Regenerate the lost or corrupted ``project_init.json`` blueprint for an existing project."""
        project_root = self.nas.resolve_project_dir(project_name)
        if not project_root:
            folder_name = project_name.strip().lower().replace(" ", "-")
            project_root = self.nas.base_dir / folder_name

        blueprint.project_name = project_name
        blueprint.kitsu_project_id = kitsu_id or blueprint.kitsu_project_id

        # Rebuild any missing structural folders and regenerate the manifest.
        WorkspaceScaffolder.build_directories(project_root, blueprint)
        BlueprintGenerator.write_manifests(project_root, blueprint)

        # Keep the generated add-on startup scripts in sync with the blueprint.
        AddonConfigGenerator(self.config_factory).generate(
            project_root,
            blueprint.addon_configuration,
            blueprint.topography,
        )

        return True, "Blueprint rebuilt: project_init.json regenerated."
