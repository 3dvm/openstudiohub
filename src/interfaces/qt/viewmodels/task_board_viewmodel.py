# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/task_board_viewmodel.py
# Architectural role: MVVM ViewModel / PM-TD project task board
# =========================================================================================

"""ViewModel for the PM/TD task board (project tasks, comments and assignment)."""

from typing import List, Optional

from PySide6.QtCore import Signal

from src.domain.production.comments import (
    comment_task_id,
    newest_comment_timestamp,
    to_iso,
    unread_comment_count,
)
from src.infrastructure.comment_read_store import CommentReadStore
from src.infrastructure.ui_prefs_store import UiPrefsStore
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.viewmodels.task_comments_viewmodel import TaskCommentsViewModel
from src.interfaces.qt.workers.comment_workers import FetchProjectsCommentsWorker
from src.interfaces.qt.workers.task_board_workers import (
    AssignTaskWorker,
    FetchPersonsWorker,
    FetchProjectTaskBoardWorker,
    FetchProjectsWorker,
)
from src.interfaces.qt.workers.worker_manager import WorkerManager


class TaskBoardViewModel(BaseViewModel):
    projects_loaded = Signal(list)
    tasks_loaded = Signal(str, list)  # (project_id, tasks)
    persons_loaded = Signal(list)
    comment_counts_ready = Signal(dict)  # {task_id: {total, unread}}
    assignment_finished = Signal(str, bool, str)
    view_mode_changed = Signal(str)

    VIEW_KEY = "task_board_view"
    COMMENT_WIDTH_KEY = "comment_panel_width"
    DEFAULT_COMMENT_WIDTH = 360
    MIN_COMMENT_WIDTH = 240
    MAX_COMMENT_WIDTH = 900

    def __init__(
        self,
        production_service,
        auth_service,
        read_store: Optional[CommentReadStore] = None,
        prefs_store: Optional[UiPrefsStore] = None,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.production_service = production_service
        self.auth_service = auth_service
        self.read_store = read_store or CommentReadStore()
        self.prefs_store = prefs_store or UiPrefsStore()
        self.comments = TaskCommentsViewModel(
            production_service,
            auth_service,
            read_store=self.read_store,
            status_sink=status_sink,
        )
        self.workers = WorkerManager(self)

        self._projects: List[dict] = []
        self._tasks: List[dict] = []
        self._persons: List[dict] = []
        self._current_project_id = ""
        self._pending_tasks_project_id = ""
        self._pending_comments_project_id = ""
        self.view_mode = str(self.prefs_store.get(self._user_id(), self.VIEW_KEY, "table"))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @property
    def token(self) -> str:
        return self.auth_service.access_token() if self.auth_service else ""

    @property
    def host(self) -> str:
        return self.auth_service.host if self.auth_service else ""

    @property
    def current_project_id(self) -> str:
        return self._current_project_id

    @property
    def projects(self) -> List[dict]:
        return list(self._projects)

    @property
    def tasks(self) -> List[dict]:
        return list(self._tasks)

    @property
    def persons(self) -> List[dict]:
        return list(self._persons)

    def _user_id(self) -> str:
        user = getattr(self.auth_service, "current_user", None)
        return str(getattr(user, "id", "") or "")

    def assignment_allowed(self) -> bool:
        """Only PMs (managers) may edit assignees; TD is read-only."""
        try:
            return self.auth_service.current_role().value == "manager"
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_projects(self) -> None:
        if self.production_service is None or self.workers.is_running("projects"):
            return
        worker = FetchProjectsWorker(self.production_service)
        worker.data_ready.connect(self._on_projects_loaded)
        self.workers.start("projects", worker)

    def _on_projects_loaded(self, projects: list) -> None:
        self._projects = projects or []
        self.projects_loaded.emit(self._projects)

    def select_project(self, project_id: str) -> None:
        self._current_project_id = str(project_id or "")
        self.load_tasks(self._current_project_id)
        self.load_persons()

    def load_tasks(self, project_id: str = "") -> None:
        if self.production_service is None or not project_id:
            return
        if self.workers.is_running("tasks"):
            self._pending_tasks_project_id = project_id
            return
        worker = FetchProjectTaskBoardWorker(self.production_service, project_id)
        worker.data_ready.connect(self._on_tasks_loaded)
        self.workers.start("tasks", worker, on_finished=self._drain_pending_tasks)

    def _drain_pending_tasks(self) -> None:
        project_id = self._pending_tasks_project_id
        self._pending_tasks_project_id = ""
        if project_id:
            self.load_tasks(project_id)

    def _on_tasks_loaded(self, project_id: str, tasks: list) -> None:
        if project_id != self._current_project_id:
            return
        self._tasks = tasks or []
        self.tasks_loaded.emit(project_id, self._tasks)
        self.load_comment_counts(project_id)

    def load_persons(self) -> None:
        if self.production_service is None:
            return
        if self._persons:
            self.persons_loaded.emit(self._persons)
            return
        if self.workers.is_running("persons"):
            return
        worker = FetchPersonsWorker(self.production_service)
        worker.data_ready.connect(self._on_persons_loaded)
        self.workers.start("persons", worker)

    def _on_persons_loaded(self, persons: list) -> None:
        self._persons = persons or []
        self.persons_loaded.emit(self._persons)

    # ------------------------------------------------------------------
    # Comment badges
    # ------------------------------------------------------------------
    def load_comment_counts(self, project_id: str = "") -> None:
        if self.production_service is None or self.workers.is_running("comments"):
            return
        target = project_id or self._current_project_id
        if not target:
            return
        if self.workers.is_running("comments"):
            self._pending_comments_project_id = target
            return
        worker = FetchProjectsCommentsWorker(
            self.production_service, {target: list(self._tasks)}
        )
        worker.data_ready.connect(self._on_projects_comments)
        self.workers.start("comments", worker, on_finished=self._drain_pending_comments)

    def _on_projects_comments(self, payload: dict) -> None:
        for project_id, comments in (payload or {}).items():
            self._on_project_comments(project_id, comments)

    def _drain_pending_comments(self) -> None:
        project_id = self._pending_comments_project_id
        self._pending_comments_project_id = ""
        if project_id:
            self.load_comment_counts(project_id)

    def _on_project_comments(self, project_id: str, comments: list) -> None:
        if project_id != self._current_project_id:
            return
        user_id = self._user_id()
        by_task: dict = {}
        for comment in comments or []:
            task_id = comment_task_id(comment)
            if task_id:
                by_task.setdefault(task_id, []).append(comment)

        counts: dict = {}
        for task in self._tasks:
            task_id = str(task.get("id", ""))
            task_comments = by_task.get(task_id, [])
            last_seen = self.read_store.get_last_seen(user_id, task_id) if user_id else None
            if task_comments and last_seen is None:
                newest = newest_comment_timestamp(task_comments)
                if user_id and newest is not None:
                    self.read_store.set_last_seen(user_id, task_id, to_iso(newest))
                unread = 0
            else:
                unread = unread_comment_count(task_comments, user_id, last_seen)
            task["_comment_count"] = len(task_comments)
            task["_unread_count"] = unread
            counts[task_id] = {"total": len(task_comments), "unread": unread}

        self.comment_counts_ready.emit(counts)

    # ------------------------------------------------------------------
    # View mode
    # ------------------------------------------------------------------
    def set_view_mode(self, mode: str) -> None:
        mode = "cards" if str(mode) == "cards" else "table"
        if mode == self.view_mode:
            return
        self.view_mode = mode
        try:
            self.prefs_store.set(self._user_id(), self.VIEW_KEY, mode)
        except Exception:  # noqa: BLE001 - preference persistence is best-effort
            pass
        self.view_mode_changed.emit(mode)

    def comment_panel_width(self) -> int:
        try:
            value = int(
                self.prefs_store.get(
                    self._user_id(),
                    self.COMMENT_WIDTH_KEY,
                    self.DEFAULT_COMMENT_WIDTH,
                )
            )
        except (TypeError, ValueError):
            value = self.DEFAULT_COMMENT_WIDTH
        return max(self.MIN_COMMENT_WIDTH, min(value, self.MAX_COMMENT_WIDTH))

    def set_comment_panel_width(self, width: int) -> None:
        try:
            self.prefs_store.set(
                self._user_id(),
                self.COMMENT_WIDTH_KEY,
                max(self.MIN_COMMENT_WIDTH, min(int(width), self.MAX_COMMENT_WIDTH)),
            )
        except Exception:  # noqa: BLE001 - preference persistence is best-effort
            pass

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------
    def apply_assignees(self, task: dict, add_ids: list, remove_ids: list) -> None:
        if not self.assignment_allowed():
            self.assignment_finished.emit(str(task.get("id", "")), False, "Only PMs can assign tasks.")
            return
        if self.production_service is None or self.workers.is_running("assign"):
            return
        worker = AssignTaskWorker(
            self.production_service,
            str(task.get("id", "")),
            task,
            add_ids,
            remove_ids,
        )
        worker.finished_assign.connect(self._on_assignment_finished)
        self.workers.start("assign", worker)
        self.report_status("Updating assignees...", "yellow")

    def _on_assignment_finished(
        self, task_id: str, success: bool, message: str, assignees: list
    ) -> None:
        if success:
            for task in self._tasks:
                if str(task.get("id", "")) == str(task_id):
                    task["assignees"] = assignees
                    break
            self.report_status("Assignees updated.", "green")
        else:
            self.report_status(f"Assignee update failed: {message}", "red")
        self.assignment_finished.emit(task_id, success, message)
