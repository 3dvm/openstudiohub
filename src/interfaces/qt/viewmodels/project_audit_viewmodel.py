# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/project_audit_viewmodel.py
# Architectural role: MVVM ViewModel / project health audit
# =========================================================================================

"""ViewModel for the project audit use case.

Runs ``ProjectAuditService.audit_project`` off the UI thread through
``ProjectAuditWorker`` and re-emits one ``HubProject`` per audited project, so
the project grid can refresh each card as its health is resolved.

A monotonic ``token`` tags every audit batch. Since a grid re-render can arrive
while a previous audit is still running, the newest request is queued and the
stale batch's results are identifiable by their token on the view side.
"""

from PySide6.QtCore import Signal

from src.application.services.project_audit_service import ProjectAuditService
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.workers.project_audit_workers import ProjectAuditWorker


class ProjectAuditViewModel(BaseViewModel):
    audit_completed = Signal(int, object, object)  # (token, project_data: dict, hub_project)
    audit_finished = Signal()
    audit_failed = Signal(str)

    def __init__(
        self,
        service: ProjectAuditService,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.service = service
        self._worker = None
        self._queued = None

    def is_busy(self) -> bool:
        """True while an audit worker is running."""
        return self._worker is not None and self._worker.isRunning()

    def audit_projects(self, projects_data: list, token: int = 0) -> None:
        """Audit a batch of raw project dicts, emitting results incrementally.

        If an audit is already running, the newest request is queued and starts
        as soon as the current batch finishes.
        """
        if self.is_busy():
            self._queued = (list(projects_data), token)
            return
        self._start(projects_data, token)

    def audit(self, project_name: str, kitsu_id: str = "") -> None:
        """Audit a single project by name/id."""
        self.audit_projects([{"name": project_name, "id": kitsu_id}])

    def _start(self, projects_data: list, token: int) -> None:
        self._worker = ProjectAuditWorker(self.service, projects_data, token)
        self._worker.project_audited.connect(self.audit_completed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        self._worker = None
        self.audit_finished.emit()

        if self._queued is not None:
            projects_data, token = self._queued
            self._queued = None
            self._start(projects_data, token)
