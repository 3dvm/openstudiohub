# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/vault_manager.py
# Architectural role: Software Vault inventory (manifest CRUD)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. All rights reserved.
# License: GNU General Public License v3.0 (GPLv3)
# =========================================================================================

"""
Software-vault inventory manager (vault_manifest.json CRUD).

NOTE: the transient-credential responsibilities that used to live here were
extracted into ``src/application/credential_vault.py``. This class now only
manages the shared software inventory (Blender versions, add-ons, templates).
"""

import json
from pathlib import Path


class VaultManager:
    def __init__(self, config_factory) -> None:
        self.config_factory = config_factory
        self._cached_manifest = {}

    @property
    def manifest_path(self) -> Path:
        """Resolve the manifest location at the root of the Vault."""
        return self.config_factory.get_vault_path() / "vault_manifest.json"

    def cargar_inventario(self) -> dict:
        """Read, normalize, and cache the shared NAS manifest (auto-seeds if absent)."""
        self._cached_manifest = {}
        target_path = self.manifest_path

        if not target_path.exists():
            print(f"[VAULT MANAGER] Manifest not found. Initializing seed at: {target_path}")
            target_path.parent.mkdir(parents=True, exist_ok=True)

            esqueleto_base = {
                "5.1.2": {
                    "categories": {
                        "templates": {
                            "Macuare_Estudio_Base": {
                                "version": "1.0",
                                "description": "Plantilla oficial generada automáticamente",
                                "mandatory": True,
                                "requires": []
                            }
                        },
                        "addons": {}
                    }
                }
            }
            try:
                self.guardar_inventario(esqueleto_base)
            except Exception as e:
                print(f"[VAULT MANAGER ERROR] Critical failure during auto-seeding: {e}")

        if target_path.exists():
            try:
                with open(target_path, 'r', encoding='utf-8') as f:
                    manifesto_crudo = json.load(f)

                for key, val in manifesto_crudo.items():
                    if isinstance(val, dict):
                        raw_version = val.get("blender_version") or key
                        clean_version = str(raw_version).lstrip("vV ")

                        categories_block = val.get("categories") if "categories" in val else val
                        if isinstance(categories_block, dict):
                            self._cached_manifest[clean_version] = categories_block
            except Exception as e:
                print(f"[VAULT MANAGER ERROR] Failed to parse vault manifest file: {e}")
                self._cached_manifest = {}

        return self._cached_manifest

    def guardar_inventario(self, payload: dict) -> bool:
        """Persist the manifest state to the shared NAS disk."""
        try:
            target_path = self.manifest_path
            target_path.parent.mkdir(parents=True, exist_ok=True)

            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[VAULT MANAGER ERROR] Failed to write manifest to disk: {e}")
            return False

    def obtener_datos_locales(self) -> dict:
        """Return the in-memory manifest cache without forcing disk I/O."""
        return self._cached_manifest
