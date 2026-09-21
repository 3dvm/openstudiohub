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

from PySide6.QtCore import Signal

from src.application.services.auth_service import AuthService
from src.application.services.installation_service import InstallationService
from src.application.services.production_service import ProductionService
from src.application.services.project_audit_service import ProjectAuditService
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
from src.interfaces.qt.workers.worker_manager import WorkerManager


class ProjectListViewModel(BaseViewModel):
    projects_loaded = Signal(list)  # list[dict] raw project data
    refresh_requested = Signal()
    install_finished = Signal(object, bool, str)  # (project_dir, success, message)
    delete_warning = Signal(str)
    delete_completed = Signal(str)

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

        self.nas_manager = NasManager(self.nas_dir)
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
    def _ensure_vcs_credentials(self) -> Optional[tuple[str, str]]:
        """Gate VCS-backed actions behind the session credentials prompt."""
        return ensure_vcs_credentials(
            required=vcs_requires_credentials(self.config_factory),
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )

    def install_project(self, project_dir: Path) -> None:
        if self.workers.is_running("install"):
            self.report_status("Please wait, an installation is already running...", "red")
            return

        creds = self._ensure_vcs_credentials()
        if creds is None:
            return
        vcs_user, vcs_pwd = creds

        worker = self._build_install_worker(project_dir, vcs_user, vcs_pwd)
        worker.progress_update.connect(self.report_status)
        worker.finished_install.connect(
            lambda success, msg, p=project_dir: self._on_install_finished(p, success, msg)
        )
        self.workers.start("install", worker)

    def _build_install_worker(self, project_dir: Path, vcs_user: str, vcs_pwd: str):
        from src.interfaces.qt.workers.project_list_workers import ProjectInstallWorker

        return ProjectInstallWorker(self.installation_service, project_dir, vcs_user, vcs_pwd, self.user_role)

    def _on_install_finished(self, project_dir: Path, success: bool, message: str) -> None:
        self.install_finished.emit(project_dir, success, message)
        if success:
            self.report_status("✓ Workspace deployed", "green")
            self.refresh_requested.emit()
        else:
            self.report_status(f"✗ Install Failed: {message}", "red")

    def launch_project(self, project_dir: Path) -> None:
        config_path = project_dir / "local" / "project_config.json"
        if not config_path.exists():
            self.report_status("Error: config missing.", "red")
            return

        creds = self._ensure_vcs_credentials()
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

    def delete_project(self, project_name: str, project_id: str) -> None:
        import subprocess

        folder_name = project_name.lower().replace(" ", "-")
        project_dir = self.nas_manager.resolve_project_dir(project_name)
        success, msg = self.production_service.delete_project(project_id)
        if not success:
            self.delete_warning.emit(msg)
        try:
            subprocess.run(
                ["docker", "exec", "openstudio_local_svn", "rm", "-rf", f"/home/svn/{folder_name}"],
                check=False,
            )
        except Exception:  # noqa: BLE001
            pass
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
