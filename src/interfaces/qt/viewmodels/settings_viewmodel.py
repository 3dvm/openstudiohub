# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/settings_viewmodel.py
# Architectural role: MVVM ViewModel / global settings
# =========================================================================================

"""ViewModel for the global settings panel.

The settings tabs remain thin Views (data-down/actions-up); this ViewModel
owns the load / save / export orchestration and talks to ``ConfigFactory`` and
``VaultService``.
"""

from pathlib import Path

from PySide6.QtCore import Signal

from src.application.credential_vault import CredentialVault
from src.application.services.vault_service import VaultService
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink


class SettingsViewModel(BaseViewModel):
    unsaved_changed = Signal(bool)

    def __init__(
        self,
        config_factory,
        vault_service: VaultService,
        status_sink: StatusSink | None = None,
        credential_vault: CredentialVault | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.config_factory = config_factory
        self.vault_service = vault_service
        self.credential_vault = credential_vault

    def load_state(self) -> dict:
        """Return the data the View needs to hydrate its tabs."""
        raw = self.config_factory.get_raw_config()
        manifest = self.vault_service.load_inventory()
        return {"raw": raw, "manifest": manifest}

    def save(self, config_payload: dict, software_payload: dict) -> tuple[bool, bool]:
        config_ok = self.config_factory.save_configuration(config_payload)
        vault_ok = self.vault_service.save_inventory(software_payload)
        return config_ok, vault_ok

    def export_seed(self, config_payload: dict, dest_dir: Path) -> tuple[bool, str]:
        return self.config_factory.export_seed(config_payload, dest_dir)

    # ------------------------------------------------------------------
    # Session VCS credentials (RAM-only, per server, never persisted)
    # ------------------------------------------------------------------
    def list_servers(self) -> list:
        registry = self.config_factory.get_vcs_servers()
        return [
            {**server.to_dict(), "is_default": server.id == registry.default_server_id}
            for server in registry.servers
        ]

    def load_session_credentials(self, server_id: str = "") -> tuple[str, bool]:
        if self.credential_vault is None or not server_id:
            return "", False
        username, _ = self.credential_vault.get_server_credentials(server_id)
        return username or "", self.credential_vault.is_server_enabled(server_id)

    def save_session_credentials(
        self, server_id: str, username: str, password: str, enabled: bool, ssh_passphrase: str = ""
    ) -> None:
        if self.credential_vault is None or not server_id:
            return
        self.credential_vault.save_server_credentials(
            server_id, username, password, enabled, ssh_passphrase or None
        )

    def has_ssh_passphrase(self, server_id: str = "") -> bool:
        if self.credential_vault is None or not server_id:
            return False
        return self.credential_vault.has_ssh_passphrase(server_id)
