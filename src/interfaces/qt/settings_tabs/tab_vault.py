# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/settings_tabs/tab_vault.py
# Rol Arquitectónico: UI Component / Settings Tab
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0 (Extracted from widget_settings)
# =========================================================================================

"""
Sub-vista de configuración encargada del almacenamiento físico en el NAS.
Aísla la UI y los cuadros de diálogo del sistema operativo (QFileDialog) para
el mapeo del directorio de proyectos y la bóveda de software inmutable.
"""

from pathlib import Path
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton, 
                               QLineEdit, QFormLayout, QFileDialog)
from PySide6.QtCore import Qt, QDir, Signal

class TabVault(QWidget):
    # Señal para notificar cambios en caliente al orquestador padre
    modified = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_loading = True
        
        self._build_ui()
        self._conectar_senales()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Campo de Directorio de Proyectos
        proj_layout = QHBoxLayout()
        self.entry_projects_path = self._crear_input(self.tr("e.g. Z:/studio_projects"))
        self.entry_projects_path.setReadOnly(True)
        proj_layout.addWidget(self.entry_projects_path)

        btn_browse_proj = QPushButton(self.tr("Browse..."))
        btn_browse_proj.setObjectName("SecondaryButton")
        btn_browse_proj.setFixedSize(90, 35)
        btn_browse_proj.clicked.connect(self._seleccionar_proyectos)
        proj_layout.addWidget(btn_browse_proj)

        layout.addRow(self._styled_label(self.tr("Projects Directory:")), proj_layout)

        # Campo de Directorio de la Bóveda (Vault)
        path_layout = QHBoxLayout()
        self.entry_vault_path = self._crear_input(self.tr("e.g. Z:/studio_projects/openstudio_vault"))
        self.entry_vault_path.setReadOnly(True)
        path_layout.addWidget(self.entry_vault_path)

        btn_browse_vault = QPushButton(self.tr("Browse..."))
        btn_browse_vault.setObjectName("SecondaryButton")
        btn_browse_vault.setFixedSize(90, 35)
        btn_browse_vault.clicked.connect(self._seleccionar_boveda)
        path_layout.addWidget(btn_browse_vault)

        layout.addRow(self._styled_label(self.tr("Vault Directory:")), path_layout)

        # Texto explicativo de infraestructura
        lbl_desc = QLabel(self.tr("Physical storage paths on the NAS.\nThe Projects Directory holds live production assets, while the Vault contains immutable software components and engine templates."))
        lbl_desc.setStyleSheet("color: #64748B; font-size: 12px;")
        layout.addRow("", lbl_desc)

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
        self.entry_projects_path.textChanged.connect(self._on_field_modified)
        self.entry_vault_path.textChanged.connect(self._on_field_modified)

    def _on_field_modified(self):
        if not self._is_loading:
            self.modified.emit()

    def _seleccionar_proyectos(self):
        start_dir = QDir.homePath()
        actual = self.entry_projects_path.text()
        if actual and Path(actual).exists():
            start_dir = actual
            
        dir_path = QFileDialog.getExistingDirectory(self, self.tr("Select Projects Root Directory"), start_dir)
        if dir_path:
            self.entry_projects_path.setText(dir_path)
            # Autocompletado inteligente si la bóveda está vacía
            if not self.entry_vault_path.text():
                self.entry_vault_path.setText(str(Path(dir_path) / "openstudio_vault"))

    def _seleccionar_boveda(self):
        start_dir = QDir.homePath()
        actual = self.entry_vault_path.text()
        proj_dir = self.entry_projects_path.text()
        
        if actual and Path(actual).exists():
            start_dir = str(Path(actual).parent)
        elif proj_dir and Path(proj_dir).exists():
            start_dir = proj_dir
            
        dir_path = QFileDialog.getExistingDirectory(self, self.tr("Select NAS Root (Vault)"), start_dir)
        if dir_path:
            chosen_path = Path(dir_path)
            if chosen_path.name != "openstudio_vault":
                chosen_path = chosen_path / "openstudio_vault"
                
            self.entry_vault_path.setText(str(chosen_path))

    # ---------------------------------------------------------
    # PUBLIC API (Data-Down, Actions-Up)
    # ---------------------------------------------------------

    def cargar_datos(self, projects_path: str, vault_path: str):
        """Hidrata los cuadros de texto con las rutas procesadas por el backend."""
        self._is_loading = True
        self.entry_projects_path.setText(projects_path)
        self.entry_vault_path.setText(vault_path)
        self._is_loading = False

    def get_vault_payload(self) -> dict:
        """Devuelve las variables parciales listas para la persistencia atómica."""
        return {
            "infrastructure_topology": {
                "vault_path": self.entry_vault_path.text().strip()
            },
            "vcs_engine": {
                "local_workspace_root": self.entry_projects_path.text().strip()
            }
        }
