# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/widget_settings.py
# Rol Arquitectónico: UI Orchestrator / Global Settings Container (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.7.0 (Top Compact Tabs Layout)
# =========================================================================================

"""
Global Configuration Panel for the Technical Director.
Groups decoupled molecular sub-tabs (Identity, Vault, VCS, Topography, Software).
Coordinates atomic payload assembly and routes data via ConfigFactory and VaultManager.
Uses a compact top-tab layout to maximize vertical screen real estate.
"""

import shutil
from pathlib import Path
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QStackedWidget, QFileDialog)
from PySide6.QtCore import Qt, QDir

from src.interfaces.qt.settings_tabs.tab_identity import TabIdentity
from src.interfaces.qt.settings_tabs.tab_vault import TabVault
from src.interfaces.qt.settings_tabs.tab_vcs import TabVCS
from src.interfaces.qt.settings_tabs.tab_topography import TabTopography
from src.interfaces.qt.settings_tabs.tab_software import TabSoftware
from src.application.vault_manager import VaultManager

class SettingsWidget(QFrame):
    def __init__(self, parent, config_factory, auth_manager, status_callback, **kwargs):
        super().__init__(parent, **kwargs)
        self.config_factory = config_factory
        self.auth_manager = auth_manager
        self.status_callback = status_callback
        
        self.vault_manager = VaultManager(self.config_factory)
        
        self.setObjectName("SettingsWidgetBase")
        self.nav_buttons = {}
        
        self._build_ui()
        self._conectar_senales_cambio()
        self._cargar_datos_actuales()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        # Márgenes en cero para pegar la barra de pestañas al TopBar principal
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. TOP TAB BAR (Estilo VSCode/Editor)
        self.tab_bar_frame = QFrame()
        self.tab_bar_frame.setStyleSheet("background-color: #1F2531; border-bottom: 1px solid #141820;")
        self.tab_bar_frame.setFixedHeight(35)
        
        self.tab_bar_layout = QHBoxLayout(self.tab_bar_frame)
        self.tab_bar_layout.setContentsMargins(15, 0, 15, 0)
        self.tab_bar_layout.setSpacing(2)

        # Indicador de cambios sin guardar
        self.lbl_unsaved_warning = QLabel("")

        # 2. CONTENT STACK
        self.stack = QStackedWidget()
        
        # 3. INSTANCIACIÓN MOLECULAR
        self.tab_identidad = TabIdentity(self.auth_manager, self.status_callback, parent=self.stack)
        self.tab_boveda = TabVault(parent=self.stack)
        self.tab_vcs = TabVCS(parent=self.stack)
        self.tab_topo = TabTopography(parent=self.stack)
        self.tab_software = TabSoftware(self.stack, self.vault_manager, self.status_callback)

        # Añadir al Stack y generar pestañas superiores
        self._add_nav_item(self.tr("Identity and API"), self.tab_identidad, 0)
        self._add_nav_item(self.tr("Vault Storage"), self.tab_boveda, 1)
        self._add_nav_item(self.tr("Pipeline and VCS"), self.tab_vcs, 2)
        self._add_nav_item(self.tr("Project Topography"), self.tab_topo, 3)
        self._add_nav_item(self.tr("Software and Manifest"), self.tab_software, 4)

        # Empujar las pestañas a la izquierda y colocar el warning a la derecha
        self.tab_bar_layout.addStretch()
        self.tab_bar_layout.addWidget(self.lbl_unsaved_warning)

        main_layout.addWidget(self.tab_bar_frame)
        main_layout.addWidget(self.stack, stretch=1)

        # 4. FOOTER / MASTER ACTIONS
        footer_frame = QFrame()
        footer_layout = QHBoxLayout(footer_frame)
        footer_layout.setContentsMargins(15, 10, 15, 15)
        
        self.btn_guardar = QPushButton(self.tr("Save Local Changes"))
        self.btn_guardar.setObjectName("SecondaryButton")
        self.btn_guardar.setFixedSize(180, 40)
        self.btn_guardar.setCursor(Qt.PointingHandCursor)
        self.btn_guardar.clicked.connect(self._guardar_configuracion)
        footer_layout.addWidget(self.btn_guardar)

        footer_layout.addStretch()

        self.btn_exportar_semilla = QPushButton(self.tr("Export Studio Seed (.seed)"))
        self.btn_exportar_semilla.setObjectName("PrimaryButton")
        self.btn_exportar_semilla.setFixedSize(240, 40)
        self.btn_exportar_semilla.setCursor(Qt.PointingHandCursor)
        self.btn_exportar_semilla.clicked.connect(self._exportar_semilla_estudio)
        footer_layout.addWidget(self.btn_exportar_semilla)

        main_layout.addWidget(footer_frame)

    def _add_nav_item(self, text: str, widget, index: int):
        """Genera la pestaña compacta y la vincula al índice del QStackedWidget."""
        self.stack.addWidget(widget)
        btn = QPushButton(text)
        btn.setObjectName("TopTabInactive")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(34)
        btn.clicked.connect(lambda _, idx=index: self._cambiar_vista(idx))
        
        self.tab_bar_layout.addWidget(btn)
        self.nav_buttons[index] = btn
        
        # Activar el primero por defecto
        if index == 0:
            self._cambiar_vista(0)

    def _cambiar_vista(self, index: int):
        self.stack.setCurrentIndex(index)
        for idx, btn in self.nav_buttons.items():
            btn.setObjectName("TopTabActive" if idx == index else "TopTabInactive")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _conectar_senales_cambio(self):
        self.tab_identidad.modified.connect(self._on_field_modified)
        self.tab_boveda.modified.connect(self._on_field_modified)
        self.tab_vcs.modified.connect(self._on_field_modified)
        self.tab_topo.modified.connect(self._on_field_modified)
        self.tab_software.modified.connect(self._on_field_modified)

    def _on_field_modified(self):
        self.lbl_unsaved_warning.setText(self.tr("● Unsaved Changes"))
        self.lbl_unsaved_warning.setStyleSheet("color: #F59E0B; font-weight: bold; font-size: 13px; margin-left: 15px;")

    def _cargar_datos_actuales(self):
        raw = self.config_factory.get_raw_config()
        vcs = raw.get("vcs_engine", {})
        topo = raw.get("project_topography", {})
        
        self.tab_identidad.cargar_datos(raw)
        
        projects_path = vcs.get("local_workspace_root", {}).get(self.config_factory._get_current_os(), "")
        if not projects_path:
            projects_path = str(self.config_factory.get_workspace_root())
            
        vault_path = str(self.config_factory.get_vault_path())
        self.tab_boveda.cargar_datos(projects_path, vault_path)

        active_adapter = vcs.get("active_adapter", "svn")
        repo_url = vcs.get("repository_url", "")
        enable_sparse = vcs.get("enable_vendor_sparse_checkout", True)
        vcs_user = vcs.get("vcs_username", "")
        vcs_pwd = vcs.get("vcs_password", "")
        
        self.tab_vcs.cargar_datos(active_adapter, repo_url, enable_sparse, vcs_user, vcs_pwd)
        self.tab_topo.cargar_datos(topo)
        
        manifest_data = self.vault_manager.cargar_inventario()
        self.tab_software.cargar_datos(manifest_data)
        
        self.lbl_unsaved_warning.setText("")

    def _recopilar_payload(self) -> dict:
        payload = {}
        payload.update(self.tab_identidad.get_identity_payload())
        payload.update(self.tab_vcs.get_vcs_payload())
        payload.update(self.tab_topo.get_topography_payload())
        
        vault_data = self.tab_boveda.get_vault_payload()
        projects_dir = vault_data.get("vcs_engine", {}).get("local_workspace_root", "")
        
        payload["infrastructure_topology"] = vault_data.get("infrastructure_topology", {})
        payload["vcs_engine"].update({
            "local_workspace_root": {
                "windows": projects_dir,
                "linux": projects_dir,
                "macos": projects_dir
            }
        })
        return payload

    def _guardar_configuracion(self):
        if getattr(self.tab_identidad, 'pending_hero_image_path', None) and self.tab_identidad.pending_hero_image_path.exists():
            try:
                dest_path = Path("assets/login_hero.png")
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.tab_identidad.pending_hero_image_path, dest_path)
                self.tab_identidad.entry_hero_image.clear()
                self.tab_identidad.pending_hero_image_path = None
            except Exception as e:
                self.status_callback(self.tr("⚠️ Failed to apply Hero Image: {0}").format(e), "yellow")

        payload = self._recopilar_payload()
        exito_config = self.config_factory.guardar_configuracion(payload)
        
        software_payload = self.tab_software.get_software_payload()
        exito_vault = self.vault_manager.guardar_inventario(software_payload)
        
        if exito_config and exito_vault:
            self.lbl_unsaved_warning.setText("")
            self.status_callback(self.tr("✓ Local settings and Network Manifest saved successfully."), "green")
            self._cargar_datos_actuales()
        else:
            if not exito_config: self.status_callback(self.tr("✗ Error writing settings.json"), "red")
            if not exito_vault: self.status_callback(self.tr("✗ Error writing vault_manifest.json"), "red")

    def _exportar_semilla_estudio(self):
        payload = self._recopilar_payload()
        dest_dir = QFileDialog.getExistingDirectory(self, self.tr("Select Destination Directory"), QDir.homePath())
        if dest_dir:
            self.status_callback(self.tr("Encrypting and exporting Studio Seed..."), "yellow")
            exito, mensaje = self.config_factory.exportar_semilla(payload, Path(dest_dir))
            if exito: self.status_callback(self.tr("✓ Seed exported: {0}").format(mensaje), "green")
            else: self.status_callback(self.tr("✗ Export failed: {0}").format(mensaje), "red")
