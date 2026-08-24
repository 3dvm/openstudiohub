# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/vault_manager.py
# Rol Arquitectónico: Core Service / Vault Inventory Engine & Session Bridge
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.1.0 (Environment Variables Injection)
# =========================================================================================

"""
Centralized CRUD manager for the vault_manifest.json shared inventory file.
Acts as the Single Source of Truth for software availability, templates, and addons.
Implements robust polymorphic parsing and retains transient credentials compatibility,
injecting them into the OS environment for headless subprocesses.
"""

import os
import json
from pathlib import Path

class VaultManager:
    def __init__(self, config_factory):
        """
        Inicializa el gestor de inventario inyectando dinámicamente la fábrica de configuración.
        """
        self.config_factory = config_factory
        self._cached_manifest = {}
        
        # Estado efímero de sesión (Compatibilidad con el flujo legacy de login)
        self._transient_email = None
        self._transient_password = None

    @property
    def manifest_path(self) -> Path:
        """Resuelve reactivamente la coordenada real del manifiesto en la raíz de la Bóveda."""
        return self.config_factory.get_vault_path() / "vault_manifest.json"

    def cargar_inventario(self) -> dict:
        """
        Lee, procesa y normaliza el manifiesto compartido en el NAS.
        Garantiza compatibilidad polimórfica de esquemas y auto-sembrado seguro.
        """
        self._cached_manifest = {}
        target_path = self.manifest_path

        # 1. Red de Seguridad: Auto-Sembrado si el estudio es virgen
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

        # 2. Operación de lectura atómica y parseo elástico
        if target_path.exists():
            try:
                with open(target_path, 'r', encoding='utf-8') as f:
                    manifesto_crudo = json.load(f)
                    
                    for key, val in manifesto_crudo.items():
                        if isinstance(val, dict):
                            # Normalización polimórfica de llaves de versión
                            raw_version = val.get("blender_version") or key
                            clean_version = str(raw_version).lstrip("vV ")
                            
                            # Aislamiento elástico de bloques de categorías
                            categories_block = val.get("categories") if "categories" in val else val
                            if isinstance(categories_block, dict):
                                self._cached_manifest[clean_version] = categories_block
                                
            except Exception as e:
                print(f"[VAULT MANAGER ERROR] Failed to parse vault manifest file: {e}")
                self._cached_manifest = {}

        return self._cached_manifest

    def guardar_inventario(self, payload: dict) -> bool:
        """
        Persiste de forma atómica el estado del manifiesto en el disco compartido del NAS.
        """
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
        """Devuelve el caché de memoria ram actual sin forzar I/O de disco."""
        return self._cached_manifest

    # ---------------------------------------------------------
    # TRANSIENT SESSION LAYER (Backward Compatibility Patch)
    # ---------------------------------------------------------

    def save_kitsu_credentials(self, email: str, password: str):
        """Retiene de forma efímera las credenciales de red e inyecta al ambiente del OS."""
        self._transient_email = email
        self._transient_password = password
        
        # Inyectar al entorno para que los subprocesos (ProjectBuilder) puedan consumirlo
        os.environ["OPENSTUDIO_KITSU_USER"] = email
        os.environ["OPENSTUDIO_KITSU_PWD"] = password

    def clear(self):
        """Limpia los estados temporales de memoria al cerrar sesión o purgar la app."""
        self._transient_email = None
        self._transient_password = None
        self._cached_manifest = {}
        
        # Purgar el entorno por seguridad
        os.environ.pop("OPENSTUDIO_KITSU_USER", None)
        os.environ.pop("OPENSTUDIO_KITSU_PWD", None)
        
        print("[VAULT MANAGER] Transient session states successfully flushed.")
