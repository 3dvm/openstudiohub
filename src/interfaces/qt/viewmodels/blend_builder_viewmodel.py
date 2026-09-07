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
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
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


class BlendBuilderViewModel(BaseViewModel):
    projects_loaded = Signal(list)  # list[dict] {id, name}
    editorial_status_loaded = Signal(dict)
    assets_loaded = Signal(list)
    shots_loaded = Signal(list, list)
    sequences_loaded = Signal(list)
    spawn_progress = Signal(int, str)
    spawn_log = Signal(str)
    spawn_finished = Signal(bool, str)

    def __init__(
        self,
        production_service: ProductionService,
        config_factory,
        credential_vault: CredentialVault,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.production_service = production_service
        self.config_factory = config_factory
        self.credential_vault = credential_vault

        self.pm_core = ProductionManager(self.config_factory)
        self.current_project_id: Optional[str] = None
        self.current_project_name: str = ""
        self.project_map: dict = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def project_root(self) -> Path:
        nas_root = self.config_factory.get_workspace_root()
        folder_name = self.current_project_name.strip().lower().replace(" ", "-")
        return nas_root / folder_name

    def inject_credentials(self) -> None:
        """Expose the transient Kitsu credentials to the headless subprocess."""
        if self.credential_vault:
            kitsu_user, kitsu_pwd = self.credential_vault.get_kitsu_credentials()
            os.environ["OPENSTUDIO_KITSU_USER"] = kitsu_user or ""
            os.environ["OPENSTUDIO_KITSU_PWD"] = kitsu_pwd or ""

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
    # Navigation
    # ------------------------------------------------------------------
    def kitsu_assets_url(self) -> str:
        kitsu_url = self.config_factory.get_kitsu_api_url().replace("/api", "")
        return f"{kitsu_url}/productions/{self.current_project_id}/assets?search="
