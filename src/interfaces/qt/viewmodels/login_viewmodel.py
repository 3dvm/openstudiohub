# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/login_viewmodel.py
# Architectural role: MVVM ViewModel / authentication
# =========================================================================================

"""ViewModel for the login view.

Owns the authentication state and the Studio Seed configuration flow. It talks
to ``AuthService`` and ``CredentialVault`` and reports results exclusively
through signals.
"""

from pathlib import Path

from PySide6.QtCore import Signal

from src.application.credential_vault import CredentialVault
from src.application.services.auth_service import AuthService
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.workers.auth_workers import LoginWorker
from src.interfaces.qt.workers.worker_manager import WorkerManager


class LoginViewModel(BaseViewModel):
    error_message = Signal(str)
    login_succeeded = Signal()
    config_state_changed = Signal(bool)  # True when a host is already configured
    host_set = Signal(str)

    def __init__(
        self,
        auth_service: AuthService,
        credential_vault: CredentialVault,
        config_factory,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.auth_service = auth_service
        self.credential_vault = credential_vault
        self.config_factory = config_factory
        self.workers = WorkerManager(self)
        self._temp_email = ""
        self._temp_password = ""

    # ------------------------------------------------------------------
    # Configuration state (Day 0 vs Day 1+)
    # ------------------------------------------------------------------
    def load_config_state(self) -> None:
        kitsu_url = self.config_factory.get_kitsu_api_url()
        has_config = bool(kitsu_url)
        if has_config:
            self.host_set.emit(kitsu_url)
        self.config_state_changed.emit(has_config)

    def import_seed(self, seed_path: Path, projects_dir: Path | None = None) -> None:
        ok = self.config_factory.import_seed(seed_path)
        if ok and projects_dir is not None:
            self.config_factory.set_local_workspace_root(projects_dir)
        if ok:
            # Rebind the vault to this machine (portable, relative to the workspace
            # root) and drop any absolute path inherited from a legacy seed.
            self.config_factory.set_vault_dir(self.config_factory.get_vault_dir())
            self.load_config_state()
            self.report_status("✓ Configuration imported successfully. You can now log in.", "green")
        else:
            self.report_status("✗ Failed to load the Seed. The file might be corrupted.", "red")

    def clear_local_config(self) -> None:
        ok = self.config_factory.purge_local_configuration()
        self.load_config_state()
        if ok:
            self.report_status("✓ Local configuration cleared.", "green")
        else:
            self.report_status("✗ Could not delete configuration file.", "red")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def login(self, email: str, password: str, host: str) -> None:
        self._temp_email = email
        self._temp_password = password

        self.set_busy(True)
        self.report_status("SYSTEM: AUTHENTICATING... PLEASE WAIT.", "yellow")

        worker = LoginWorker(self.auth_service, email, password, host)
        worker.success.connect(self._on_login_success)
        worker.error.connect(self._on_login_error)
        self.workers.start("login", worker, skip_if_running=False)

    def _on_login_success(self) -> None:
        self.set_busy(False)
        self.credential_vault.save_kitsu_credentials(self._temp_email, self._temp_password)
        self.login_succeeded.emit()

    def _on_login_error(self, message: str) -> None:
        self.set_busy(False)
        self.report_status("SYSTEM: AUTHENTICATION FAILED.", "red")
        self.error_message.emit(message)
