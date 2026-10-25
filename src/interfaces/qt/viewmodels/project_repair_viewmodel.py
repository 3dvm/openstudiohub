# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/project_repair_viewmodel.py
# Architectural role: MVVM ViewModel / project repair
# =========================================================================================

"""ViewModel for the project repair use case.

Orchestrates the two repair sagas (NAS Ghost / Kitsu Orphan) through the
application service, off the UI thread via ``ProjectRepairWorker``. VCS
credentials are resolved from the RAM-only ``CredentialVault`` or collected
through the injected prompt before the VCS-backed repair starts.
"""

from typing import Optional

from PySide6.QtCore import Signal

from src.application.credential_vault import CredentialVault
from src.application.services.project_repair_service import ProjectRepairService
from src.domain.workspace.entities import ERROR_INVALID_BLUEPRINT, ERROR_KITSU_ORPHAN, ERROR_MISSING_BLUEPRINT, ERROR_NAS_GHOST
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.viewmodels.vcs_credential_gate import (
    VcsPrompt,
    ensure_vcs_credentials,
    vcs_requires_credentials,
)
from src.interfaces.qt.workers.project_repair_workers import ProjectRepairWorker
from src.interfaces.qt.workers.worker_manager import WorkerManager


class ProjectRepairViewModel(BaseViewModel):
    repair_finished = Signal(bool, str)

    def __init__(
        self,
        service: ProjectRepairService,
        credential_vault: CredentialVault | None = None,
        config_factory=None,
        vcs_prompt: VcsPrompt | None = None,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.service = service
        self.credential_vault = credential_vault
        self.config_factory = config_factory
        self.vcs_prompt = vcs_prompt
        self.workers = WorkerManager(self)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_vcs_credentials(self, vcs_enabled: bool, server_id: str = "") -> Optional[tuple[str, str]]:
        """Gate the VCS-backed repair behind the per-server credentials prompt."""
        server = None
        get_server = getattr(self.config_factory, "get_server", None)
        if server_id and callable(get_server):
            server = get_server(server_id)
        if server is None:
            get_default = getattr(self.config_factory, "get_default_server", None)
            server = get_default() if callable(get_default) else None
        return ensure_vcs_credentials(
            required=vcs_enabled and vcs_requires_credentials(self.config_factory, server=server),
            server_id=server.id if server is not None else "",
            server_label=server.name if server is not None else "default",
            needs_passphrase=bool(server is not None and server.is_remote),
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def is_busy(self) -> bool:
        """True while a repair worker is running."""
        return self.workers.is_running("repair")

    def _start_worker(self, worker: ProjectRepairWorker) -> bool:
        if self.is_busy():
            self.report_status("A repair is already in progress...", "red")
            return False
        worker.result.connect(self._on_repair_finished)
        self.workers.start("repair", worker, critical=True)
        return True

    def repair_nas_ghost(self, project_name: str, template_name: str = "") -> None:
        worker = ProjectRepairWorker(
            self.service,
            ERROR_NAS_GHOST,
            project_name=project_name,
            template_name=template_name,
        )
        if not self._start_worker(worker):
            return
        self.report_status(f"Fixing missing Kitsu project: {project_name}...", "yellow")
        self.set_busy(True)

    def repair_kitsu_orphan(
        self,
        project_name: str,
        kitsu_id: str,
        blueprint,
        vcs_enabled: bool = True,
    ) -> None:
        creds = self._resolve_vcs_credentials(vcs_enabled, getattr(blueprint, "vcs_server_id", ""))
        if creds is None:
            return
        vcs_user, vcs_pwd = creds
        worker = ProjectRepairWorker(
            self.service,
            ERROR_KITSU_ORPHAN,
            project_name=project_name,
            kitsu_id=kitsu_id,
            blueprint=blueprint,
            vcs_user=vcs_user,
            vcs_pwd=vcs_pwd,
            vcs_enabled=vcs_enabled,
        )
        if not self._start_worker(worker):
            return
        self.report_status(f"Recreating missing local files for: {project_name}...", "yellow")
        self.set_busy(True)

    def repair_blueprint(
        self,
        project_name: str,
        kitsu_id: str,
        blueprint,
        error_code: str = ERROR_MISSING_BLUEPRINT,
    ) -> None:
        worker = ProjectRepairWorker(
            self.service,
            error_code,
            project_name=project_name,
            kitsu_id=kitsu_id,
            blueprint=blueprint,
        )
        if not self._start_worker(worker):
            return
        self.report_status(f"Rebuilding blueprint for: {project_name}...", "yellow")
        self.set_busy(True)

    def _on_repair_finished(self, success: bool, message: str) -> None:
        self.set_busy(False)
        self.report_status(message, "green" if success else "red")
        self.repair_finished.emit(success, message)
