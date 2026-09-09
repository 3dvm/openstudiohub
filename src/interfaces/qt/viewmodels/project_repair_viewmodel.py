# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/project_repair_viewmodel.py
# Architectural role: MVVM ViewModel / project repair
# =========================================================================================

"""ViewModel for the project repair use case.

Orchestrates the two repair sagas (NAS Ghost / Kitsu Orphan) through the
application service, off the UI thread via ``ProjectRepairWorker``. VCS
credentials are resolved from the RAM-only ``CredentialVault`` falling back to
the development defaults.
"""

from PySide6.QtCore import Signal

from src.application.credential_vault import CredentialVault
from src.application.services.project_repair_service import ProjectRepairService
from src.domain.workspace.entities import ERROR_KITSU_ORPHAN, ERROR_NAS_GHOST
from src.infrastructure.dev_defaults import DEV_SVN_PASSWORD, DEV_SVN_USER
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.workers.project_repair_workers import ProjectRepairWorker


class ProjectRepairViewModel(BaseViewModel):
    repair_finished = Signal(bool, str)

    def __init__(
        self,
        service: ProjectRepairService,
        credential_vault: CredentialVault | None = None,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.service = service
        self.credential_vault = credential_vault
        self._worker = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_vcs_credentials(self) -> tuple[str, str]:
        user, pwd = "", ""
        if self.credential_vault is not None:
            user, pwd = self.credential_vault.get_svn_credentials()
        return user or DEV_SVN_USER, pwd or DEV_SVN_PASSWORD

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def repair_nas_ghost(self, project_name: str, template_name: str = "") -> None:
        self.report_status(f"Fixing missing Kitsu project: {project_name}...", "yellow")
        self.set_busy(True)
        self._worker = ProjectRepairWorker(
            self.service,
            ERROR_NAS_GHOST,
            project_name=project_name,
            template_name=template_name,
        )
        self._worker.result.connect(self._on_repair_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def repair_kitsu_orphan(
        self,
        project_name: str,
        kitsu_id: str,
        blueprint,
        vcs_enabled: bool = True,
    ) -> None:
        vcs_user, vcs_pwd = self._resolve_vcs_credentials()
        self.report_status(f"Recreating missing local files for: {project_name}...", "yellow")
        self.set_busy(True)
        self._worker = ProjectRepairWorker(
            self.service,
            ERROR_KITSU_ORPHAN,
            project_name=project_name,
            kitsu_id=kitsu_id,
            blueprint=blueprint,
            vcs_user=vcs_user,
            vcs_pwd=vcs_pwd,
            vcs_enabled=vcs_enabled,
        )
        self._worker.result.connect(self._on_repair_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_repair_finished(self, success: bool, message: str) -> None:
        self.set_busy(False)
        self.report_status(message, "green" if success else "red")
        self.repair_finished.emit(success, message)
