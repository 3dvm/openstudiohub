# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/vcs_history_workers.py
# Architectural role: UI workers / VCS history, diff and revision export
# =========================================================================================

"""Background workers for the VCS history viewer."""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal

from src.application.services.task_file_sync_service import TaskFileSyncService
from src.infrastructure.qt_worker import ManagedWorker


class FetchVcsHistoryWorker(ManagedWorker):
    """Fetch the revision log for a task file."""

    history_ready = Signal(str, list)  # (task_id, revisions)
    error_occurred = Signal(str)

    def __init__(
        self,
        sync_service: TaskFileSyncService,
        task_id: str,
        project_root: Path,
        relative_path: str,
        limit: int = 20,
        username: str = "",
        password: str = "",
    ) -> None:
        super().__init__()
        self.sync_service = sync_service
        self.task_id = str(task_id)
        self.project_root = project_root
        self.relative_path = relative_path
        self.limit = limit
        self.username = username
        self.password = password

    def run(self) -> None:
        try:
            revisions = self.sync_service.get_file_history(
                self.project_root,
                self.relative_path,
                self.limit,
                self.username,
                self.password,
            )
            self.history_ready.emit(self.task_id, revisions)
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))


class FetchVcsDiffWorker(ManagedWorker):
    """Fetch a textual diff for one revision."""

    diff_ready = Signal(str, str, str)  # (task_id, revision, diff)
    error_occurred = Signal(str)

    def __init__(
        self,
        sync_service: TaskFileSyncService,
        task_id: str,
        project_root: Path,
        relative_path: str,
        revision: Optional[int] = None,
        username: str = "",
        password: str = "",
    ) -> None:
        super().__init__()
        self.sync_service = sync_service
        self.task_id = str(task_id)
        self.project_root = project_root
        self.relative_path = relative_path
        self.revision = revision
        self.username = username
        self.password = password

    def run(self) -> None:
        try:
            diff = self.sync_service.get_file_diff(
                self.project_root,
                self.relative_path,
                self.revision,
                self.username,
                self.password,
            )
            self.diff_ready.emit(
                self.task_id,
                "" if self.revision is None else str(self.revision),
                diff,
            )
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))


class ExportVcsRevisionWorker(ManagedWorker):
    """Export one historical revision to a user-selected file."""

    export_finished = Signal(str, bool, str)  # (task_id, success, message)

    def __init__(
        self,
        sync_service: TaskFileSyncService,
        task_id: str,
        project_root: Path,
        relative_path: str,
        revision: int,
        destination: Path,
        username: str = "",
        password: str = "",
    ) -> None:
        super().__init__()
        self.sync_service = sync_service
        self.task_id = str(task_id)
        self.project_root = project_root
        self.relative_path = relative_path
        self.revision = revision
        self.destination = destination
        self.username = username
        self.password = password

    def run(self) -> None:
        try:
            success, message = self.sync_service.export_file_revision(
                self.project_root,
                self.relative_path,
                self.revision,
                self.destination,
                self.username,
                self.password,
            )
        except Exception as error:  # noqa: BLE001
            success, message = False, str(error)
        self.export_finished.emit(self.task_id, success, message)
