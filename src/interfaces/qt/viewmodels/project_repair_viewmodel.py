# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/project_repair_viewmodel.py
# Architectural role: MVVM ViewModel / project repair (STUB)
# =========================================================================================

"""ViewModel for the project repair use case (Phase 2 wiring).

The service already exists in the application layer; this ViewModel is a stub
so the presentation layer is ready to be connected in the next phase without
breaking the current feature set.
"""

from PySide6.QtCore import Signal

from src.application.services.project_repair_service import ProjectRepairService
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink


class ProjectRepairViewModel(BaseViewModel):
    repair_completed = Signal(bool, str)

    def __init__(
        self,
        service: ProjectRepairService,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.service = service

    def fix_nas_ghost(self, project_name: str, blender_version: str, blueprint) -> None:
        raise NotImplementedError("ProjectRepairViewModel is not wired yet (Phase 2).")

    def fix_kitsu_orphan(self, project_name: str, kitsu_id: str, blueprint, vcs_user: str, vcs_pwd: str) -> None:
        raise NotImplementedError("ProjectRepairViewModel is not wired yet (Phase 2).")
