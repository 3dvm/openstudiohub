# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/project_repair_workers.py
# Architectural role: Thin QThread adapters for the project repair flow
# =========================================================================================

"""Project repair workers (heavy repair I/O off the UI thread)."""

from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker

from src.application.services.project_repair_service import ProjectRepairService
from src.domain.workspace.entities import ERROR_INVALID_BLUEPRINT, ERROR_KITSU_ORPHAN, ERROR_MISSING_BLUEPRINT, ERROR_NAS_GHOST


class ProjectRepairWorker(ManagedWorker):
    """Runs the repair saga for a single damaged project without freezing the UI."""

    result = Signal(bool, str)

    def __init__(
        self,
        service: ProjectRepairService,
        repair_type: str,
        project_name: str = "",
        template_name: str = "",
        kitsu_id: str = "",
        blueprint=None,
        vcs_user: str = "",
        vcs_pwd: str = "",
        vcs_enabled: bool = True,
    ) -> None:
        super().__init__()
        self.service = service
        self.repair_type = repair_type
        self.project_name = project_name
        self.template_name = template_name
        self.kitsu_id = kitsu_id
        self.blueprint = blueprint
        self.vcs_user = vcs_user
        self.vcs_pwd = vcs_pwd
        self.vcs_enabled = vcs_enabled

    def run(self) -> None:
        try:
            if self.repair_type == ERROR_NAS_GHOST:
                ok, msg = self.service.fix_nas_ghost(self.project_name, self.template_name)
            elif self.repair_type == ERROR_KITSU_ORPHAN:
                ok, msg = self.service.fix_kitsu_orphan(
                    self.project_name,
                    self.kitsu_id,
                    self.blueprint,
                    self.vcs_user,
                    self.vcs_pwd,
                    self.vcs_enabled,
                )
            elif self.repair_type in (ERROR_MISSING_BLUEPRINT, ERROR_INVALID_BLUEPRINT):
                ok, msg = self.service.fix_blueprint(
                    self.project_name,
                    self.kitsu_id,
                    self.blueprint,
                )
            else:
                ok, msg = False, f"Unknown repair type: {self.repair_type}"
        except Exception as error:  # noqa: BLE001
            ok, msg = False, f"Repair failed: {str(error)}"

        self.result.emit(ok, msg)
