# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/blend_builder_viewmodel.py
# Architectural role: MVVM ViewModel / batch entity genesis (PM)
# =========================================================================================

"""ViewModel for the batch entity builder (PM wizard).

Owns the project selection state and the auditing/spawning use cases. It emits
fine-grained signals (progress / log / finished) so the View can drive the
modal progress dialog without knowing about workers or services.
"""

import os
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Signal

from src.application.credential_vault import CredentialVault
from src.application.production_manager import ProductionManager
from src.application.services.production_service import ProductionService
from src.application.services.task_file_service import TaskFileService
from src.domain.production.entities import Task
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.viewmodels.vcs_credential_gate import (
    VcsPrompt,
    ensure_vcs_credentials,
    vcs_requires_credentials,
)
from src.interfaces.qt.workers.api_queries import (
    FetchAssetsWorker,
    FetchEditStatusWorker,
    FetchProjectsWorker,
    FetchSequencesWorker,
    FetchShotsWorker,
)
from src.interfaces.qt.workers.blender_spawners import (
    BatchCreationWorker,
    MasterSpawningWorker,
    StoryboardBatchWorker,
)
from src.interfaces.qt.workers.project_list_workers import ProjectInstallWorker
from src.interfaces.qt.workers.task_file_workers import TaskFileWorker
from src.interfaces.qt.workers.worker_keepalive import keep_worker_alive


class BlendBuilderViewModel(BaseViewModel):
    projects_loaded = Signal(list)  # list[dict] {id, name}
    editorial_status_loaded = Signal(dict)
    assets_loaded = Signal(list)
    shots_loaded = Signal(list, list)
    sequences_loaded = Signal(list)
    spawn_progress = Signal(int, str)
    spawn_log = Signal(str)
    spawn_finished = Signal(bool, str)
    task_file_finished = Signal(bool, str)
    install_progress = Signal(str, str)
    install_finished = Signal(bool, str)

    def __init__(
        self,
        production_service: ProductionService,
        config_factory,
        credential_vault: CredentialVault,
        status_sink: StatusSink | None = None,
        vcs_prompt: VcsPrompt | None = None,
        installation_service=None,
        user_role: str = "manager",
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.production_service = production_service
        self.config_factory = config_factory
        self.credential_vault = credential_vault
        self.vcs_prompt = vcs_prompt
        self.installation_service = installation_service
        self.user_role = user_role

        self.pm_core = ProductionManager(self.config_factory)
        self.task_file_service = TaskFileService(self.config_factory)
        self.current_project_id: Optional[str] = None
        self.current_project_name: str = ""
        self.project_map: dict = {}
        self._task_file_worker: Optional[TaskFileWorker] = None
        self._install_worker: Optional[ProjectInstallWorker] = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def project_root(self) -> Path:
        nas_root = self.config_factory.get_workspace_root()
        folder_name = self.current_project_name.strip().lower().replace(" ", "-")
        return nas_root / folder_name

    def inject_credentials(self) -> None:
        """Expose the transient Kitsu/VCS credentials to the headless subprocess."""
        if self.credential_vault:
            kitsu_user, kitsu_pwd = self.credential_vault.get_kitsu_credentials()
            os.environ["OPENSTUDIO_KITSU_USER"] = kitsu_user or ""
            os.environ["OPENSTUDIO_KITSU_PWD"] = kitsu_pwd or ""

            svn_user, svn_pwd = self.credential_vault.get_svn_credentials()
            os.environ["OPENSTUDIO_SVN_USER"] = svn_user or ""
            os.environ["OPENSTUDIO_SVN_PASSWORD"] = svn_pwd or ""

    def _ensure_vcs_credentials(self) -> bool:
        """Gate VCS-backed batch spawning behind the session credentials prompt."""
        creds = ensure_vcs_credentials(
            required=vcs_requires_credentials(self.config_factory),
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )
        return creds is not None

    # ------------------------------------------------------------------
    # Project loading
    # ------------------------------------------------------------------
    def load_projects(self) -> None:
        self.worker_projects = FetchProjectsWorker(self.production_service)
        self.worker_projects.data_ready.connect(self._on_projects_loaded)
        self.worker_projects.error_occurred.connect(lambda e: self.report_status(f"Project fetch error: {e}", "red"))
        self.worker_projects.start()

    def _on_projects_loaded(self, projects: list) -> None:
        self.project_map = {p.get("name", "Unknown"): p.get("id") for p in projects}
        self.projects_loaded.emit(projects)

    def select_project(self, project_name: str) -> None:
        if project_name in self.project_map:
            self.current_project_id = self.project_map[project_name]
            self.current_project_name = project_name

    # ------------------------------------------------------------------
    # Local installation gate
    # ------------------------------------------------------------------
    def is_current_project_installed(self) -> bool:
        """True when the selected project's local workspace is fully provisioned."""
        if not self.current_project_id:
            return False
        if self.installation_service is None:
            return True
        try:
            return self.installation_service.verify_installation(self.project_root())
        except Exception:  # noqa: BLE001
            return False

    def install_current_project(self) -> bool:
        """Provision the selected project's local workspace (Blender + VCS).

        Returns ``True`` when the install worker actually started (so the view
        can keep its button disabled), ``False`` when it was aborted (no
        project/service, already running, or credentials cancelled).
        """
        if not self.current_project_id:
            self.report_status("Please select a project first.", "yellow")
            return False
        if self.installation_service is None:
            self.report_status("Installation service unavailable.", "red")
            return False
        if self._install_worker is not None and self._install_worker.isRunning():
            self.report_status("Please wait, an installation is already running...", "red")
            return False

        creds = ensure_vcs_credentials(
            required=vcs_requires_credentials(self.config_factory),
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )
        if creds is None:
            return False
        vcs_user, vcs_pwd = creds

        self.report_status("Installing project workspace...", "yellow")
        self._install_worker = ProjectInstallWorker(
            self.installation_service,
            self.project_root(),
            vcs_user,
            vcs_pwd,
            self.user_role,
        )
        self._install_worker.progress_update.connect(self.install_progress.emit)
        self._install_worker.finished_install.connect(self._on_install_finished)
        self._install_worker.finished.connect(self._on_install_worker_finished)
        keep_worker_alive(self._install_worker)
        self._install_worker.start()
        return True

    def _on_install_worker_finished(self) -> None:
        self._install_worker = None

    def _on_install_finished(self, success: bool, message: str) -> None:
        self.install_finished.emit(success, message)
        if success:
            self.report_status("✓ Workspace installed", "green")
        else:
            self.report_status(f"✗ Install failed: {message}", "red")

    # ------------------------------------------------------------------
    # Audits
    # ------------------------------------------------------------------
    def load_sequences(self) -> None:
        if not self.current_project_id:
            return
        vfs_svn = self.config_factory.get_vfs_svn_name()
        self.worker_seqs = FetchSequencesWorker(
            self.production_service, self.current_project_id, self.project_root(), vfs_svn
        )
        self.worker_seqs.data_ready.connect(self.sequences_loaded.emit)
        self.worker_seqs.error_occurred.connect(lambda e: self.report_status(f"Seq fetch error: {e}", "red"))
        self.worker_seqs.start()

    def load_editorial_status(self) -> None:
        if not self.current_project_id:
            return
        self.report_status("Auditing Editorial Master...", "yellow")
        vfs_svn = self.config_factory.get_vfs_svn_name()
        self.worker_edit = FetchEditStatusWorker(
            self.production_service,
            self.current_project_id,
            self.current_project_name,
            self.project_root(),
            vfs_svn,
        )
        self.worker_edit.data_ready.connect(self.editorial_status_loaded.emit)
        self.worker_edit.error_occurred.connect(lambda e: self.report_status(f"Edit fetch error: {e}", "red"))
        self.worker_edit.start()

    def load_assets(self) -> None:
        if not self.current_project_id:
            return
        self.report_status("Auditing assets from Kitsu and SVN...", "yellow")
        vfs_svn = self.config_factory.get_vfs_svn_name()
        self.worker_assets = FetchAssetsWorker(
            self.production_service, self.current_project_id, self.project_root(), vfs_svn
        )
        self.worker_assets.data_ready.connect(self.assets_loaded.emit)
        self.worker_assets.error_occurred.connect(lambda e: self.report_status(f"Asset fetch error: {e}", "red"))
        self.worker_assets.start()

    def load_shots(self) -> None:
        if not self.current_project_id:
            return
        self.report_status("Fetching pending shots from Kitsu...", "yellow")
        vfs_svn = self.config_factory.get_vfs_svn_name()
        self.worker_shots = FetchShotsWorker(
            self.production_service, self.current_project_id, self.project_root(), vfs_svn
        )
        self.worker_shots.data_ready.connect(self.shots_loaded.emit)
        self.worker_shots.error_occurred.connect(lambda e: self.report_status(f"Shot fetch error: {e}", "red"))
        self.worker_shots.start()

    # ------------------------------------------------------------------
    # Spawning use cases
    # ------------------------------------------------------------------
    def spawn_storyboard(self, sequence_names: list) -> None:
        if not self.current_project_id:
            self.report_status("Please select a project first.", "yellow")
            return
        if not self._ensure_vcs_credentials():
            return
        self.report_status("Spawning Storyboard sequences...", "yellow")
        self.inject_credentials()

        self.spawn_worker = StoryboardBatchWorker(
            self.pm_core, self.config_factory, self.current_project_id, self.current_project_name, sequence_names
        )
        self.spawn_worker.progress_updated.connect(self.spawn_progress.emit)
        self.spawn_worker.log_stream.connect(self.spawn_log.emit)
        self.spawn_worker.finished_batch.connect(self.spawn_finished.emit)
        self.spawn_worker.start()

    def spawn_edit_master(self) -> None:
        if not self.current_project_id:
            self.report_status("Please select a project first.", "yellow")
            return
        if not self._ensure_vcs_credentials():
            return
        self.inject_credentials()
        self.spawn_worker = MasterSpawningWorker(
            self.config_factory, self.current_project_name, "EDIT", self.current_project_id
        )
        self.spawn_worker.progress_updated.connect(self.spawn_progress.emit)
        self.spawn_worker.log_stream.connect(self.spawn_log.emit)
        self.spawn_worker.finished_spawn.connect(self.spawn_finished.emit)
        self.spawn_worker.start()

    def spawn_batch(self, entities: list, task_types: list) -> None:
        if not self.current_project_id:
            self.report_status("Please select a project first.", "yellow")
            return
        if not self._ensure_vcs_credentials():
            return
        self.inject_credentials()
        self.worker_batch = BatchCreationWorker(
            pm_core=self.pm_core,
            config_factory=self.config_factory,
            project_id=self.current_project_id,
            project_name=self.current_project_name,
            entities=entities,
            task_types=task_types,
        )
        self.worker_batch.progress_updated.connect(self.spawn_progress.emit)
        self.worker_batch.log_stream.connect(self.spawn_log.emit)
        self.worker_batch.finished_batch.connect(self.spawn_finished.emit)
        self.worker_batch.start()

    # ------------------------------------------------------------------
    # Task <-> file mapping
    # ------------------------------------------------------------------
    def suggest_task_file_path(self, task: Task) -> str:
        return self.task_file_service.suggest_relative_path(task)

    def _start_task_file_worker(self, task: Task, action: str, relative_path: str = "") -> None:
        if self._task_file_worker is not None and self._task_file_worker.isRunning():
            self.report_status("Another file operation is already running...", "red")
            return
        self._task_file_worker = TaskFileWorker(
            service=self.task_file_service,
            task=task,
            project_root=self.project_root(),
            action=action,
            relative_path=relative_path,
        )
        self._task_file_worker.finished_link.connect(self._on_task_file_finished)
        self._task_file_worker.finished.connect(self._task_file_worker.deleteLater)
        self._task_file_worker.start()

    def _on_task_file_finished(self, success: bool, message: str) -> None:
        self._task_file_worker = None
        self.task_file_finished.emit(success, message)

    def link_task_file(self, task: Task, relative_path: str) -> None:
        self._start_task_file_worker(task, "link", relative_path)

    def create_empty_task_file(self, task: Task, project_root: Path, relative_path: str) -> None:
        self._start_task_file_worker(task, "create_empty", relative_path)

    def unlink_task_file(self, task: Task) -> None:
        self._start_task_file_worker(task, "unlink")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def kitsu_assets_url(self) -> str:
        kitsu_url = self.config_factory.get_kitsu_api_url().replace("/api", "")
        return f"{kitsu_url}/productions/{self.current_project_id}/assets?search="
