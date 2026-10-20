# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/task_comments_viewmodel.py
# Architectural role: MVVM ViewModel / task comment timeline
# =========================================================================================

"""ViewModel for the task comment drawer (fetch, decorate, post, mark seen)."""

from typing import List, Optional

from PySide6.QtCore import Signal

from src.domain.production.comments import (
    comment_created_at,
    normalize_checklist,
    sort_comments,
)
from src.infrastructure.comment_read_store import CommentReadStore
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.workers.comment_workers import (
    FetchTaskCommentsWorker,
    PostTaskCommentWorker,
    UpdateCommentChecklistWorker,
)
from src.interfaces.qt.workers.worker_manager import WorkerManager


class TaskCommentsViewModel(BaseViewModel):
    comments_loaded = Signal(str, list)  # (task_id, decorated comments)
    comments_failed = Signal(str)
    comment_posted = Signal(str, bool, str)  # (task_id, ok, message)
    checklist_updating = Signal(bool)
    seen_updated = Signal(str)  # task_id (clear its badge)

    def __init__(
        self,
        production_service,
        auth_service,
        read_store: Optional[CommentReadStore] = None,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.production_service = production_service
        self.auth_service = auth_service
        self.read_store = read_store or CommentReadStore()
        self.workers = WorkerManager(self)
        self._task = None
        self._task_id = ""
        self._comments: List[dict] = []
        self._mark_seen_on_load = False
        self._person_map = None
        self._pending_load = None
        self._checklist_revert = None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def current_task_id(self) -> str:
        return self._task_id

    def current_task(self):
        return self._task

    def _user_id(self) -> str:
        user = getattr(self.auth_service, "current_user", None)
        return str(getattr(user, "id", "") or "")

    def _people(self) -> dict:
        if self._person_map is None:
            people = []
            if self.production_service is not None:
                try:
                    people = self.production_service.list_persons()
                except Exception:  # noqa: BLE001
                    people = []
            self._person_map = {str(person.get("id", "")): person for person in people or []}
        return self._person_map

    def _author_name(self, comment: dict) -> str:
        person = comment.get("person")
        if not isinstance(person, dict):
            person = self._people().get(str(comment.get("person_id") or "")) or {}
        return (
            person.get("full_name")
            or person.get("email")
            or str(comment.get("person_id") or "")
            or "Unknown"
        )

    @staticmethod
    def _created_label(comment: dict) -> str:
        created = comment_created_at(comment)
        if created is None:
            return ""
        return created.astimezone().strftime("%Y-%m-%d %H:%M")

    def _decorate(self, comments: List[dict]) -> List[dict]:
        decorated = []
        for comment in comments or []:
            item = dict(comment)
            item["_author"] = self._author_name(item)
            item["_created"] = self._created_label(item)
            status = item.get("task_status")
            item["_status"] = status.get("name", "") if isinstance(status, dict) else ""
            checklist = normalize_checklist(item.get("checklist"))
            item["_checklist"] = checklist
            item["_checklist_done"] = sum(1 for entry in checklist if entry["checked"])
            item["_checklist_total"] = len(checklist)
            decorated.append(item)
        return decorated

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def load(self, task, mark_seen: bool = False) -> None:
        if not task or self.production_service is None:
            return
        self._task = task
        self._task_id = str(task.get("id", "") or "")
        self._mark_seen_on_load = mark_seen
        self.checklist_updating.emit(False)

        if self.workers.is_running("comments_fetch"):
            self._pending_load = (task, mark_seen)
            return
        worker = FetchTaskCommentsWorker(
            self.production_service, self._task_id, self._task
        )
        worker.data_ready.connect(self._on_comments_loaded)
        worker.error_occurred.connect(self._on_comments_failed)
        self.workers.start(
            "comments_fetch", worker, on_finished=self._drain_pending_load
        )

    def _drain_pending_load(self) -> None:
        pending = self._pending_load
        self._pending_load = None
        if pending is not None:
            task, mark_seen = pending
            self.load(task, mark_seen=mark_seen)

    def _on_comments_loaded(self, task_id: str, comments: list) -> None:
        if task_id != self._task_id:
            return
        self._comments = sort_comments(comments)
        for comment in self._comments:
            comment["checklist"] = normalize_checklist(comment.get("checklist"))
        self.comments_loaded.emit(task_id, self._decorate(self._comments))
        if self._mark_seen_on_load:
            self._mark_seen_on_load = False
            self._store_seen(task_id)

    def _on_comments_failed(self, error: str) -> None:
        self.comments_failed.emit(error)

    def mark_seen(self, task_id: str = "") -> None:
        target = task_id or self._task_id
        if target and target == self._task_id:
            self._store_seen(target)

    def _store_seen(self, task_id: str) -> None:
        user_id = self._user_id()
        if not user_id:
            return
        try:
            self.read_store.mark_seen(user_id, task_id, self._comments)
        except Exception:  # noqa: BLE001 - seen state must never break the UI
            return
        self.seen_updated.emit(task_id)

    def _find_comment(self, comment_id: str):
        for comment in self._comments:
            if str(comment.get("id", "")) == str(comment_id):
                return comment
        return None

    def _emit_comments(self) -> None:
        self.comments_loaded.emit(self._task_id, self._decorate(self._comments))

    def toggle_checklist(self, comment_id: str, index: int, checked: bool) -> None:
        if self.production_service is None:
            return
        if self.workers.is_running("comment_update"):
            return
        comment = self._find_comment(comment_id)
        if comment is None:
            return

        checklist = normalize_checklist(comment.get("checklist"))
        if index < 0 or index >= len(checklist):
            return
        original = [dict(item) for item in checklist]
        checklist[index]["checked"] = bool(checked)
        comment["checklist"] = checklist
        self._checklist_revert = (str(comment_id), original)
        self._emit_comments()
        self.checklist_updating.emit(True)

        worker = UpdateCommentChecklistWorker(
            self.production_service, str(comment_id), checklist
        )
        worker.finished_update.connect(self._on_checklist_updated)
        self.workers.start("comment_update", worker)
        self.report_status("Updating checklist...", "yellow")

    def _on_checklist_updated(
        self, comment_id: str, success: bool, message: str, updated
    ) -> None:
        self.checklist_updating.emit(False)
        comment = self._find_comment(comment_id)
        revert = self._checklist_revert
        self._checklist_revert = None

        if success:
            if comment is not None and isinstance(updated, dict) and "checklist" in updated:
                comment["checklist"] = normalize_checklist(updated.get("checklist"))
            self._emit_comments()
            self.report_status("Checklist updated.", "green")
            return

        if (
            comment is not None
            and revert is not None
            and str(revert[0]) == str(comment_id)
        ):
            comment["checklist"] = [dict(item) for item in revert[1]]
        self._emit_comments()
        self.report_status(f"Checklist update failed: {message}", "red")

    def post(self, text: str, status_ref=None) -> None:
        text = (text or "").strip()
        if not text or self._task is None:
            return
        if self.workers.is_running("comments_post"):
            return

        status = status_ref
        if status is None:
            status = self.production_service.get_task_status(self._task)
        if status is None:
            self.comment_posted.emit(self._task_id, False, "Could not resolve the task status.")
            return

        worker = PostTaskCommentWorker(
            self.production_service, self._task_id, self._task, status, text
        )
        worker.finished_comment.connect(self._on_comment_posted)
        self.workers.start("comments_post", worker)
        self.report_status("Posting comment...", "yellow")

    def _on_comment_posted(self, task_id: str, success: bool, message: str, comment) -> None:
        self.comment_posted.emit(task_id, success, message)
        if not success:
            self.report_status(f"Comment failed: {message}", "red")
            return
        self.report_status("Comment posted.", "green")
        self._comments = []
        self.load(self._task, mark_seen=True)
