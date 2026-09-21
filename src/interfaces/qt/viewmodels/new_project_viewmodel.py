# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/new_project_viewmodel.py
# Architectural role: MVVM ViewModel / new project dialog
# =========================================================================================

"""ViewModel for the new project dialog.

Owns the vault inventory and the project creation saga. The dialog (View)
collects the form inputs and forwards them here for the heavy I/O.
"""

from PySide6.QtCore import Signal

from src.application.credential_vault import CredentialVault
from src.application.services.creation_saga import CreationOutcome
from src.application.services.project_creation_service import ProjectCreationService
from src.application.services.production_service import ProductionService
from src.application.services.vault_service import VaultService
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.viewmodels.vcs_credential_gate import (
    VcsPrompt,
    ensure_vcs_credentials,
    vcs_requires_credentials,
)
from src.interfaces.qt.workers.new_project_workers import (
    FetchKitsuTemplatesWorker,
    ProjectCreationRetryWorker,
    ProjectCreationWorker,
    ProjectRollbackWorker,
)
from src.interfaces.qt.workers.worker_manager import WorkerManager


class NewProjectViewModel(BaseViewModel):
    templates_loaded = Signal(list)
    creation_finished = Signal(object)
    rollback_finished = Signal(bool, str)

    def __init__(
        self,
        config_factory,
        production_service: ProductionService,
        vault_service: VaultService,
        status_sink: StatusSink | None = None,
        credential_vault: CredentialVault | None = None,
        vcs_prompt: VcsPrompt | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.config_factory = config_factory
        self.production_service = production_service
        self.project_creation_service = ProjectCreationService(config_factory)
        self.vault_data = vault_service.load_inventory()
        self.credential_vault = credential_vault
        self.vcs_prompt = vcs_prompt

        self.workers = WorkerManager(self)
        self._last_outcome: CreationOutcome | None = None

    def resolve_vcs_credentials(self) -> tuple[str, str]:
        user, pwd = "", ""
        if self.credential_vault is not None:
            user, pwd = self.credential_vault.get_svn_credentials()
        return user or "", pwd or ""

    def load_templates(self) -> None:
        worker = FetchKitsuTemplatesWorker(self.production_service)
        worker.data_ready.connect(self.templates_loaded.emit)
        self.workers.start("templates", worker)

    def active_workers(self) -> list:
        """Return the currently running workers so callers can defer teardown."""
        return self.workers.active()

    def create_project(
        self,
        name: str,
        version: str,
        dependencies: dict,
        kitsu_template: str,
        splash: str,
        vcs_user: str,
        vcs_pwd: str,
        vcs_enabled: bool = True,
        addon_configuration: dict | None = None,
    ) -> None:
        required = vcs_enabled and vcs_requires_credentials(self.config_factory)
        creds = ensure_vcs_credentials(
            required=required,
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )
        if creds is None:
            outcome = CreationOutcome(
                success=False,
                message=self.tr("VCS credentials are required to create the project."),
                failed_step="credentials",
                can_retry=False,
                can_rollback=False,
            )
            self._last_outcome = outcome
            self.creation_finished.emit(outcome)
            return
        if required:
            vcs_user, vcs_pwd = creds

        self.set_busy(True)
        worker = ProjectCreationWorker(
            self.project_creation_service,
            name,
            version,
            dependencies,
            kitsu_template,
            splash,
            vcs_user,
            vcs_pwd,
            vcs_enabled=vcs_enabled,
            addon_configuration=addon_configuration,
        )
        worker.result.connect(self._on_creation_finished)
        self.workers.start("creation", worker)

    def retry_creation(self) -> None:
        """Resume the last failed creation from its recorded context."""
        outcome = self._last_outcome
        if outcome is None or not outcome.can_retry or outcome.context is None:
            return

        self.set_busy(True)
        worker = ProjectCreationRetryWorker(
            self.project_creation_service, outcome.context
        )
        worker.result.connect(self._on_creation_finished)
        self.workers.start("retry", worker)

    def rollback_creation(self) -> None:
        """Delete everything created by the last failed project creation."""
        outcome = self._last_outcome
        if outcome is None or outcome.context is None:
            return

        self.set_busy(True)
        worker = ProjectRollbackWorker(
            self.project_creation_service, outcome.context
        )
        worker.result.connect(self._on_rollback_finished)
        self.workers.start("rollback", worker)

    def _on_creation_finished(self, outcome: CreationOutcome) -> None:
        self.set_busy(False)
        self._last_outcome = outcome
        self.creation_finished.emit(outcome)

    def _on_rollback_finished(self, success: bool, message: str) -> None:
        self.set_busy(False)
        self.rollback_finished.emit(success, message)
