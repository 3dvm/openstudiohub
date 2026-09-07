# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/project_audit_viewmodel.py
# Architectural role: MVVM ViewModel / project health audit (STUB)
# =========================================================================================

"""ViewModel for the project audit use case (Phase 2 wiring).

The service already exists in the application layer; this ViewModel is a stub
so the presentation layer is ready to be connected in the next phase without
breaking the current feature set.
"""

from PySide6.QtCore import Signal

from src.application.services.project_audit_service import ProjectAuditService
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink


class ProjectAuditViewModel(BaseViewModel):
    audit_completed = Signal(object)  # HubProject
    audit_failed = Signal(str)

    def __init__(
        self,
        service: ProjectAuditService,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.service = service

    def audit(self, project_name: str, kitsu_id: str = "") -> None:
        raise NotImplementedError("ProjectAuditViewModel is not wired yet (Phase 2).")
