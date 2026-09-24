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
from src.application.services.task_file_sync_service import TaskFileSyncService
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
from src.interfaces.qt.workers.artist_workers import (
    CheckVcsChangesWorker,
    PublishVcsChangesWorker,
)
from src.interfaces.qt.workers.blender_spawners import (
    BatchCreationWorker,
    MasterSpawningWorker,
    StoryboardBatchWorker,
)
from src.interfaces.qt.workers.project_list_workers import ProjectInstallWorker
from src.interfaces.qt.workers.task_file_workers import TaskFileWorker
from src.interfaces.qt.workers.worker_manager import WorkerManager


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
    project_changes_ready = Signal(list)  # list[FileChange] for the current project
    project_publish_dialog_requested = Signal(list)  # interactive scan with changes
    project_publish_up_to_date = Signal()  # interactive scan with no changes
    vcs_publish_finished = Signal(str, bool, str)  # (task_id, success, message)

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
        self.task_file_sync_service = TaskFileSyncService(self.config_factory)
        self._publish_scan_interactive = False
        self._publish_scan_notify_clean = True
        self.current_project_id: Optional[str] = None
        self.current_project_name: str = ""
        self.project_map: dict = {}
        self.workers = WorkerManager(self)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def project_root(self) -> Path:
        nas_root = self.config_factory.get_workspace_root()
        folder_name = self.current_project_name.strip().lower().replace(" ", "-")
        return nas_root / folder_name

    def _resolve_server(self):
        getter = getattr(self.config_factory, "get_server_for_project", None)
        if callable(getter):
            try:
                server = getter(self.project_root())
                if server is not None:
                    return server
            except Exception:  # noqa: BLE001
                pass
        getter = getattr(self.config_factory, "get_default_server", None)
        return getter() if callable(getter) else None

    def inject_credentials(self) -> None:
        """Expose the transient Kitsu/VCS credentials to the headless subprocess."""
        if not self.credential_vault:
            return
        kitsu_user, kitsu_pwd = self.credential_vault.get_kitsu_credentials()
        os.environ["OPENSTUDIO_KITSU_USER"] = kitsu_user or ""
        os.environ["OPENSTUDIO_KITSU_PWD"] = kitsu_pwd or ""

        server = self._resolve_server()
        self.credential_vault.export_server_env(server.id if server is not None else "")

    def _ensure_vcs_credentials(self) -> bool:
        """Gate VCS-backed batch spawning behind the per-server credentials prompt."""
        server = self._resolve_server()
        creds = ensure_vcs_credentials(
            required=vcs_requires_credentials(self.config_factory, server=server),
            server_id=server.id if server is not None else "",
            server_label=server.name if server is not None else "default",
            needs_passphrase=bool(server is not None and server.is_remote),
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )
        return creds is not None

    # ------------------------------------------------------------------
    # Project loading
    # ------------------------------------------------------------------
    def load_projects(self) -> None:
        """Fetch the Kitsu project catalog (safe to call repeatedly)."""
        worker = FetchProjectsWorker(self.production_service)
        worker.data_ready.connect(self._on_projects_loaded)
        worker.error_occurred.connect(lambda e: self.report_status(f"Project fetch error: {e}", "red"))
        self.workers.start("projects", worker)

    def _on_projects_loaded(self, projects: list) -> None:
        self.project_map = {p.get("name", "Unknown"): p.get("id") for p in projects}
        self.projects_loaded.emit(projects)

    def select_project(self, project_name: str) -> None:
        """Select a project by its Kitsu name, ignoring case differences."""
        key = self._resolve_project_key(project_name)
        if key is None:
            self.current_project_id = None
            self.current_project_name = ""
            return
        self.current_project_id = self.project_map[key]
        self.current_project_name = key

    def _resolve_project_key(self, project_name: str) -> Optional[str]:
        if project_name in self.project_map:
            return project_name
        target = (project_name or "").strip().lower()
        for name in self.project_map:
            if name.strip().lower() == target:
                return name
        return None

    def _emit_for_current_project(self, project_id: str, signal, *args) -> None:
        """Drop results that belong to a project the user has already left.

        Since stale workers are skipped rather than cancelled, an in-flight
        fetch for the previous project can still deliver after a new selection.
        """
        if project_id == self.current_project_id:
            signal.emit(*args)

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
        if self.workers.is_running("install"):
            self.report_status("Please wait, an installation is already running...", "red")
            return False

        server = self._resolve_server()
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
            return False
        vcs_user, vcs_pwd = creds

        self.report_status("Installing project workspace...", "yellow")
        worker = ProjectInstallWorker(
            self.installation_service,
            self.project_root(),
            vcs_user,
            vcs_pwd,
            self.user_role,
        )
        worker.progress_update.connect(self.install_progress.emit)
        worker.finished_install.connect(self._on_install_finished)
        self.workers.start("install", worker, critical=True)
        return True

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
        worker = FetchSequencesWorker(
            self.production_service, self.current_project_id, self.project_root(), vfs_svn
        )
        worker.data_ready.connect(
            lambda *a, pid=self.current_project_id: self._emit_for_current_project(
                pid, self.sequences_loaded, *a
            )
        )
        worker.error_occurred.connect(lambda e: self.report_status(f"Seq fetch error: {e}", "red"))
        self.workers.start("sequences", worker)

    def load_editorial_status(self) -> None:
        if not self.current_project_id:
            return
        if self.workers.is_running("edit"):
            return
        self.report_status("Auditing Editorial Master...", "yellow")
        vfs_svn = self.config_factory.get_vfs_svn_name()
        worker = FetchEditStatusWorker(
            self.production_service,
            self.current_project_id,
            self.current_project_name,
            self.project_root(),
            vfs_svn,
        )
        worker.data_ready.connect(
            lambda *a, pid=self.current_project_id: self._emit_for_current_project(
                pid, self.editorial_status_loaded, *a
            )
        )
        worker.error_occurred.connect(lambda e: self.report_status(f"Edit fetch error: {e}", "red"))
        self.workers.start("edit", worker)

    def load_assets(self) -> None:
        if not self.current_project_id:
            return
        self.report_status("Auditing assets from Kitsu and SVN...", "yellow")
        vfs_svn = self.config_factory.get_vfs_svn_name()
        worker = FetchAssetsWorker(
            self.production_service, self.current_project_id, self.project_root(), vfs_svn
        )
        worker.data_ready.connect(
            lambda *a, pid=self.current_project_id: self._emit_for_current_project(
                pid, self.assets_loaded, *a
            )
        )
        worker.error_occurred.connect(lambda e: self.report_status(f"Asset fetch error: {e}", "red"))
        self.workers.start("assets", worker)

    def load_shots(self) -> None:
        if not self.current_project_id:
            return
        if self.workers.is_running("shots"):
            return
        self.report_status("Fetching pending shots from Kitsu...", "yellow")
        vfs_svn = self.config_factory.get_vfs_svn_name()
        worker = FetchShotsWorker(
            self.production_service, self.current_project_id, self.project_root(), vfs_svn
        )
        worker.data_ready.connect(
            lambda *a, pid=self.current_project_id: self._emit_for_current_project(
                pid, self.shots_loaded, *a
            )
        )
        worker.error_occurred.connect(lambda e: self.report_status(f"Shot fetch error: {e}", "red"))
        self.workers.start("shots", worker)

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

        worker = StoryboardBatchWorker(
            self.pm_core, self.config_factory, self.current_project_id, self.current_project_name, sequence_names
        )
        worker.progress_updated.connect(self.spawn_progress.emit)
        worker.log_stream.connect(self.spawn_log.emit)
        worker.finished_batch.connect(self.spawn_finished.emit)
        self.workers.start("spawn", worker, skip_if_running=False, critical=True)

    def spawn_edit_master(self) -> None:
        if not self.current_project_id:
            self.report_status("Please select a project first.", "yellow")
            return
        if not self._ensure_vcs_credentials():
            return
        self.inject_credentials()
        worker = MasterSpawningWorker(
            self.config_factory, self.current_project_name, "EDIT", self.current_project_id
        )
        worker.progress_updated.connect(self.spawn_progress.emit)
        worker.log_stream.connect(self.spawn_log.emit)
        worker.finished_spawn.connect(self.spawn_finished.emit)
        self.workers.start("spawn", worker, skip_if_running=False, critical=True)

    def spawn_batch(self, entities: list, task_types: list) -> None:
        if not self.current_project_id:
            self.report_status("Please select a project first.", "yellow")
            return
        if not self._ensure_vcs_credentials():
            return
        self.inject_credentials()
        worker = BatchCreationWorker(
            pm_core=self.pm_core,
            config_factory=self.config_factory,
            project_id=self.current_project_id,
            project_name=self.current_project_name,
            entities=entities,
            task_types=task_types,
        )
        worker.progress_updated.connect(self.spawn_progress.emit)
        worker.log_stream.connect(self.spawn_log.emit)
        worker.finished_batch.connect(self.spawn_finished.emit)
        self.workers.start("spawn", worker, skip_if_running=False, critical=True)

    # ------------------------------------------------------------------
    # Task <-> file mapping
    # ------------------------------------------------------------------
    def suggest_task_file_path(self, task: Task) -> str:
        return self.task_file_service.suggest_relative_path(task)

    def _start_task_file_worker(self, task: Task, action: str, relative_path: str = "") -> None:
        if self.workers.is_running("task_file"):
            self.report_status("Another file operation is already running...", "red")
            return
        worker = TaskFileWorker(
            service=self.task_file_service,
            task=task,
            project_root=self.project_root(),
            action=action,
            relative_path=relative_path,
        )
        worker.finished_link.connect(self._on_task_file_finished)
        self.workers.start("task_file", worker)

    def _on_task_file_finished(self, success: bool, message: str) -> None:
        self.task_file_finished.emit(success, message)

    def link_task_file(self, task: Task, relative_path: str) -> None:
        self._start_task_file_worker(task, "link", relative_path)

    def create_empty_task_file(self, task: Task, project_root: Path, relative_path: str) -> None:
        self._start_task_file_worker(task, "create_empty", relative_path)

    def unlink_task_file(self, task: Task) -> None:
        self._start_task_file_worker(task, "unlink")

    # ------------------------------------------------------------------
    # Project VCS publish (post-spawn checklist)
    # ------------------------------------------------------------------
    def request_project_publish_scan(
        self, interactive: bool = False, notify_when_clean: bool = True
    ) -> None:
        """Scan the current project for uncommitted files.

        ``project_changes_ready`` is always emitted (used to refresh the publish
        button count). When ``interactive`` the caller also gets either
        ``project_publish_dialog_requested`` or, if ``notify_when_clean``,
        ``project_publish_up_to_date``.
        """
        if not self.current_project_id:
            return
        project_root = self.project_root()
        if not project_root.exists() or self.workers.is_running("project_vcs_check"):
            return
        self._publish_scan_interactive = interactive
        self._publish_scan_notify_clean = notify_when_clean
        worker = CheckVcsChangesWorker(self.task_file_sync_service, "__project__", project_root)
        worker.changes_ready.connect(self._on_project_changes_ready)
        worker.error_occurred.connect(lambda e: self.report_status(f"VCS scan error: {e}", "red"))
        self.workers.start("project_vcs_check", worker)

    def _on_project_changes_ready(self, _task_id: str, changes: list) -> None:
        changes = list(changes or [])
        self.project_changes_ready.emit(changes)
        if not self._publish_scan_interactive:
            return
        self._publish_scan_interactive = False
        if changes:
            self.project_publish_dialog_requested.emit(changes)
        elif self._publish_scan_notify_clean:
            self.project_publish_up_to_date.emit()
        self._publish_scan_notify_clean = True

    def publish_vcs_changes(self, _card, selected_changes: list) -> bool:
        """Commit the selected project files (used by the publish checklist)."""
        if not selected_changes:
            self.report_status("No files selected for publishing.", "yellow")
            return False
        project_root = self.project_root()
        if not project_root.exists():
            self.report_status("Cannot publish: project folder is missing on NAS.", "red")
            return False
        if self.workers.is_running("vcs_publish"):
            self.report_status("A publish is already in progress...", "red")
            return False
        if not self._ensure_vcs_credentials():
            return False
        server = self._resolve_server()
        server_id = server.id if server is not None else ""
        vcs_user, vcs_pwd = ("", "")
        if self.credential_vault is not None:
            vcs_user, vcs_pwd = self.credential_vault.get_server_credentials(server_id)
        selected_paths = [change.relative_path for change in selected_changes]
        unversioned_paths = [
            change.relative_path for change in selected_changes if change.is_unversioned
        ]
        worker = PublishVcsChangesWorker(
            sync_service=self.task_file_sync_service,
            task_id="__project__",
            project_root=project_root,
            selected_paths=selected_paths,
            unversioned_paths=unversioned_paths,
            username=vcs_user or "",
            password=vcs_pwd or "",
            message=(
                f"OpenStudioHub: publish {len(selected_paths)} spawned file(s) "
                f"for {self.current_project_name}."
            ),
        )
        worker.finished_publish.connect(self._on_project_publish_finished)
        self.workers.start("vcs_publish", worker, critical=True)
        return True

    def _on_project_publish_finished(self, task_id: str, success: bool, message: str) -> None:
        self.report_status(
            ("🟢 " if success else "🔴 ") + message, "green" if success else "red"
        )
        self.vcs_publish_finished.emit(task_id, success, message)
        if success:
            # Refresh the publish button count.
            self.request_project_publish_scan()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def kitsu_assets_url(self) -> str:
        kitsu_url = self.config_factory.get_kitsu_api_url().replace("/api", "")
        return f"{kitsu_url}/productions/{self.current_project_id}/assets?search="
