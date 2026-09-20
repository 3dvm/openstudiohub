# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/task_file_workers.py
# Architectural role: Thin QThread adapter for task <-> file operations
# =========================================================================================

"""Background worker for linking/creating task files without freezing the UI."""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from src.application.services.task_file_service import TaskFileService
from src.domain.production.entities import Task


class TaskFileWorker(QThread):
    finished_link = Signal(bool, str)

    def __init__(
        self,
        service: TaskFileService,
        task: Task,
        project_root: Path,
        action: str,
        relative_path: str = "",
    ) -> None:
        super().__init__()
        self.service = service
        self.task = task
        self.project_root = project_root
        self.action = action
        self.relative_path = relative_path

    def run(self) -> None:
        try:
            if self.action == "link":
                self.service.link(self.task, self.relative_path)
                message = "Task linked to file."
            elif self.action == "create_empty":
                self.service.link_and_create_empty(self.task, self.project_root, self.relative_path)
                message = "Empty file created and linked."
            elif self.action == "unlink":
                self.service.unlink(self.task)
                message = "Task unlinked."
            else:
                raise ValueError(f"Unknown action: {self.action}")
            self.finished_link.emit(True, message)
        except Exception as error:  # noqa: BLE001
            self.finished_link.emit(False, str(error))
