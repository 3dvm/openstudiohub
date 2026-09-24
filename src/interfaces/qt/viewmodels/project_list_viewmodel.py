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
import queue

from PySide6.QtCore import QTimer, Signal

from src.application.services.auth_service import AuthService
from src.application.services.installation_service import InstallationService
from src.application.services.production_service import ProductionService
from src.application.services.project_audit_service import ProjectAuditService
from src.application.services.vcs_migration_service import VCSMigrationService
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
from src.interfaces.qt.workers.project_list_workers import ProjectGridWorker
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

        self.nas_manager = NasManager(self.nas_dir)
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
        self._projects: List[dict] = []
        self.workers = WorkerManager(self)
        self._refresh_pending = False

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

    def list_servers(self) -> list:
        registry = self.config_factory.get_vcs_servers()
        return [
            {**server.to_dict(), "is_default": server.id == registry.default_server_id}
            for server in registry.servers
        ]

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
