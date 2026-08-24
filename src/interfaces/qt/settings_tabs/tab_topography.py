# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/settings_tabs/tab_topography.py
# Rol Arquitectónico: UI Component / Settings Tab
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0 (Extracted from widget_settings)
# =========================================================================================

"""
Sub-vista de configuración encargada de la Topografía Semántica del Proyecto (VFS).
Aísla la UI y el mapeo de los nombres de carpetas personalizados del estudio para
hacerlos compatibles con el pipeline unificado de Blender Studio.
"""

from PySide6.QtWidgets import QWidget, QLineEdit, QFormLayout, QLabel
from PySide6.QtCore import Qt, Signal


class TabTopography(QWidget):
    # Señal para notificar cambios en caliente al orquestador padre
    modified = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_loading = True
        
        self._build_ui()
        self._conectar_senales()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(15)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        lbl_desc = QLabel(self.tr("Map Blender Studio Tool's core logic to your custom naming conventions.\nThe Hub relies on VFS Keys, allowing you to use numerical prefixes safely."))
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px; margin-bottom: 10px;")
        layout.addRow("", lbl_desc)

        # Variables Core del VFS
        self.entry_topo_svn = self._crear_input(self.tr("e.g. 02_production (Maps to 'svn')"))
        self.entry_topo_shared = self._crear_input(self.tr("e.g. 04_shared_data (Maps to 'shared')"))
        self.entry_topo_local = self._crear_input(self.tr("e.g. 06_local_cache (Maps to 'local')"))
        self.entry_topo_pipeline = self._crear_input(self.tr("e.g. 05_studio_config (Maps to 'pipeline')"))

        layout.addRow(self._styled_label(self.tr("Active Workspace [vfs_svn]:")), self.entry_topo_svn)
        layout.addRow(self._styled_label(self.tr("NAS Cache / Refs [vfs_shared]:")), self.entry_topo_shared)
        layout.addRow(self._styled_label(self.tr("Sandbox Cache [vfs_local]:")), self.entry_topo_local)
        layout.addRow(self._styled_label(self.tr("Hub Database [vfs_pipeline]:")), self.entry_topo_pipeline)

        # Carpetas Personalizadas Adicionales (Solo NAS)
        lbl_custom = QLabel(self.tr("Additional Organization Folders (NAS Only)"))
        lbl_custom.setStyleSheet("color: #F8FAFC; font-weight: bold; margin-top: 15px; margin-bottom: 5px;")
        layout.addRow("", lbl_custom)

        self.entry_topo_custom1 = self._crear_input(self.tr("e.g. 01_Brief_and_Refs"))
        self.entry_topo_custom2 = self._crear_input(self.tr("e.g. 03_renders"))

        layout.addRow(self._styled_label(self.tr("Custom Folder 1:")), self.entry_topo_custom1)
        layout.addRow(self._styled_label(self.tr("Custom Folder 2:")), self.entry_topo_custom2)

    def _crear_input(self, placeholder: str = "") -> QLineEdit:
        campo = QLineEdit()
        campo.setObjectName("FormInput")
        campo.setFixedHeight(35)
        campo.setPlaceholderText(placeholder)
        return campo

    def _styled_label(self, texto: str) -> QLabel:
        lbl = QLabel(texto)
        lbl.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 13px;")
        return lbl

    def _conectar_senales(self):
        self.entry_topo_svn.textChanged.connect(self._on_field_modified)
        self.entry_topo_shared.textChanged.connect(self._on_field_modified)
        self.entry_topo_local.textChanged.connect(self._on_field_modified)
        self.entry_topo_pipeline.textChanged.connect(self._on_field_modified)
        self.entry_topo_custom1.textChanged.connect(self._on_field_modified)
        self.entry_topo_custom2.textChanged.connect(self._on_field_modified)

    def _on_field_modified(self):
        if not self._is_loading:
            self.modified.emit()

    # ---------------------------------------------------------
    # PUBLIC API (Data-Down, Actions-Up)
    # ---------------------------------------------------------

    def cargar_datos(self, topo_config: dict):
        """Hidrata los cuadros de texto con las variables semánticas guardadas."""
        self._is_loading = True
        
        self.entry_topo_svn.setText(topo_config.get("vfs_svn", "svn"))
        self.entry_topo_shared.setText(topo_config.get("vfs_shared", "shared"))
        self.entry_topo_local.setText(topo_config.get("vfs_local", "local"))
        self.entry_topo_pipeline.setText(topo_config.get("vfs_pipeline", "pipeline"))
        
        custom_dirs = topo_config.get("custom_dirs", [])
        self.entry_topo_custom1.clear()
        self.entry_topo_custom2.clear()
        
        if len(custom_dirs) > 0:
            self.entry_topo_custom1.setText(custom_dirs[0])
        if len(custom_dirs) > 1:
            self.entry_topo_custom2.setText(custom_dirs[1])
            
        self._is_loading = False

    def get_topography_payload(self) -> dict:
        """Devuelve el sub-bloque serializable para conformar el JSON global."""
        custom_dirs = []
        if self.entry_topo_custom1.text().strip():
            custom_dirs.append(self.entry_topo_custom1.text().strip())
        if self.entry_topo_custom2.text().strip():
            custom_dirs.append(self.entry_topo_custom2.text().strip())

        return {
            "project_topography": {
                "vfs_svn": self.entry_topo_svn.text().strip() or "svn",
                "vfs_shared": self.entry_topo_shared.text().strip() or "shared",
                "vfs_local": self.entry_topo_local.text().strip() or "local",
                "vfs_pipeline": self.entry_topo_pipeline.text().strip() or "pipeline",
                "custom_dirs": custom_dirs
            }
        }
