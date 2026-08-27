# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/vault_manager.py
# Architectural role: Software Vault inventory (facade over VaultManifestRepository)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. All rights reserved.
# License: GNU General Public License v3.0 (GPLv3)
# =========================================================================================

"""Software-vault inventory manager.

Thin facade over the single canonical ``VaultManifest`` aggregate / repository.
Kept so the settings UI consumers (``widget_settings``, ``window_new_project``,
``manifest_editor``, ``remote_explorer``) keep their existing API unchanged.
"""

from pathlib import Path

from src.domain.vault.manifest import VaultManifest
from src.infrastructure.vault_manifest_repository import FileVaultManifestRepository


class VaultManager:
    def __init__(self, config_factory) -> None:
        self.config_factory = config_factory
        self._repo = FileVaultManifestRepository(config_factory.get_vault_path())
        self._manifest = VaultManifest()

    @property
    def manifest_path(self) -> Path:
        return self._repo.path()

    def cargar_inventario(self) -> dict:
        """Load and normalize the manifest (auto-seed a default if absent)."""
        if not self.manifest_path.exists():
            print(f"[VAULT MANAGER] Manifest not found. Initializing seed at: {self.manifest_path}")
            seed = {
                "5.1.2": {
                    "categories": {
                        "templates": {
                            "Macuare_Estudio_Base": {
                                "version": "1.0",
                                "description": "Plantilla oficial generada automáticamente",
                                "mandatory": True,
                                "requires": [],
                            }
                        },
                        "addons": {},
                    }
                }
            }
            self.guardar_inventario(seed)

        self._manifest = self._repo.load()
        return self._manifest.versions

    def guardar_inventario(self, payload: dict) -> bool:
        """Persist the manifest state to the shared NAS disk."""
        try:
            self._manifest = VaultManifest.from_dict(payload)
            return self._repo.save(self._manifest)
        except Exception as error:  # noqa: BLE001
            print(f"[VAULT MANAGER ERROR] Failed to write manifest to disk: {error}")
            return False

    def obtener_datos_locales(self) -> dict:
        """Return the in-memory normalized manifest without forcing disk I/O."""
        return self._manifest.versions
