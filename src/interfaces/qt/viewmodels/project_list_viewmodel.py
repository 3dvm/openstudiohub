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

from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Signal

from src.application.services.auth_service import AuthService
from src.application.services.installation_service import InstallationService
from src.application.services.production_service import ProductionService
from src.infrastructure.dev_defaults import DEV_SVN_PASSWORD, DEV_SVN_USER
from src.infrastructure.nas_manager import NasManager
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.workers.project_list_workers import ProjectGridWorker


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
        read_vcs_credentials: bool,
        nas_dir: Path,
        open_kitsu_callback: Callable[[str], None],
        open_watchtower_callback: Callable[[Path], None],
        instance_lock_callback: Callable[[bool], None] | None = None,
        status_sink: StatusSink | None = None,
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

        self.nas_manager = NasManager(self.nas_dir)
        self._projects: List[dict] = []
        self._install_worker = None

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
        self.report_status("Syncing projects catalog...", "yellow")
        self._projects = []

        self._worker = ProjectGridWorker(self.production_service)
        self._worker.data_ready.connect(self._on_projects_fetched)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_projects_fetched(self, projects: list) -> None:
        self._projects = projects
        if not projects:
            self.report_status("No active projects found.", "yellow")
        else:
            self.report_status(f"🟢 Synchronized: {len(projects)} active projects.", "green")
        self.projects_loaded.emit(projects)

    def compute_status(self, project_data: dict) -> dict:
        """Resolve the filesystem-backed status rendered by a project card."""
        project_name = project_data.get("name", "")
        project_code = project_data.get("code", "")
        project_dir = self.nas_manager.resolve_project_dir(project_name, project_code)

        is_installed = False
        if self.config_factory and project_dir:
            is_installed = self.installation_service.verify_installation(project_dir)

        if is_installed and project_dir:
            blueprint = self.nas_manager.get_project_blueprint(project_dir)
            return {
                "project_dir": project_dir,
                "is_installed": True,
                "badge_text": blueprint.get("blender_version", "Blender"),
                "sync_text": "🗄️ 🟢 Ready on Disk",
            }

        return {
            "project_dir": project_dir,
            "is_installed": False,
            "badge_text": "Not Mounted",
            "sync_text": "🗄️ ⚪ Cloud Only",
        }

    def thumbnail_fetcher(self, project_id: str, token: str, host: str) -> Optional[bytes]:
        return self.production_service.download_project_thumbnail(project_id, token, host)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def install_project(self, project_dir: Path) -> None:
        vcs_user, vcs_pwd = "", ""
        if self.read_vcs_credentials:
            vcs_config = self.config_factory.get_raw_config().get("vcs_engine", {})
            vcs_user = vcs_config.get("vcs_username", DEV_SVN_USER)
            vcs_pwd = vcs_config.get("vcs_password", DEV_SVN_PASSWORD)

        self._install_worker = self._build_install_worker(project_dir, vcs_user, vcs_pwd)
        self._install_worker.progress_update.connect(self.report_status)
        self._install_worker.finished_install.connect(
            lambda success, msg, p=project_dir: self._on_install_finished(p, success, msg)
        )
        self._install_worker.start()

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
