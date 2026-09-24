# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/project_creation_service.py
# Architectural role: Application service / project creation saga
# =========================================================================================

"""Resumable project creation saga.

Orchestrates: server pre-flight -> Kitsu project -> physical folder tree ->
``project_init.json`` blueprint -> VCS repository + initial commit.

Every step is recorded in a :class:`CreationContext` so a failed step can be
retried without re-running the steps that already succeeded, and so the created
data can be rolled back on demand.
"""

import shutil
from pathlib import Path

from utils import _

from src.infrastructure.dev_defaults import DEV_SVN_PASSWORD, DEV_SVN_USER
from src.infrastructure.kitsu_manager import KitsuManager
from src.infrastructure.nas_manager import NasManager
from src.infrastructure.vcs.vcs_router import VCSRouter

from src.domain.shared_kernel.addon_contract import (
    default_addon_configuration,
    parse_addon_configuration,
)
from src.domain.workspace.blueprint import ProjectBlueprint
from src.application.services.creation_saga import (
    CreationContext,
    CreationOutcome,
    CreationStep,
    StageError,
)
from src.application.services.workspace_operations import (
    WorkspaceScaffolder,
    BlueprintGenerator,
    VCSProvisioner,
    EnvironmentPatcher,
)


class ProjectCreationService:
    def __init__(self, config_factory, kitsu_manager=None, nas_manager=None, credential_vault=None) -> None:
        self.config_factory = config_factory
        self._kitsu = kitsu_manager or KitsuManager()
        self._nas = nas_manager or NasManager(config_factory=config_factory)
        self.credential_vault = credential_vault

    # ------------------------------------------------------------------
    # Remote-server helpers
    # ------------------------------------------------------------------
    def _server_profile(self):
        getter = getattr(self.config_factory, "get_vcs_server_profile", None)
        return getter() if callable(getter) else None

    def _ssh_passphrase_provider(self):
        if self.credential_vault is None:
            return None
        return self.credential_vault.get_ssh_passphrase

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
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
        vcs_enabled: bool = True,
        addon_configuration: dict | None = None,
    ) -> CreationOutcome:

        if not project_name.strip():
            return self._validation_failure(_("Project name cannot be empty."))
        if not blender_version.strip():
            return self._validation_failure(_("You must specify a Blender version."))

        folder_name = self._folder_name(project_name)
        project_path = self.config_factory.get_workspace_root() / folder_name

        if project_path.exists():
            return CreationOutcome(
                success=False,
                message=_(f"Folder '{folder_name}' already exists on the NAS."),
                failed_step="folder_exists",
                can_retry=False,
                can_rollback=False,
            )

        context = self._build_context(
            project_name=project_name.strip(),
            folder_name=folder_name,
            project_path=project_path,
            blender_version=blender_version,
            dependencies=dependencies,
            kitsu_template=kitsu_template,
            splash_image_path=splash_image_path,
            vcs_user=vcs_user,
            vcs_pwd=vcs_pwd,
            topography=topography,
            vcs_enabled=vcs_enabled,
            addon_configuration=addon_configuration,
        )
        return self._run(context)

    def retry(self, context: CreationContext) -> CreationOutcome:
        """Resume a failed creation, skipping the steps already completed."""
        if context is None:
            return CreationOutcome(
                success=False,
                message=_("Nothing to retry."),
                can_retry=False,
                can_rollback=False,
            )
        return self._run(context)

    def rollback(self, context: CreationContext) -> tuple[bool, str]:
        """Best-effort deletion of everything created for a failed project."""
        if context is None:
            return False, _("Nothing to delete.")

        reports: list[str] = []
        ok = True

        if context.kitsu_project_id:
            deleted, message = self._kitsu.delete_project(context.kitsu_project_id)
            ok = ok and deleted
            reports.append(message)

        if context.vcs_enabled:
            try:
                deleted, message = VCSRouter.destroy_repository(
                    self.config_factory.get_vcs_adapter_type(),
                    self.config_factory.get_vcs_repository_url(),
                    context.folder_name,
                    context.blueprint.topography.vfs_svn,
                    server_profile=self._server_profile(),
                    ssh_passphrase_provider=self._ssh_passphrase_provider(),
                )
                ok = ok and deleted
                reports.append(message)
            except Exception as error:  # noqa: BLE001
                ok = False
                reports.append(_(f"Failed to delete the VCS repository: {error}"))

        if context.project_path and context.project_path.exists():
            if self._nas.delete_project_folder(context.project_path):
                reports.append(_("NAS workspace folder deleted."))
            else:
                ok = False
                reports.append(_("Failed to delete the NAS workspace folder."))

        return ok, " ".join(reports) if reports else _("Nothing to delete.")

    # ------------------------------------------------------------------
    # Saga execution
    # ------------------------------------------------------------------
    def _run(self, context: CreationContext) -> CreationOutcome:
        steps = [
            (CreationStep.PREFLIGHT_KITSU, self._preflight_kitsu),
            (CreationStep.PREFLIGHT_VCS, self._preflight_vcs),
            (CreationStep.KITSU, self._step_kitsu),
            (CreationStep.SCAFFOLD, self._step_scaffold),
            (CreationStep.MANIFESTS, self._step_manifests),
            (CreationStep.SPLASH, self._step_splash),
            (CreationStep.VFS_PATCH, self._step_vfs_patch),
            (CreationStep.VCS, self._step_vcs),
        ]

        current = CreationStep.PREFLIGHT_KITSU
        try:
            for step, run_step in steps:
                current = step
                run_step(context)

            return CreationOutcome(
                success=True,
                message=_(f"Project '{context.folder_name}' successfully generated."),
                context=context,
            )
        except StageError as error:
            return self._failure_outcome(error.step, error.message, context)
        except Exception as error:  # noqa: BLE001
            import traceback

            print(_(f"\n[ProjectCreationService] CRASH FATAL:\n{traceback.format_exc()}\n"))
            return self._failure_outcome(current, str(error), context)

    def _preflight_kitsu(self, context: CreationContext) -> None:
        if context.is_done(CreationStep.PREFLIGHT_KITSU):
            return
        online, message = self._kitsu.check_health()
        if not online:
            raise StageError(CreationStep.PREFLIGHT_KITSU, message)
        context.mark_done(CreationStep.PREFLIGHT_KITSU)

    def _preflight_vcs(self, context: CreationContext) -> None:
        if not context.vcs_enabled or context.is_done(CreationStep.PREFLIGHT_VCS):
            return

        base_repo_url = self.config_factory.get_vcs_repository_url()
        if not base_repo_url:
            raise StageError(
                CreationStep.PREFLIGHT_VCS,
                _("VCS repository URL is not configured."),
            )
        online, message = VCSRouter.probe_health(
            self.config_factory.get_vcs_adapter_type(),
            base_repo_url,
            context.vcs_user,
            context.vcs_pwd,
            server_profile=self._server_profile(),
            ssh_passphrase_provider=self._ssh_passphrase_provider(),
        )
        if not online:
            raise StageError(CreationStep.PREFLIGHT_VCS, message)
        context.mark_done(CreationStep.PREFLIGHT_VCS)

    def _step_kitsu(self, context: CreationContext) -> None:
        if context.is_done(CreationStep.KITSU):
            return

        success, kitsu_msg, kitsu_project = self._kitsu.create_project_from_template(
            context.project_name, context.blueprint.template
        )
        if not success:
            existing = self._kitsu.get_project_by_name(context.project_name)
            if existing:
                print(f"[ProjectCreationService] Reusing existing Kitsu project '{context.project_name}'.")
                kitsu_project = existing
            else:
                raise StageError(CreationStep.KITSU, _(f"Aborted by Kitsu: {kitsu_msg}"))

        context.kitsu_project_id = kitsu_project.get("id", "")
        context.blueprint.kitsu_project_id = context.kitsu_project_id
        print(f"[ProjectCreationService] Kitsu project ready. ID: {context.kitsu_project_id}")
        context.mark_done(CreationStep.KITSU)

    def _step_scaffold(self, context: CreationContext) -> None:
        if context.is_done(CreationStep.SCAFFOLD):
            return
        if not WorkspaceScaffolder.build_directories(context.project_path, context.blueprint):
            raise StageError(CreationStep.SCAFFOLD, _("Failed to create the workspace folder tree."))
        context.mark_done(CreationStep.SCAFFOLD)

    def _step_manifests(self, context: CreationContext) -> None:
        if context.is_done(CreationStep.MANIFESTS):
            return
        if not BlueprintGenerator.write_manifests(context.project_path, context.blueprint):
            raise StageError(CreationStep.MANIFESTS, _("Failed to write project_init.json."))
        context.mark_done(CreationStep.MANIFESTS)

    def _step_splash(self, context: CreationContext) -> None:
        if context.is_done(CreationStep.SPLASH):
            return
        splash_path = context.splash_image_path
        if splash_path and Path(splash_path).exists():
            shutil.copy(
                splash_path,
                context.project_path / context.blueprint.topography.vfs_pipeline / "splash.png",
            )
            self._kitsu.upload_project_splash(context.kitsu_project_id, splash_path)
        context.mark_done(CreationStep.SPLASH)

    def _step_vfs_patch(self, context: CreationContext) -> None:
        if context.is_done(CreationStep.VFS_PATCH):
            return
        patch_template = (
            Path(__file__).resolve().parent.parent.parent
            / "infrastructure"
            / "templates"
            / "vfs_patch.py.template"
        )
        if not EnvironmentPatcher.apply_vfs_patch(context.project_path, context.blueprint, patch_template):
            raise StageError(CreationStep.VFS_PATCH, _("Failed to apply the VFS patch."))
        context.mark_done(CreationStep.VFS_PATCH)

    def _step_vcs(self, context: CreationContext) -> None:
        if context.is_done(CreationStep.VCS):
            return

        if not context.vcs_enabled:
            context.mark_done(CreationStep.VCS)
            return

        base_repo_url = self.config_factory.get_vcs_repository_url()
        if "localhost" in base_repo_url and not context.vcs_user:
            context.vcs_user, context.vcs_pwd = DEV_SVN_USER, DEV_SVN_PASSWORD

        online, message = VCSRouter.probe_health(
            self.config_factory.get_vcs_adapter_type(),
            base_repo_url,
            context.vcs_user,
            context.vcs_pwd,
            server_profile=self._server_profile(),
            ssh_passphrase_provider=self._ssh_passphrase_provider(),
        )
        if not online:
            raise StageError(CreationStep.VCS, message)

        router = self._build_router(context)
        provisioner = VCSProvisioner(router, is_enabled=context.vcs_enabled)
        success, message = provisioner.initialize_and_commit(
            context.folder_name,
            context.blueprint.topography.vfs_svn,
            context.vcs_user,
            context.vcs_pwd,
            context.ignore_rules,
        )
        if not success:
            raise StageError(CreationStep.VCS, message)

        context.mark_done(CreationStep.VCS)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_context(
        self,
        project_name: str,
        folder_name: str,
        project_path: Path,
        blender_version: str,
        dependencies: dict,
        kitsu_template: str,
        splash_image_path: str,
        vcs_user: str,
        vcs_pwd: str,
        topography,
        vcs_enabled: bool,
        addon_configuration: dict | None,
    ) -> CreationContext:
        if addon_configuration is None:
            parsed_addon_config = default_addon_configuration(dependencies)
        else:
            parsed_addon_config = parse_addon_configuration(addon_configuration)

        blueprint = ProjectBlueprint(
            project_name=project_name,
            kitsu_project_id="",
            blender_version=blender_version.strip(),
            template=kitsu_template,
            dependencies=dependencies,
            addon_configuration=parsed_addon_config,
            topography=topography or self.config_factory.get_topography(),
            vcs_enabled=vcs_enabled,
            vcs_base_url=self.config_factory.get_vcs_repository_url(),
        )

        ignore_rules = [
            blueprint.topography.vfs_local,
            blueprint.topography.vfs_shared,
            blueprint.topography.vfs_pipeline,
            "*.blend1",
            "*.blend2",
        ]

        context = CreationContext(
            project_name=project_name,
            folder_name=folder_name,
            project_path=project_path,
            blueprint=blueprint,
            vcs_user=vcs_user,
            vcs_pwd=vcs_pwd,
            vcs_enabled=vcs_enabled,
            splash_image_path=splash_image_path,
            ignore_rules=ignore_rules,
        )
        return context

    def _build_router(self, context: CreationContext) -> VCSRouter:
        base_repo_url = self.config_factory.get_vcs_repository_url()
        return VCSRouter(
            vcs_type=self.config_factory.get_vcs_adapter_type(),
            repo_url=f"{base_repo_url}/{context.folder_name}/{context.blueprint.topography.vfs_svn}",
            workspace_dir=context.project_path / context.blueprint.topography.vfs_svn,
            server_profile=self._server_profile(),
            ssh_passphrase_provider=self._ssh_passphrase_provider(),
        )

    def _failure_outcome(self, step: CreationStep, message: str, context: CreationContext) -> CreationOutcome:
        has_side_effects = context.has_side_effects
        return CreationOutcome(
            success=False,
            message=message,
            failed_step=step.value,
            has_side_effects=has_side_effects,
            can_retry=True,
            can_rollback=has_side_effects
            and (bool(context.kitsu_project_id) or context.project_path.exists()),
            context=context,
        )

    @staticmethod
    def _validation_failure(message: str) -> CreationOutcome:
        return CreationOutcome(
            success=False,
            message=message,
            failed_step="validation",
            can_retry=False,
            can_rollback=False,
        )

    @staticmethod
    def _folder_name(project_name: str) -> str:
        return project_name.strip().lower().replace(" ", "-")
