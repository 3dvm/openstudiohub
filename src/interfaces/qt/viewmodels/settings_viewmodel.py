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

from src.application.services.vault_service import VaultService
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink


class SettingsViewModel(BaseViewModel):
    unsaved_changed = Signal(bool)

    def __init__(
        self,
        config_factory,
        vault_service: VaultService,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.config_factory = config_factory
        self.vault_service = vault_service

    def load_state(self) -> dict:
        """Return the data the View needs to hydrate its tabs."""
        raw = self.config_factory.get_raw_config()
        manifest = self.vault_service.load_inventory()
        return {"raw": raw, "manifest": manifest}

    def save(self, config_payload: dict, software_payload: dict) -> tuple[bool, bool]:
        config_ok = self.config_factory.guardar_configuracion(config_payload)
        vault_ok = self.vault_service.save_inventory(software_payload)
        return config_ok, vault_ok

    def export_seed(self, config_payload: dict, dest_dir: Path) -> tuple[bool, str]:
        return self.config_factory.exportar_semilla(config_payload, dest_dir)
