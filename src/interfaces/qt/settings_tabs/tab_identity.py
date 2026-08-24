# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/settings_tabs/tab_identity.py
# Rol Arquitectónico: UI Component / Settings Tab
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0 (Extracted from widget_settings)
# =========================================================================================

"""
Sub-vista de configuración encargada de la Identidad del Estudio y la API.
Encapsula la interfaz y la lógica de sincronización asíncrona con Kitsu,
exponiendo métodos limpios de hidratación (cargar_datos) y extracción de payload.
"""

from pathlib import Path
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton, 
                               QLineEdit, QFormLayout, QFileDialog)
from PySide6.QtCore import Qt, QThread, Signal

class SyncIdentityWorker(QThread):
    """Worker thread to handle the Kitsu network call for organisation metadata asynchronously."""
    finished_sync = Signal(dict)

    def __init__(self, auth_manager):
        super().__init__()
        self.auth_manager = auth_manager

    def run(self):
        identity_data = self.auth_manager.sync_studio_identity()
        self.finished_sync.emit(identity_data)


class TabIdentity(QWidget):
    # Señal para notificar al orquestador padre que hay cambios sin guardar
    modified = Signal()

    def __init__(self, auth_manager, status_callback, parent=None):
        super().__init__(parent)
        self.auth_manager = auth_manager
        self.status_callback = status_callback
        
        self._is_loading = True
        self.pending_hero_image_path = None
        
        self._build_ui()
        self._conectar_senales()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Nombre del Estudio y Botón Sync
        name_layout = QHBoxLayout()
        self.entry_studio_name = self._crear_input(self.tr("e.g. Macuare Studio"))
        name_layout.addWidget(self.entry_studio_name)

        self.btn_sync_identity = QPushButton(self.tr("Sync from Kitsu"))
        self.btn_sync_identity.setObjectName("SecondaryButton")
        self.btn_sync_identity.setFixedSize(130, 35)
        self.btn_sync_identity.setCursor(Qt.PointingHandCursor)
        self.btn_sync_identity.clicked.connect(self._ejecutar_sincronizacion_identidad)
        name_layout.addWidget(self.btn_sync_identity)

        # URL de Kitsu
        self.entry_kitsu_url = self._crear_input(self.tr("e.g. https://kitsu.mydomain.com/api"))

        # Studio Hero Image
        hero_layout = QHBoxLayout()
        self.entry_hero_image = self._crear_input(self.tr("Select a PNG/JPG for the login background"))
        self.entry_hero_image.setReadOnly(True)
        hero_layout.addWidget(self.entry_hero_image)

        btn_browse_hero = QPushButton(self.tr("Browse..."))
        btn_browse_hero.setObjectName("SecondaryButton")
        btn_browse_hero.setFixedSize(90, 35)
        btn_browse_hero.clicked.connect(self._seleccionar_hero_image)
        hero_layout.addWidget(btn_browse_hero)

        # Ensamblaje en el Formulario
        layout.addRow(self._styled_label(self.tr("Studio Name:")), name_layout)
        layout.addRow(self._styled_label(self.tr("Kitsu API URL:")), self.entry_kitsu_url)
        layout.addRow(self._styled_label(self.tr("Studio Hero Image:")), hero_layout)

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
        self.entry_studio_name.textChanged.connect(self._on_field_modified)
        self.entry_kitsu_url.textChanged.connect(self._on_field_modified)

    def _on_field_modified(self):
        if not self._is_loading:
            self.modified.emit()

    def _seleccionar_hero_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select Studio Hero Image"), "", self.tr("Images (*.png *.jpg *.jpeg)")
        )
        if file_path:
            self.entry_hero_image.setText(file_path)
            self.pending_hero_image_path = Path(file_path)
            self._on_field_modified()

    def _ejecutar_sincronizacion_identidad(self):
        self.btn_sync_identity.setEnabled(False)
        self.btn_sync_identity.setText(self.tr("Syncing..."))
        self.status_callback(self.tr("Connecting to Kitsu to pull production profile..."), "yellow")

        url = self.entry_kitsu_url.text().strip()
        if url:
            self.auth_manager.set_host(url)

        self.sync_worker = SyncIdentityWorker(self.auth_manager)
        self.sync_worker.finished_sync.connect(self._on_sync_identity_finished)
        self.sync_worker.finished.connect(self.sync_worker.deleteLater)
        self.sync_worker.start()

    def _on_sync_identity_finished(self, identity_data: dict):
        self.btn_sync_identity.setEnabled(True)
        self.btn_sync_identity.setText(self.tr("Sync from Kitsu"))
        
        if identity_data and "name" in identity_data:
            self.entry_studio_name.setText(identity_data["name"])
            self.status_callback(self.tr("✓ Studio identity synchronized from Kitsu successfully."), "green")
        else:
            self.status_callback(self.tr("✗ Failed to sync identity. Verify API URL or network connection."), "red")

    # ---------------------------------------------------------
    # PUBLIC API (Data-Down, Actions-Up)
    # ---------------------------------------------------------

    def cargar_datos(self, raw_config: dict):
        """Hidrata los inputs con los datos provistos por el Orquestador."""
        self._is_loading = True
        self.entry_studio_name.setText(raw_config.get("studio_profile", {}).get("name", ""))
        self.entry_kitsu_url.setText(raw_config.get("kitsu_production", {}).get("api_url", ""))
        self._is_loading = False

    def get_identity_payload(self) -> dict:
        """Devuelve el diccionario parcial para que el Orquestador lo guarde."""
        return {
            "studio_profile": {
                "name": self.entry_studio_name.text().strip()
            },
            "kitsu_production": {
                "api_url": self.entry_kitsu_url.text().strip()
            }
        }
