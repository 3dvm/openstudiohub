# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/settings_tabs/tab_software.py
# Rol Arquitectónico: UI Component / Software Provisioning Coordinator
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.6.0 (Pure Coordinator Pattern)
# =========================================================================================

import re
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PySide6.QtCore import Signal

from src.interfaces.qt.settings_tabs.software_components.remote_explorer import RemoteExplorerWidget
from src.interfaces.qt.settings_tabs.software_components.manifest_editor import ManifestEditorWidget

class TabSoftware(QWidget):
    modified = Signal()

    def __init__(self, parent, vault_manager, status_callback):
        super().__init__(parent)
        self.vault_manager = vault_manager
        self.status_callback = status_callback
        
        self._build_ui()
        self._conectar_modulos()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(20)

        # --- División Vertical / Horizontal según el espacio ---
        split_layout = QHBoxLayout()
        split_layout.setSpacing(20)

        # 1. Explorador Remoto (Descargas de Blender)
        self.remote_explorer = RemoteExplorerWidget(self, self.vault_manager, self.status_callback)
        split_layout.addWidget(self.remote_explorer, stretch=1)

        # 2. Editor del Manifiesto (Dependencias y Add-ons)
        self.manifest_editor = ManifestEditorWidget(self, self.vault_manager, self.status_callback)
        split_layout.addWidget(self.manifest_editor, stretch=1)

        main_layout.addLayout(split_layout)

    def _conectar_modulos(self):
        """Conecta las señales entre los submódulos y el orquestador."""
        # Si el explorador remoto descarga un Blender nuevo, notificar al editor del manifiesto
        self.remote_explorer.download_finished.connect(self._on_blender_downloaded)
        
        # Burbujear la señal de "cambios sin guardar" hacia arriba
        self.manifest_editor.modified.connect(self.modified.emit)

    def _on_blender_downloaded(self, exito: bool, filename: str):
        """Atrapa la descarga exitosa e inyecta la nueva versión en el manifiesto."""
        if exito and filename:
            match = re.search(r'blender-(\d+\.\d+\.\d+)', filename.lower())
            detected_version = match.group(1) if match else "4.2.0"
            
            # Forzamos la inyección en el diccionario del Manifest Editor
            if detected_version not in self.manifest_editor.manifest_data:
                self.manifest_editor.manifest_data[detected_version] = {"addons": {}, "templates": {}}
                self.modified.emit()
            
            # Recargamos la lista del combobox y auto-seleccionamos la recién descargada
            lista_versiones = list(self.manifest_editor.manifest_data.keys())
            self.manifest_editor.set_versiones_disponibles(lista_versiones, auto_select=detected_version)

    # ---------------------------------------------------------
    # PUBLIC API (Exigida por SettingsWidget)
    # ---------------------------------------------------------
    def cargar_datos(self, manifest_config: dict):
        """Recibe el JSON de la bóveda e hidrata el Manifest Editor."""
        self.manifest_editor._is_loading = True
        self.manifest_editor.manifest_data = {}

        for key, val in manifest_config.items():
            if isinstance(val, dict):
                raw_version = val.get("blender_version") or key
                clean_version = str(raw_version).lstrip("vV ")
                
                categories_block = val.get("categories") if "categories" in val else val
                if isinstance(categories_block, dict):
                    self.manifest_editor.manifest_data[clean_version] = categories_block

        lista_versiones = list(self.manifest_editor.manifest_data.keys())
        self.manifest_editor.set_versiones_disponibles(lista_versiones)
        self.manifest_editor._is_loading = False

    def get_software_payload(self) -> dict:
        """Extrae el estado del árbol de UI para empaquetarlo en el JSON a guardar."""
        full_payload = {}
        for version, categories in self.manifest_editor.manifest_data.items():
            full_payload[version] = {
                "blender_version": version,
                "categories": categories
            }
        return full_payload
