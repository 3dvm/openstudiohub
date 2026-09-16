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
    ProjectCreationWorker,
)


class NewProjectViewModel(BaseViewModel):
    templates_loaded = Signal(list)
    creation_finished = Signal(bool, str)

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

        self._worker = None

    def resolve_vcs_credentials(self) -> tuple[str, str]:
        user, pwd = "", ""
        if self.credential_vault is not None:
            user, pwd = self.credential_vault.get_svn_credentials()
        return user or "", pwd or ""

    def load_templates(self) -> None:
        self._templates_worker = FetchKitsuTemplatesWorker(self.production_service)
        self._templates_worker.data_ready.connect(self.templates_loaded.emit)
        self._templates_worker.finished.connect(self._on_templates_worker_finished)
        self._templates_worker.start()

    def _on_templates_worker_finished(self) -> None:
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        self._templates_worker = None

    def active_workers(self) -> list:
        """Return the currently running workers so callers can defer teardown."""
        workers = []
        if self._templates_worker is not None and self._templates_worker.isRunning():
            workers.append(self._templates_worker)
        if self._worker is not None and self._worker.isRunning():
            workers.append(self._worker)
        return workers

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
            self.creation_finished.emit(False, self.tr("VCS credentials are required to create the project."))
            return
        if required:
            vcs_user, vcs_pwd = creds

        self.set_busy(True)
        self._worker = ProjectCreationWorker(
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
        self._worker.result.connect(self._on_creation_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_creation_finished(self, success: bool, message: str) -> None:
        self.set_busy(False)
        self.creation_finished.emit(success, message)
