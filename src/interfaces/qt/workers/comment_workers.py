# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/comment_workers.py
# Architectural role: Thin QThread adapters for task comments
# =========================================================================================

"""Task-comment workers (fetch, summary and post)."""

from PySide6.QtCore import Signal

from src.application.services.production_service import ProductionService
from src.infrastructure.qt_worker import ManagedWorker


class FetchTaskCommentsWorker(ManagedWorker):
    data_ready = Signal(str, list)  # (task_id, comments)
    error_occurred = Signal(str)

    def __init__(self, production_service, task_id: str, task_ref) -> None:
        super().__init__()
        self.production_service = production_service
        self.task_id = str(task_id or "")
        self.task_ref = task_ref or task_id

    def run(self) -> None:
        try:
            comments = self.production_service.get_task_comments(self.task_ref)
            self.data_ready.emit(self.task_id, comments)
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))


class FetchProjectCommentsWorker(ManagedWorker):
    data_ready = Signal(str, list)  # (project_id, comments)
    error_occurred = Signal(str)

    def __init__(self, production_service, project_id: str, tasks: list | None = None) -> None:
        super().__init__()
        self.production_service = production_service
        self.project_id = str(project_id or "")
        self.tasks = list(tasks or [])

    def run(self) -> None:
        try:
            comments = self.production_service.get_project_comments(self.project_id)
            self.data_ready.emit(self.project_id, comments)
        except Exception as error:  # noqa: BLE001
            # Some artists can read task comments but not project comments.
            comments = _comments_per_task(self.production_service, self.tasks)
            if comments:
                self.data_ready.emit(self.project_id, comments)
            else:
                self.error_occurred.emit(str(error))


class FetchProjectsCommentsWorker(ManagedWorker):
    """Fetch comments for several projects, with a per-task fallback."""

    data_ready = Signal(dict)  # {project_id: [comments]}

    def __init__(self, production_service, projects: dict) -> None:
        super().__init__()
        self.production_service = production_service
        self.projects = dict(projects or {})

    def run(self) -> None:
        payload: dict = {}
        for project_id, tasks in self.projects.items():
            try:
                payload[project_id] = self.production_service.get_project_comments(project_id)
            except Exception:  # noqa: BLE001 - fall back to task-level comments
                payload[project_id] = _comments_per_task(
                    self.production_service, tasks
                )
        self.data_ready.emit(payload)


def _comments_per_task(production_service, tasks: list) -> list:
    comments: list = []
    for task in tasks or []:
        if not task:
            continue
        try:
            comments.extend(production_service.get_task_comments(task) or [])
        except Exception:  # noqa: BLE001 - one task must not block the rest
            continue
    return comments


class UpdateCommentChecklistWorker(ManagedWorker):
    finished_update = Signal(str, bool, str, object)  # (comment_id, ok, message, comment)

    def __init__(self, production_service, comment_id: str, checklist: list) -> None:
        super().__init__()
        self.production_service = production_service
        self.comment_id = str(comment_id or "")
        self.checklist = list(checklist or [])

    def run(self) -> None:
        try:
            updated = self.production_service.update_comment_checklist(
                self.comment_id, self.checklist
            )
            self.finished_update.emit(self.comment_id, True, "Checklist updated.", updated)
        except Exception as error:  # noqa: BLE001
            self.finished_update.emit(self.comment_id, False, str(error), None)


class PostTaskCommentWorker(ManagedWorker):
    finished_comment = Signal(str, bool, str, object)  # (task_id, ok, message, comment)

    def __init__(self, production_service, task_id: str, task_ref, status_ref, text: str) -> None:
        super().__init__()
        self.production_service = production_service
        self.task_id = str(task_id or "")
        self.task_ref = task_ref
        self.status_ref = status_ref
        self.text = text

    def run(self) -> None:
        try:
            comment = self.production_service.add_task_comment(
                self.task_ref, self.status_ref, self.text
            )
            self.finished_comment.emit(self.task_id, True, "Comment posted.", comment)
        except Exception as error:  # noqa: BLE001
            self.finished_comment.emit(self.task_id, False, str(error), None)
