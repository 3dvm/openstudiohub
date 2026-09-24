# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/project_list_viewmodel.py
# Architectural role: MVVM ViewModel / project grid
# =========================================================================================

"""ViewModel for the project list.

Owns the project catalog, computes each project's filesystem status, and
orchestrates install / launch / delete. Navigation to Kitsu and Watchtower is
delegated to shell callbacks injected at construction time.
"""

from os import error
from pathlib import Path
from typing import Callable, List, Optional
import json
import queue
import shutil

from PySide6.QtCore import QTimer, Signal

from src.application.services.auth_service import AuthService
from src.application.services.installation_service import InstallationService
from src.application.services.production_service import ProductionService
from src.application.services.project_audit_service import ProjectAuditService
from src.application.services.task_file_sync_service import TaskFileSyncService
from src.application.services.vcs_migration_service import VCSMigrationService
from src.domain.shared_kernel.addon_contract import ADDON_CONFIGURATION_KEY
from src.domain.workspace.entities import (
    ERROR_INVALID_BLUEPRINT,
    ERROR_KITSU_ORPHAN,
    ERROR_MISSING_BLUEPRINT,
    ERROR_NAS_GHOST,
)
from src.infrastructure.nas_manager import NasManager
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.viewmodels.vcs_credential_gate import (
    VcsPrompt,
    ensure_vcs_credentials,
    vcs_requires_credentials,
)
from src.interfaces.qt.workers.kitsu_migration_workers import (
    KitsuCheckoutWorker,
    KitsuCreatePersonWorker,
    KitsuExportEstimateWorker,
    KitsuExportWorker,
    KitsuImportInspectWorker,
    KitsuImportRepoProbeWorker,
    KitsuImportWorker,
    KitsuRollbackWorker,
)
from src.interfaces.qt.workers.artist_workers import (
    CheckVcsChangesWorker,
    PublishVcsChangesWorker,
)
from src.interfaces.qt.workers.project_list_workers import (
    ProjectGridWorker,
    ResetWorkingCopyWorker,
)
from src.interfaces.qt.workers.vcs_migration_workers import (
    VCSLocalCleanupWorker,
    VCSMigrationWorker,
)
from src.interfaces.qt.workers.worker_manager import WorkerManager


class ProjectListViewModel(BaseViewModel):
    projects_loaded = Signal(list)  # list[dict] raw project data
    refresh_requested = Signal()
    install_finished = Signal(object, bool, str)  # (project_dir, success, message)
    delete_warning = Signal(str)
    delete_completed = Signal(str)
    migration_finished = Signal(str, bool, str)
    migration_started = Signal(str, dict, dict)  # (project_name, source, target)
    migration_detail = Signal(dict)
    migration_log = Signal(str)
    migration_phase = Signal(str)
    cleanup_finished = Signal(str, bool, str)

    # Kitsu project export
    export_estimate_ready = Signal(dict)
    export_phase = Signal(str)
    export_log = Signal(str)
    export_progress = Signal(int)
    export_finished = Signal(str, bool, str)
    export_uncommitted_found = Signal(str, list)  # (project_name, list[FileChange])

    # Manual VCS publish (project card)
    publish_changes_ready = Signal(str, list)  # (project_name, list[FileChange])
    publish_up_to_date = Signal(str)  # project_name
    vcs_publish_finished = Signal(str, bool, str)  # (task_id, success, message)

    # Reset VCS working copy (project card)
    reset_finished = Signal(str, bool, str)  # (project_name, success, message)

    # Kitsu project import
    import_plan_ready = Signal(object, list)  # (ImportPlan, target persons)
    import_repo_status = Signal(dict)
    import_conflict = Signal(str)
    import_person_created = Signal(object, object)
    import_person_failed = Signal(str)
    import_phase = Signal(str)
    import_log = Signal(str)
    import_progress = Signal(int)
    import_finished = Signal(object)  # ImportReport
    checkout_finished = Signal(bool, str)
    rollback_finished = Signal(bool, str)

    def __init__(
        self,
        production_service: ProductionService,
        auth_service: AuthService,
        config_factory,
        installation_service: InstallationService,
        audit_service: ProjectAuditService,
        read_vcs_credentials: bool,
        nas_dir: Path,
        open_kitsu_callback: Callable[[str], None],
        open_watchtower_callback: Callable[[Path], None],
        instance_lock_callback: Callable[[bool], None] | None = None,
        status_sink: StatusSink | None = None,
        credential_vault=None,
        vcs_prompt: VcsPrompt | None = None,
        ssh_passphrase_prompt: Callable[[str], Optional[str]] | None = None,
        export_service=None,
        import_service=None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.production_service = production_service
        self.auth_service = auth_service
        self.config_factory = config_factory
        self.installation_service = installation_service
        self.read_vcs_credentials = read_vcs_credentials
        self.nas_dir = nas_dir
        self.open_kitsu_callback = open_kitsu_callback
        self.open_watchtower_callback = open_watchtower_callback
        self.instance_lock_callback = instance_lock_callback or (lambda _active: None)
        self.audit_service = audit_service
        self.credential_vault = credential_vault
        self.vcs_prompt = vcs_prompt
        self.ssh_passphrase_prompt = ssh_passphrase_prompt
        self.export_service = export_service
        self.import_service = import_service

        self.nas_manager = NasManager(self.nas_dir)
        self.sync_service = TaskFileSyncService(self.config_factory)
        self._pending_export: Optional[tuple] = None
        self._migration_events: "queue.Queue" = queue.Queue()
        self.migration_service = VCSMigrationService(
            self.config_factory,
            credential_vault=self.credential_vault,
            status_callback=self.report_status,
            progress_callback=self.report_progress,
            event_sink=self._migration_events,
        )
        self._migration_source_servers: dict = {}
        self._migration_target_servers: dict = {}
        self._migration_timer = QTimer(self)
        self._migration_timer.setInterval(200)
        self._migration_timer.timeout.connect(self._drain_migration_events)

        # Export/import event queues drained on the main thread.
        self._export_events: "queue.Queue" = queue.Queue()
        self._export_timer = QTimer(self)
        self._export_timer.setInterval(200)
        self._export_timer.timeout.connect(self._drain_export_events)
        self._import_events: "queue.Queue" = queue.Queue()
        self._import_timer = QTimer(self)
        self._import_timer.setInterval(200)
        self._import_timer.timeout.connect(self._drain_import_events)
        self._import_plan = None
        self._import_report = None
        self._import_options: dict = {}
        self._projects: List[dict] = []
        self.workers = WorkerManager(self)
        self._refresh_pending = False

        if self.export_service is None:
            self.export_service = self._build_export_service()
        if self.import_service is None:
            self.import_service = self._build_import_service()

    # ------------------------------------------------------------------
    # Service builders (used when not injected by the composition root)
    # ------------------------------------------------------------------
    def _build_export_service(self):
        from src.application.services.kitsu_export_service import KitsuExportService

        try:
            from _version import __version__
        except Exception:  # noqa: BLE001
            __version__ = ""
        return KitsuExportService(
            getattr(self.production_service, "kitsu", None),
            config_factory=self.config_factory,
            credential_vault=self.credential_vault,
            app_version=__version__,
            status_callback=self.report_status,
            progress_callback=self.report_progress,
            event_sink=self._export_events,
        )

    def _build_import_service(self):
        from src.application.services.kitsu_import_service import KitsuImportService

        try:
            from _version import __version__
        except Exception:  # noqa: BLE001
            __version__ = ""
        return KitsuImportService(
            getattr(self.production_service, "kitsu", None),
            config_factory=self.config_factory,
            credential_vault=self.credential_vault,
            nas_manager=self.nas_manager,
            installation_service=self.installation_service,
            app_version=__version__,
            status_callback=self.report_status,
            progress_callback=self.report_progress,
            event_sink=self._import_events,
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @property
    def user_role(self) -> str:
        return self.auth_service.current_role().value

    @property
    def token(self) -> str:
        return self.auth_service.access_token()

    @property
    def host(self) -> str:
        return self.auth_service.host

    def refresh(self) -> None:
        if self.workers.is_running("grid"):
            self._refresh_pending = True
            return

        self.report_status("Syncing projects catalog...", "yellow")
        self._projects = []

        worker = ProjectGridWorker(self.production_service)
        worker.data_ready.connect(self._on_projects_fetched)
        self.workers.start("grid", worker, on_finished=self._on_grid_worker_finished)

    def _on_grid_worker_finished(self) -> None:
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()

    def _on_projects_fetched(self, projects: list) -> None:
        self._projects = projects
        if not projects:
            self.report_status("No active projects found.", "yellow")
        else:
            self.report_status(f"🟢 Synchronized: {len(projects)} active projects.", "green")
        self.projects_loaded.emit(projects)

    def compute_status(self, project_data: dict) -> dict:
        """Resolve the filesystem-backed status rendered by a project card.

        Synchronous convenience wrapper kept for tests and any synchronous
        caller. The grid uses the asynchronous audit flow instead.
        """
        project_name = project_data.get("name", "")
        project_id = project_data.get("id", "")
        hub_project = self.audit_service.audit_project(project_name, project_id)
        return self.status_from_hub_project(project_name, hub_project)

    def status_from_hub_project(self, project_name: str, hub_project) -> dict:
        """Flatten an audited ``HubProject`` into the plain status dict the card renders."""
        health = hub_project.health

        is_corrupted = False
        error_type = None
        error_code = None

        if health.is_accessible_on_nas and not health.has_kitsu_project:
            is_corrupted = True
            error_type = "Missing Kitsu project"
            error_code = ERROR_NAS_GHOST
        elif health.has_kitsu_project and not health.is_accessible_on_nas:
            is_corrupted = True
            error_type = "Kitsu Orphan"
            error_code = ERROR_KITSU_ORPHAN
        elif health.is_accessible_on_nas and health.has_kitsu_project and not health.has_blueprint:
            is_corrupted = True
            error_type = "Missing blueprint (project_init.json)"
            error_code = ERROR_MISSING_BLUEPRINT
        elif health.is_accessible_on_nas and health.has_kitsu_project and not health.has_valid_blueprint:
            is_corrupted = True
            error_type = "Invalid blueprint (project_init.json)"
            error_code = ERROR_INVALID_BLUEPRINT

        project_dir = self.nas_manager.resolve_project_dir(project_name)
        is_installed = health.is_installed_locally if health.has_valid_blueprint else False

        status = {
            "project_dir": project_dir,
            "is_installed": is_installed,
            "is_corrupted": is_corrupted,
            "error_type": error_type,
            "error_code": error_code,
            "badge_text": "Not Mounted",
            "sync_text": "🗄️ ⚪ Cloud Only",
        }

        if is_installed and project_dir and health.has_valid_blueprint:
            status["badge_text"] = hub_project.blueprint.blender_version
            status["sync_text"] = "🟢 Ready on Disk"

        return status

    def thumbnail_fetcher(self, project_id: str, token: str, host: str) -> Optional[bytes]:
        return self.production_service.download_project_thumbnail(project_id, token, host)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def _resolve_server(self, project_dir: Path | None = None):
        getter = getattr(self.config_factory, "get_server_for_project", None)
        if callable(getter) and project_dir:
            try:
                return getter(project_dir)
            except Exception:  # noqa: BLE001
                return None
        getter = getattr(self.config_factory, "get_default_server", None)
        return getter() if callable(getter) else None

    def server_for_project(self, project_dir: Path | None = None) -> Optional[dict]:
        """Return the project's currently bound server as a plain dict."""
        server = self._resolve_server(project_dir)
        return server.to_dict() if server is not None else None

    def _ensure_target_passphrase(self, target) -> None:
        """Collect the target server's SSH passphrase when it is remote and missing."""
        if target is None or not getattr(target, "is_remote", False):
            return
        if self.credential_vault is None or self.credential_vault.has_ssh_passphrase(target.id):
            return
        if self.ssh_passphrase_prompt is None:
            return
        passphrase = self.ssh_passphrase_prompt(target.name)
        if passphrase:
            self.credential_vault.save_ssh_passphrase(target.id, passphrase)

    def _ensure_vcs_credentials(self, project_dir: Path | None = None) -> Optional[tuple[str, str]]:
        """Gate VCS-backed actions behind the per-server session credentials prompt."""
        server = self._resolve_server(project_dir)
        return ensure_vcs_credentials(
            required=vcs_requires_credentials(self.config_factory, server=server),
            server_id=server.id if server is not None else "",
            server_label=server.name if server is not None else "default",
            needs_passphrase=bool(server is not None and server.is_remote),
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )

    def install_project(self, project_dir: Path) -> None:
        if self.workers.is_running("install"):
            self.report_status("Please wait, an installation is already running...", "red")
            return

        creds = self._ensure_vcs_credentials(project_dir)
        if creds is None:
            return
        vcs_user, vcs_pwd = creds

        worker = self._build_install_worker(project_dir, vcs_user, vcs_pwd)
        worker.progress_update.connect(self.report_status)
        worker.progress.connect(self.report_progress)
        worker.finished_install.connect(
            lambda success, msg, p=project_dir: self._on_install_finished(p, success, msg)
        )
        self.workers.start("install", worker, critical=True)

    def _build_install_worker(self, project_dir: Path, vcs_user: str, vcs_pwd: str):
        from src.interfaces.qt.workers.project_list_workers import ProjectInstallWorker

        return ProjectInstallWorker(self.installation_service, project_dir, vcs_user, vcs_pwd, self.user_role)

    def _on_install_finished(self, project_dir: Path, success: bool, message: str) -> None:
        self.install_finished.emit(project_dir, success, message)
        if success:
            self.report_status("✓ Workspace deployed", "green")
            self.report_progress(100)
            self.refresh_requested.emit()
        else:
            self.report_status(f"✗ Install Failed: {message}", "red")
            self.clear_progress()
        QTimer.singleShot(2500, self.clear_progress)

    def launch_project(self, project_dir: Path) -> None:
        config_path = project_dir / "local" / "project_config.json"
        if not config_path.exists():
            self.report_status("Error: config missing.", "red")
            return

        creds = self._ensure_vcs_credentials(project_dir)
        if creds is None:
            return

        try:
            import json
            import subprocess

            with open(config_path, "r", encoding="utf-8") as handle:
                local_config = json.load(handle)
            blender_version = local_config.get("blender_version", "")

            os_name, _ = self.installation_service._get_os_info()
            blender_folder = self.installation_service.boveda_blender / f"blender-{blender_version}-{os_name}-x64"

            if os_name == "windows":
                blender_bin = blender_folder / "blender.exe"
            elif os_name == "macos":
                blender_bin = blender_folder / "Blender.app" / "Contents" / "MacOS" / "Blender"
            else:
                blender_bin = blender_folder / "blender"

            if not blender_bin.exists():
                self.report_status("Blender not found.", "red")
                return

            self.report_status("🚀 Launching Blender...", "green")
            subprocess.Popen([str(blender_bin), "--", "--project_root", str(project_dir)])
            self.instance_lock_callback(True)
        except Exception as error:  # noqa: BLE001
            self.report_status(f"Failed to launch: {str(error)}", "red")

    def target_topography(self) -> dict:
        """The target machine's topography, used as the read-only import mapping."""
        try:
            topography = self.config_factory.get_topography()
        except Exception:  # noqa: BLE001
            return {}
        if topography is None:
            return {}
        return {
            "vfs_svn": getattr(topography, "vfs_svn", "svn"),
            "vfs_shared": getattr(topography, "vfs_shared", "shared"),
            "vfs_local": getattr(topography, "vfs_local", "local"),
            "vfs_pipeline": getattr(topography, "vfs_pipeline", "pipeline"),
            "custom_dirs": list(getattr(topography, "custom_dirs", ()) or ()),
        }

    def list_servers(self) -> list:
        registry = self.config_factory.get_vcs_servers()
        return [
            {**server.to_dict(), "is_default": server.id == registry.default_server_id}
            for server in registry.servers
        ]

    # ------------------------------------------------------------------
    # Per-project configuration (HubProject config dialog)
    # ------------------------------------------------------------------
    def project_config(self, project_name: str, project_id: str = "") -> dict:
        """Gather the editable/read-only data the config dialog renders.

        Returns the raw blueprint plus the resolved VCS binding and the current
        splash path. Kept UI-agnostic so the dialog stays a passive view.
        """
        project_dir = self.nas_manager.resolve_project_dir(project_name)
        blueprint: dict = {}
        if project_dir:
            status, raw = self.nas_manager.load_project_blueprint(project_dir)
            if status == "ok" and isinstance(raw, dict):
                blueprint = raw

        server = None
        try:
            server = self._resolve_server(project_dir)
        except Exception:  # noqa: BLE001
            server = None

        pipeline_getter = getattr(self.config_factory, "get_vfs_pipeline_name", None)
        vfs_pipeline = (blueprint.get("topography_signature") or {}).get("vfs_pipeline") or (
            pipeline_getter() if callable(pipeline_getter) else "pipeline"
        )
        splash_path = ""
        if project_dir and vfs_pipeline:
            candidate = project_dir / vfs_pipeline / "splash.png"
            if candidate.exists():
                splash_path = str(candidate)

        try:
            servers = self.list_servers()
        except Exception:  # noqa: BLE001
            servers = []

        return {
            "project_name": project_name,
            "project_id": project_id,
            "project_dir": project_dir,
            "is_mounted": project_dir is not None,
            "blueprint": blueprint,
            "servers": servers,
            "bound_server_id": server.id if server is not None else "",
            "splash_path": splash_path,
            "vfs_pipeline": vfs_pipeline,
        }

    def probe_project_vcs(self, server_id: str, project_name: str) -> tuple[bool, str]:
        """Check the target server hosts this project's repository topography."""
        server = None
        getter = getattr(self.config_factory, "get_server", None)
        if server_id and callable(getter):
            server = getter(server_id)
        self._ensure_target_passphrase(server)
        try:
            return self.migration_service.probe_repository_topography(server, project_name)
        except Exception as error:  # noqa: BLE001
            return False, f"VCS probe failed: {error}"

    def save_project_config(self, project_dir, project_id: str, payload: dict) -> tuple[bool, str]:
        """Persist the dialog payload into ``project_init.json`` (+ splash/Kitsu).

        Unknown blueprint keys are preserved by editing the raw JSON in place.
        Returns ``(success, message)``.
        """
        payload = payload or {}
        if not project_dir:
            return False, "The project is not mounted on the NAS; nothing to update."
        project_dir = Path(project_dir)

        splash_source = payload.get("splash_source_path") or ""
        if splash_source and not Path(splash_source).is_file():
            return False, "The selected splash image does not exist."

        blueprint_path = self.nas_manager.get_project_blueprint_path(project_dir)
        if blueprint_path is None:
            return False, "The project has no project_init.json to update."

        try:
            with open(blueprint_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as error:  # noqa: BLE001
            return False, f"Could not read the blueprint: {error}"
        if not isinstance(data, dict):
            return False, "The blueprint is not a valid object."

        # VCS binding
        server_id = str(payload.get("server_id", "") or "")
        if server_id:
            getter = getattr(self.config_factory, "get_server", None)
            server = getter(server_id) if callable(getter) else None
            if server is None:
                return False, f"VCS server '{server_id}' was not found."
            data["vcs_server_id"] = server.id
            data["vcs_base_url"] = server.repository_url
        else:
            data["vcs_server_id"] = ""
            data["vcs_base_url"] = ""

        # Core blueprint fields
        if "blender_version" in payload:
            data["blender_version"] = str(payload.get("blender_version") or "")
        if "template" in payload:
            data["template"] = str(payload.get("template") or "")
        if "dependencies" in payload and isinstance(payload.get("dependencies"), dict):
            data["dependencies"] = payload["dependencies"]
        if "addon_configuration" in payload and isinstance(payload.get("addon_configuration"), dict):
            data[ADDON_CONFIGURATION_KEY] = payload["addon_configuration"]

        try:
            with open(blueprint_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=4)
        except Exception as error:  # noqa: BLE001
            return False, f"Could not write the blueprint: {error}"

        # Regenerate the add-on config scripts so changes apply on next launch.
        try:
            from src.application.services.addon_config_generator import AddonConfigGenerator
            from src.domain.shared_kernel.addon_contract import parse_addon_configuration
            from src.domain.workspace.blueprint import ProjectBlueprint

            blueprint = ProjectBlueprint.from_dict(data)
            AddonConfigGenerator(self.config_factory).generate(
                project_dir, blueprint.addon_configuration, blueprint.topography
            )
        except Exception as error:  # noqa: BLE001
            self.report_status(f"Add-on config regeneration skipped: {error}", "yellow")

        # Splash screen: copy into the pipeline folder and mirror it on Kitsu.
        splash_note = ""
        if splash_source:
            try:
                source = Path(splash_source)
                pipeline_getter = getattr(self.config_factory, "get_vfs_pipeline_name", None)
                vfs_pipeline = (data.get("topography_signature") or {}).get(
                    "vfs_pipeline"
                ) or (pipeline_getter() if callable(pipeline_getter) else "pipeline")
                destination = project_dir / vfs_pipeline / "splash.png"
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(str(source), str(destination))
                splash_note = " Splash updated."
                kitsu = getattr(self.production_service, "kitsu", None)
                if project_id and kitsu is not None:
                    if kitsu.upload_project_splash(project_id, str(destination)):
                        splash_note = " Splash updated and uploaded to Kitsu."
                    else:
                        splash_note = " Splash updated (Kitsu upload failed)."
            except Exception as error:  # noqa: BLE001
                return False, f"Could not update the splash screen: {error}"

        self.refresh_requested.emit()
        return True, f"Project configuration saved.{splash_note}"

    def migrate_project(self, project_name: str, project_dir: Path | None = None, target_server_id: str = "") -> None:
        """Migrate a single project's VCS repository to the chosen server."""
        if project_dir is None:
            project_dir = self.nas_manager.resolve_project_dir(project_name)
        if not project_dir:
            self.report_status(f"Project folder for '{project_name}' was not found.", "red")
            return

        source_server = None
        getter = getattr(self.config_factory, "get_server_for_project", None)
        if callable(getter):
            try:
                source_server = getter(project_dir)
            except Exception:  # noqa: BLE001
                source_server = None

        if source_server is not None and not source_server.is_enabled:
            self.report_status("Version Control is disabled for this project.", "red")
            return

        if self.workers.is_running("migrate"):
            self.report_status("A migration is already running...", "red")
            return

        target = None
        getter = getattr(self.config_factory, "get_server", None)
        if target_server_id and callable(getter):
            target = getter(target_server_id)
        if target is None:
            self.report_status("Select a valid target VCS server.", "red")
            return

        # The relocate (and any follow-up work) authenticates against the TARGET
        # server, so gate on the target's credentials, not the source's.
        creds = ensure_vcs_credentials(
            required=target.is_enabled,
            server_id=target.id,
            server_label=target.name,
            needs_passphrase=target.is_remote,
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )
        if creds is None:
            return
        vcs_user, vcs_pwd = creds
        self._ensure_target_passphrase(target)

        if source_server is not None:
            self._migration_source_servers[project_name] = source_server.id
        self._migration_target_servers[project_name] = target.id

        # Drain stale events and start the UI poll timer before the worker runs.
        self._drain_migration_events(flush=True)
        self._migration_timer.start()

        source_dict = source_server.to_dict() if source_server is not None else {}
        self.migration_started.emit(project_name, source_dict, target.to_dict())

        worker = VCSMigrationWorker(
            self.migration_service, project_name, project_dir, vcs_user, vcs_pwd,
            target_server_id=target_server_id,
        )
        worker.progress_update.connect(self.report_status)
        worker.finished_migration.connect(self._on_migration_finished)
        self.workers.start("migrate", worker, critical=True)

    def _drain_migration_events(self, flush: bool = False) -> None:
        """Move queued migration events to UI signals (runs on the main thread)."""
        drained = 0
        while True:
            try:
                kind, payload = self._migration_events.get_nowait()
            except queue.Empty:
                break
            drained += 1
            if kind == "stats" and isinstance(payload, dict):
                self.report_progress(payload.get("percent", 0))
                self.migration_detail.emit(payload)
            elif kind == "log":
                self.migration_log.emit(str(payload))
            elif kind == "phase":
                self.migration_phase.emit(str(payload))
            elif kind == "stalled":
                self.migration_log.emit("⚠ No data received for a while; the transfer may be stalled.")
            elif kind == "log_path":
                self.migration_log.emit(f"Diagnostics saved to: {payload}")
            if not flush and drained >= 500:
                break

    def cancel_migration(self, project_name: str = "") -> None:
        """Ask the running migration to stop (terminates dump/load)."""
        self.migration_service.cancel()

    def delete_target_repository(self, project_name: str) -> None:
        """Delete the partially-loaded target repository after a cancel/failure."""
        target_id = self._migration_target_servers.get(project_name, "")
        if not target_id:
            return
        ok, message = self.migration_service.delete_repository(target_id, project_name)
        self.report_status(message, "yellow" if ok else "red")

    def _on_migration_finished(self, project_name: str, success: bool, message: str) -> None:
        self._drain_migration_events(flush=True)
        self._migration_timer.stop()
        color = "green" if success else "red"
        self.report_status(message, color)
        if success:
            self.report_progress(100)
        else:
            self.clear_progress()
        QTimer.singleShot(2500, self.clear_progress)
        self.migration_finished.emit(project_name, success, message)

    def migration_source_name(self, project_name: str) -> str:
        server_id = self._migration_source_servers.get(project_name, "")
        getter = getattr(self.config_factory, "get_server", None)
        server = getter(server_id) if callable(getter) and server_id else None
        return server.name if server is not None else "the old server"

    def cleanup_local_repository(self, project_name: str) -> None:
        """Optionally delete the old repository after a successful migration."""
        if self.workers.is_running("cleanup"):
            self.report_status("A cleanup is already running...", "red")
            return
        server_id = self._migration_source_servers.get(project_name, "")
        worker = VCSLocalCleanupWorker(self.migration_service, project_name, server_id=server_id)
        worker.finished_cleanup.connect(self._on_cleanup_finished)
        self.workers.start("cleanup", worker, critical=True)

    def _on_cleanup_finished(self, project_name: str, success: bool, message: str) -> None:
        self.report_status(message, "green" if success else "yellow")
        self.cleanup_finished.emit(project_name, success, message)

    def delete_project(self, project_name: str, project_id: str) -> None:
        from src.infrastructure.vcs.vcs_router import VCSRouter

        project_dir = self.nas_manager.resolve_project_dir(project_name)
        success, msg = self.production_service.delete_project(project_id)
        if not success:
            self.delete_warning.emit(msg)

        server = None
        getter = getattr(self.config_factory, "get_server_for_project", None)
        if callable(getter) and project_dir:
            try:
                server = getter(project_dir)
            except Exception:  # noqa: BLE001
                server = None

        if vcs_requires_credentials(self.config_factory, server=server):
            server_id = server.id if server is not None else ""
            provider = None
            if self.credential_vault is not None:
                provider = lambda sid=server_id: self.credential_vault.get_ssh_passphrase(sid)
            if server is not None:
                adapter, repository_url, profile = server.adapter, server.repository_url, server.profile
            else:
                profile_getter = getattr(self.config_factory, "get_vcs_server_profile", None)
                adapter = self.config_factory.get_vcs_adapter_type()
                repository_url = self.config_factory.get_vcs_repository_url()
                profile = profile_getter() if callable(profile_getter) else None
            try:
                VCSRouter.destroy_repository(
                    adapter,
                    repository_url,
                    project_name,
                    self.config_factory.get_vfs_svn_name(),
                    server_profile=profile,
                    ssh_passphrase_provider=provider,
                )
            except Exception as error:  # noqa: BLE001
                print(f"[ProjectList] VCS repository cleanup skipped: {error}")

        if project_dir:
            self.nas_manager.delete_project_folder(project_dir)

        self.delete_completed.emit("Project destroyed.")
        self.refresh_requested.emit()

    # ------------------------------------------------------------------
    # Kitsu project export
    # ------------------------------------------------------------------
    def estimate_export(self, project_id: str, project_name: str, options: dict) -> None:
        if self.workers.is_running("kitsu_estimate"):
            return
        self._drain_export_events(flush=True)
        worker = KitsuExportEstimateWorker(self.export_service, project_id, project_name, options)
        worker.estimate_ready.connect(self.export_estimate_ready)
        worker.estimate_failed.connect(lambda message: self.report_status(message, "red"))
        self.workers.start("kitsu_estimate", worker)

    def request_export(self, project_id: str, project_name: str, destination_dir, options: dict) -> None:
        """Entry point for the export dialog: pre-check the VCS before dumping.

        When the user asks for an embedded SVN dump, uncommitted local files
        would be silently missing from it. Scan first and let the UI offer to
        publish them before starting the export.
        """
        options = dict(options or {})
        if not options.get("embed_svn_dump"):
            self.export_project(project_id, project_name, destination_dir, options)
            return
        if self.workers.is_running("export_precheck"):
            return
        self._pending_export = (project_id, project_name, destination_dir, options)
        project_root = self._project_root_for(project_name)
        worker = CheckVcsChangesWorker(self.sync_service, "__export__", project_root)
        worker.changes_ready.connect(self._on_export_precheck)
        worker.error_occurred.connect(lambda _e: self._on_export_precheck("__export__", []))
        self.workers.start("export_precheck", worker)

    def _on_export_precheck(self, _task_id: str, changes: list) -> None:
        if not self._pending_export:
            return
        changes = list(changes or [])
        if changes:
            self.export_uncommitted_found.emit(self._pending_export[1], changes)
        else:
            self._start_pending_export()

    def export_anyway(self) -> None:
        """Proceed with the pending export without publishing (user's choice)."""
        if self._pending_export:
            self.report_status(
                "Exporting without publishing the uncommitted files.", "yellow"
            )
        self._start_pending_export()

    def publish_then_export(self, changes: list) -> None:
        """Publish the pending changes, then continue the export."""
        pending = self._pending_export
        if not pending or not changes:
            self._start_pending_export()
            return
        project_root = self._project_root_for(pending[1])
        creds = self._ensure_vcs_credentials(project_root)
        if creds is None:
            return
        self._ensure_target_passphrase(self._resolve_server(project_root))
        vcs_user, vcs_pwd = creds
        selected_paths = [change.relative_path for change in changes]
        unversioned_paths = [change.relative_path for change in changes if change.is_unversioned]
        worker = PublishVcsChangesWorker(
            sync_service=self.sync_service,
            task_id="__export__",
            project_root=project_root,
            selected_paths=selected_paths,
            unversioned_paths=unversioned_paths,
            username=vcs_user,
            password=vcs_pwd,
            message=f"OpenStudioHub: publish {len(selected_paths)} file(s) before export.",
        )
        worker.finished_publish.connect(self._on_publish_then_export)
        self.workers.start("export_publish", worker, critical=True)

    def _on_publish_then_export(self, _task_id: str, success: bool, message: str) -> None:
        if not success:
            self.report_status(message, "red")
            return
        self.report_status(message, "green")
        self._start_pending_export()

    def _start_pending_export(self) -> None:
        pending = self._pending_export
        self._pending_export = None
        if pending is None:
            return
        self.export_project(*pending)

    def _project_root_for(self, project_name: str) -> Path:
        resolved = self.nas_manager.resolve_project_dir(project_name)
        if resolved is not None:
            return Path(resolved)
        return self.config_factory.get_workspace_root() / project_name.strip().lower().replace(" ", "-")

    # ------------------------------------------------------------------
    # Manual VCS publish (project card)
    # ------------------------------------------------------------------
    def request_project_publish(self, project_name: str) -> None:
        """Scan the project and open the publish checklist (or report clean)."""
        if self.workers.is_running("publish_scan"):
            return
        project_root = self._project_root_for(project_name)
        if not project_root.exists():
            self.report_status("Cannot publish: project folder is missing on NAS.", "red")
            return
        worker = CheckVcsChangesWorker(self.sync_service, project_name, project_root)
        worker.changes_ready.connect(self._on_publish_scan_ready)
        worker.error_occurred.connect(lambda e: self.report_status(f"VCS scan error: {e}", "red"))
        self.workers.start("publish_scan", worker)

    def _on_publish_scan_ready(self, project_name: str, changes: list) -> None:
        changes = list(changes or [])
        if changes:
            self.publish_changes_ready.emit(project_name, changes)
        else:
            self.publish_up_to_date.emit(project_name)

    def publish_vcs_changes(self, card, selected_changes: list) -> bool:
        """Commit the selected project files (used by the publish checklist)."""
        if not selected_changes:
            self.report_status("No files selected for publishing.", "yellow")
            return False
        project_name = str(getattr(card, "project_name", "") or "")
        project_root = self._project_root_for(project_name)
        if not project_root.exists():
            self.report_status("Cannot publish: project folder is missing on NAS.", "red")
            return False
        if self.workers.is_running("publish"):
            self.report_status("A publish is already in progress...", "red")
            return False
        creds = self._ensure_vcs_credentials(project_root)
        if creds is None:
            return False
        self._ensure_target_passphrase(self._resolve_server(project_root))
        vcs_user, vcs_pwd = creds
        task_id = str((getattr(card, "task_data", {}) or {}).get("id", "__publish__"))
        selected_paths = [change.relative_path for change in selected_changes]
        unversioned_paths = [
            change.relative_path for change in selected_changes if change.is_unversioned
        ]
        worker = PublishVcsChangesWorker(
            sync_service=self.sync_service,
            task_id=task_id,
            project_root=project_root,
            selected_paths=selected_paths,
            unversioned_paths=unversioned_paths,
            username=vcs_user,
            password=vcs_pwd,
            message=f"OpenStudioHub: publish {len(selected_paths)} file(s) for {project_name}.",
        )
        worker.finished_publish.connect(self._on_publish_finished)
        self.workers.start("publish", worker, critical=True)
        return True

    def _on_publish_finished(self, task_id: str, success: bool, message: str) -> None:
        self.report_status(
            ("🟢 " if success else "🔴 ") + message, "green" if success else "red"
        )
        self.vcs_publish_finished.emit(task_id, success, message)

    # ------------------------------------------------------------------
    # Reset VCS working copy (project card)
    # ------------------------------------------------------------------
    def reset_vcs_working_copy(self, project_name: str) -> None:
        """Delete the project's VCS working copy and re-check it out cleanly.

        Recovers working copies with tree conflicts from a pre-scaffolded
        checkout. Destructive: uncommitted local changes are discarded.
        """
        if self.workers.is_running("reset_working_copy"):
            self.report_status("A working-copy reset is already in progress...", "red")
            return
        if self.installation_service is None:
            self.report_status("The installation service is not available.", "red")
            return
        project_root = self._project_root_for(project_name)
        if not project_root.exists():
            self.report_status("Cannot reset: project folder is missing on NAS.", "red")
            return
        creds = self._ensure_vcs_credentials(project_root)
        if creds is None:
            return
        self._ensure_target_passphrase(self._resolve_server(project_root))
        vcs_user, vcs_pwd = creds
        worker = ResetWorkingCopyWorker(
            installation_service=self.installation_service,
            project_root=project_root,
            vfs_svn=self.config_factory.get_vfs_svn_name(),
            vcs_user=vcs_user,
            vcs_pwd=vcs_pwd,
            user_role=self.user_role,
        )
        worker.finished_reset.connect(
            lambda ok, msg, name=project_name: self._on_reset_finished(name, ok, msg)
        )
        self.workers.start("reset_working_copy", worker, critical=True)
        self.report_status(f"Resetting the VCS working copy for '{project_name}'...", "yellow")

    def _on_reset_finished(self, project_name: str, success: bool, message: str) -> None:
        self.report_status(message, "green" if success else "red")
        self.reset_finished.emit(project_name, success, message)
        if success:
            self.refresh_requested.emit()

    def export_project(self, project_id: str, project_name: str, destination_dir, options: dict) -> None:
        if self.workers.is_running("kitsu_export"):
            self.report_status("An export is already running...", "red")
            return
        self._drain_export_events(flush=True)
        self._export_timer.start()
        self.report_progress(0)
        worker = KitsuExportWorker(self.export_service, project_id, project_name, destination_dir, options)
        worker.finished_export.connect(self._on_export_finished)
        self.workers.start("kitsu_export", worker, critical=True)

    def cancel_export(self) -> None:
        self.export_service.cancel()

    def _drain_export_events(self, flush: bool = False) -> None:
        drained = 0
        while True:
            try:
                kind, payload = self._export_events.get_nowait()
            except queue.Empty:
                break
            drained += 1
            if kind == "phase":
                self.export_phase.emit(str(payload))
            elif kind == "log":
                self.export_log.emit(str(payload))
            elif kind == "percent":
                self.report_progress(int(payload))
                self.export_progress.emit(int(payload))
            elif kind == "size_estimate":
                self.export_estimate_ready.emit(dict(payload))
            if not flush and drained >= 500:
                break

    def _on_export_finished(self, project_name: str, success: bool, message: str) -> None:
        self._drain_export_events(flush=True)
        self._export_timer.stop()
        self.report_status(message, "green" if success else "red")
        self.export_finished.emit(project_name, success, message)
        QTimer.singleShot(2500, self.clear_progress)

    # ------------------------------------------------------------------
    # Kitsu project import
    # ------------------------------------------------------------------
    def load_import_archive(self, archive_path) -> None:
        if self.workers.is_running("kitsu_inspect"):
            return
        self._drain_import_events(flush=True)
        worker = KitsuImportInspectWorker(self.import_service, archive_path)
        worker.plan_ready.connect(self._on_import_plan_ready)
        worker.conflict.connect(self.import_conflict)
        worker.inspect_failed.connect(lambda message: self.report_status(message, "red"))
        self.workers.start("kitsu_inspect", worker)

    def _on_import_plan_ready(self, plan, target_persons: list) -> None:
        self._import_plan = plan
        self.import_plan_ready.emit(plan, target_persons)

    def probe_import_repository(self, target_server_id: str) -> None:
        """Probe the target repository so the dialog can prompt for a rename."""
        if self._import_plan is None:
            return
        server = None
        getter = getattr(self.config_factory, "get_server", None)
        if target_server_id and callable(getter):
            server = getter(target_server_id)
        if server is None:
            default = getattr(self.config_factory, "get_default_server", None)
            server = default() if callable(default) else None

        if server is not None and vcs_requires_credentials(self.config_factory, server=server):
            creds = ensure_vcs_credentials(
                required=True,
                server_id=server.id,
                server_label=server.name,
                needs_passphrase=server.is_remote,
                credential_vault=self.credential_vault,
                prompt=self.vcs_prompt,
                report_status=self.report_status,
            )
            if creds is None:
                self.import_repo_status.emit({
                    "state": "unknown", "repo_name": "", "source": "", "target": "",
                    "server_name": server.name if server else "", "dirs": [],
                })
                return
            self._ensure_target_passphrase(server)

        if self.workers.is_running("kitsu_repo_probe"):
            return
        worker = KitsuImportRepoProbeWorker(self.import_service, self._import_plan, target_server_id)
        worker.repo_status.connect(self.import_repo_status)
        self.workers.start("kitsu_repo_probe", worker)

    def create_target_person(self, source_person: dict) -> None:
        source_id = str(source_person.get("id", "") or "new")
        key = f"kitsu_person_{source_id}"
        if self.workers.is_running(key):
            return
        worker = KitsuCreatePersonWorker(self.import_service, source_person)
        worker.person_created.connect(self.import_person_created)
        worker.person_failed.connect(lambda _source, message: self.import_person_failed.emit(message))
        self.workers.start(key, worker)

    def import_project(self, person_map: dict, options: dict) -> None:
        if self._import_plan is None:
            self.report_status("Load an .oshproject archive first.", "red")
            return
        if self.workers.is_running("kitsu_import"):
            self.report_status("An import is already running...", "red")
            return
        self._import_options = dict(options or {})
        self._drain_import_events(flush=True)
        self._import_timer.start()
        self.report_progress(0)
        worker = KitsuImportWorker(self.import_service, self._import_plan, person_map, options)
        worker.finished_import.connect(self._on_import_finished)
        self.workers.start("kitsu_import", worker, critical=True)

    def cancel_import(self) -> None:
        self.import_service.cancel()

    def _drain_import_events(self, flush: bool = False) -> None:
        drained = 0
        while True:
            try:
                kind, payload = self._import_events.get_nowait()
            except queue.Empty:
                break
            drained += 1
            if kind == "phase":
                self.import_phase.emit(str(payload))
            elif kind == "log":
                self.import_log.emit(str(payload))
            elif kind == "percent":
                self.report_progress(int(payload))
                self.import_progress.emit(int(payload))
            if not flush and drained >= 500:
                break

    def _on_import_finished(self, report) -> None:
        self._drain_import_events(flush=True)
        self._import_timer.stop()
        self._import_report = report
        self.report_status(report.message, "green" if report.success else "red")
        self.import_finished.emit(report)
        if report.success:
            self.refresh_requested.emit()
        QTimer.singleShot(2500, self.clear_progress)

    def checkout_imported_project(self) -> None:
        report = self._import_report
        if report is None or report.project_root is None:
            self.report_status("Nothing to check out.", "red")
            return
        if self.workers.is_running("kitsu_checkout"):
            return

        server = None
        server_id = self._import_options.get("target_vcs_server_id", "")
        getter = getattr(self.config_factory, "get_server", None)
        if server_id and callable(getter):
            server = getter(server_id)
        if server is None:
            default = getattr(self.config_factory, "get_default_server", None)
            server = default() if callable(default) else None

        creds = ensure_vcs_credentials(
            required=vcs_requires_credentials(self.config_factory, server=server),
            server_id=server.id if server is not None else "",
            server_label=server.name if server is not None else "default",
            needs_passphrase=bool(server is not None and server.is_remote),
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )
        if creds is None:
            return
        vcs_user, vcs_pwd = creds
        self._ensure_target_passphrase(server)

        worker = KitsuCheckoutWorker(self.import_service, report.project_root, vcs_user, vcs_pwd, self.user_role)
        worker.finished_checkout.connect(self._on_checkout_finished)
        self.workers.start("kitsu_checkout", worker, critical=True)

    def _on_checkout_finished(self, success: bool, message: str) -> None:
        self.report_status(message, "green" if success else "red")
        self.checkout_finished.emit(success, message)
        if success:
            self.refresh_requested.emit()

    def rollback_import(self) -> None:
        report = self._import_report
        if report is None or not getattr(report, "project_id", ""):
            self.report_status("Nothing to roll back.", "red")
            return
        if self.workers.is_running("kitsu_rollback"):
            return
        worker = KitsuRollbackWorker(self.import_service, self._import_plan, report.project_id)
        worker.finished_rollback.connect(self._on_rollback_finished)
        self.workers.start("kitsu_rollback", worker, critical=True)

    def _on_rollback_finished(self, success: bool, message: str) -> None:
        self.report_status(message, "green" if success else "red")
        self.rollback_finished.emit(success, message)

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------
    def build_kitsu_url(self, project_id: str, sub_path: str) -> str:
        kitsu_url = self.config_factory.get_kitsu_api_url()
        if kitsu_url.endswith("/api"):
            kitsu_url = kitsu_url[:-4]
        return f"{kitsu_url}/productions/{project_id}{sub_path}"

    def open_kitsu(self, project_id: str, sub_path: str) -> None:
        self.open_kitsu_callback(self.build_kitsu_url(project_id, sub_path))

    def open_watchtower(self, project_dir: Path) -> None:
        self.open_watchtower_callback(project_dir)
