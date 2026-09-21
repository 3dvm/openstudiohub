# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/artist_viewmodel.py
# Architectural role: MVVM ViewModel / artist dashboard
# =========================================================================================

"""ViewModel for the artist dashboard.

Fetches assigned tasks, enriches them with filesystem state (installed /
blocked), and orchestrates the launch and install use cases. It exposes plain
``ArtistTaskCardModel`` dataclasses so the View only renders.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Signal

from src.application.credential_vault import CredentialVault
from src.application.services.auth_service import AuthService
from src.application.services.installation_service import InstallationService
from src.application.services.production_service import ProductionService
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.viewmodels.vcs_credential_gate import (
    VcsPrompt,
    ensure_vcs_credentials,
    vcs_requires_credentials,
)
from src.interfaces.qt.workers.artist_workers import (
    FetchArtistTasksWorker,
    InstallProjectWorker,
    LaunchTaskWorker,
)
from src.interfaces.qt.workers.worker_manager import WorkerManager


@dataclass
class ArtistTaskCardModel:
    """Presentation-ready data for a single task card."""

    task_data: dict
    project_root: Optional[Path]
    config_path: Optional[Path]
    is_installed: bool
    can_work: bool
    blocked_reason: str
    project_id: str
    project_name: str


class ArtistViewModel(BaseViewModel):
    tasks_loaded = Signal(list)  # list[ArtistTaskCardModel]

    def __init__(
        self,
        production_service: ProductionService,
        auth_service: AuthService,
        credential_vault: CredentialVault,
        config_factory,
        installation_service: InstallationService,
        register_instance: Callable[[bool], None],
        status_sink: StatusSink | None = None,
        vcs_prompt: VcsPrompt | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.production_service = production_service
        self.auth_service = auth_service
        self.credential_vault = credential_vault
        self.config_factory = config_factory
        self.installation_service = installation_service
        self.register_instance = register_instance
        self.vcs_prompt = vcs_prompt

        self._cards: List[ArtistTaskCardModel] = []
        self.workers = WorkerManager(self)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def load_tasks(self) -> None:
        if self.workers.is_running("tasks"):
            return

        self.report_status("Fetching your assigned tasks from Kitsu...", "yellow")
        self._cards = []

        worker = FetchArtistTasksWorker(self.production_service)
        worker.data_ready.connect(self._on_tasks_fetched)
        worker.error_occurred.connect(lambda e: self.report_status(f"Network error: {e}", "red"))
        self.workers.start("tasks", worker)

    def _on_tasks_fetched(self, tasks: list) -> None:
        if not tasks:
            self.report_status("You have no pending tasks. Enjoy your coffee! ☕", "white")
            self.tasks_loaded.emit([])
            return

        cards = [self.enrich_task(task) for task in tasks]
        self._cards = cards
        self.report_status(f"🟢 Synchronized: {len(tasks)} active tasks found.", "green")
        self.tasks_loaded.emit(cards)

    def enrich_task(self, task_data: dict) -> ArtistTaskCardModel:
        """Compute filesystem-backed state for a single raw Kitsu task."""
        vfs_pipeline = self.config_factory.get_vfs_pipeline_name()
        vfs_local = self.config_factory.get_vfs_local_name()
        nas_root = self.config_factory.get_workspace_root()

        project_name = task_data.get("project_name") or (task_data.get("project") or {}).get("name", "Unknown")
        folder_name = project_name.strip().lower().replace(" ", "-")
        temp_root = nas_root / folder_name

        project_root: Optional[Path] = temp_root if temp_root.exists() else None

        is_installed = False
        can_work = True
        blocked_reason = ""

        if project_root:
            try:
                is_installed = self.installation_service.verify_installation(project_root)
            except Exception:  # noqa: BLE001
                is_installed = False

            if not is_installed:
                init_json_path = project_root / vfs_pipeline / "project_init.json"
                if not init_json_path.exists():
                    can_work = False
                    blocked_reason = "Missing NAS Setup"
        else:
            can_work = False
            blocked_reason = "Folder Missing on NAS"

        config_path = project_root / vfs_local / "project_config.json" if project_root else None

        return ArtistTaskCardModel(
            task_data=task_data,
            project_root=project_root,
            config_path=config_path,
            is_installed=is_installed,
            can_work=can_work,
            blocked_reason=blocked_reason,
            project_id=task_data.get("project_id", ""),
            project_name=project_name,
        )

    # ------------------------------------------------------------------
    # Launch use case
    # ------------------------------------------------------------------
    def _ensure_vcs_credentials(self) -> Optional[tuple[str, str]]:
        """Gate VCS-backed actions behind the session credentials prompt."""
        return ensure_vcs_credentials(
            required=vcs_requires_credentials(self.config_factory),
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )

    def launch(self, card: ArtistTaskCardModel) -> None:
        config_path = card.config_path
        if not config_path or not config_path.exists():
            self.report_status("Config file missing. Reinstall workspace.", "red")
            return

        creds = self._ensure_vcs_credentials()
        if creds is None:
            return
        svn_user, svn_pwd = creds

        self.report_status("🚀 Delegating to the DCC orchestrator...", "yellow")

        kitsu_user, kitsu_pwd = self.credential_vault.get_kitsu_credentials()
        if not kitsu_pwd:
            self.report_status("Kitsu Password lost in RAM. Please log out and log in again.", "red")
            return

        kitsu_host = self.config_factory.get_kitsu_api_url()

        self.register_instance(True)

        if self.workers.is_running("launch"):
            self.report_status("A launch is already in progress...", "red")
            return

        kwargs = {
            "project_root": card.project_root,
            "config_path": config_path,
            "svn_user": svn_user,
            "svn_pwd": svn_pwd,
            "kitsu_user": kitsu_user,
            "kitsu_pwd": kitsu_pwd,
            "kitsu_host": kitsu_host,
            "user_role": "artist",
            "task_data": card.task_data,
            "target_file": None,
            "status_callback": self.report_status,
            "config_factory": self.config_factory,
        }

        worker = LaunchTaskWorker(kwargs)
        worker.finished_launch.connect(self._on_launch_finished)
        self.workers.start("launch", worker)

    def _on_launch_finished(self, success: bool, message: str) -> None:
        self.register_instance(False)
        self.report_status(message, "green" if success else "red")

    # ------------------------------------------------------------------
    # Install use case
    # ------------------------------------------------------------------
    def install(self, card: ArtistTaskCardModel) -> None:
        if not card.project_root:
            self.report_status("Cannot install: Project folder is missing on NAS.", "red")
            return

        if self.workers.is_running("install"):
            self.report_status("Please wait, an installation is already running...", "red")
            return

        creds = self._ensure_vcs_credentials()
        if creds is None:
            return
        vcs_user, vcs_pwd = creds

        worker = InstallProjectWorker(
            project_root=card.project_root,
            vcs_user=vcs_user,
            vcs_pwd=vcs_pwd,
            installation_service=self.installation_service,
            task_data=card.task_data,
        )
        worker.progress_updated.connect(self.report_status)
        worker.finished_install.connect(self._on_install_finished)
        self.workers.start("install", worker)

    def _on_install_finished(self, success: bool, message: str) -> None:
        if success:
            self.report_status(f"🟢 100% - {message}", "green")
            self.load_tasks()
        else:
            self.report_status(f"🔴 Install Error: {message}", "red")

    # ------------------------------------------------------------------
    # Session VCS settings (RAM-only)
    # ------------------------------------------------------------------
    def vcs_settings(self) -> tuple[str, bool]:
        username, _ = self.credential_vault.get_svn_credentials()
        return username or "", self.credential_vault.is_svn_enabled()

    def save_vcs_settings(self, username: str, password: str, enabled: bool) -> None:
        if not username:
            username = self.auth_service.current_user.email if self.auth_service.current_user else "artist"
        self.credential_vault.save_svn_credentials(username, password, enabled)
        self.report_status("✓ VCS credentials stored in RAM for this session.", "green")
