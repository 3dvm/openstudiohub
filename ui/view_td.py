# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/view_td.py
# Rol Arquitectónico: UI View / Command Center Dashboard (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0 (MasterLayout Inheritance)
# =========================================================================================

"""
Advanced control panel for the Technical Director (TD) and Supervisors.
Inherits from BaseDashboardView to enforce DRY principles and corporate UI guidelines.
Uses QStackedWidget to dynamically switch between Infrastructure, Settings, and Projects.
"""

from PySide6.QtWidgets import QStackedWidget, QLabel
from PySide6.QtCore import Qt
from pathlib import Path
from typing import Callable

from core.auth_manager import AuthManager
from core.vault_manager import VaultManager
from core.config_factory import ConfigFactory

from ui.base_dashboard import BaseDashboardView
from ui.widget_project_list import ProjectListWidget
from ui.widget_infrastructure import InfrastructureWidget
from ui.widget_settings import SettingsWidget


class ViewTD(BaseDashboardView):
    def __init__(self, parent, auth_manager: AuthManager, nas_dir: Path,
                 vault_manager: VaultManager, config_factory: ConfigFactory, on_logout: Callable[[], None], **kwargs):

        # Inicializa el cascarón maestro (TopBar, Sidebar, StatusBar)
        super().__init__(parent, auth_manager, config_factory, on_logout, **kwargs)

        self.nas_dir = nas_dir
        self.vault = vault_manager

        self.setObjectName("ViewTDBase")

        # 1. Configurar Navegación Lateral (Inyectada al Master Layout)
        self.add_sidebar_button("proyectos", self.tr("Projects"), "🗂️", "folder.svg", lambda: self._cambiar_panel("proyectos"), activo=True)
        #self.add_sidebar_button("watchtower", self.tr("Watchtower"), "🗼", "radar.svg", lambda: self._cambiar_panel("watchtower"))
        self.add_sidebar_button("infra", self.tr("Infrastructure"), "⚙️", "server.svg", lambda: self._cambiar_panel("infra"))
        self.add_sidebar_button("settings", self.tr("Settings"), "🔧", "settings.svg", lambda: self._cambiar_panel("settings"))

        # 2. Construir el Contenido Central
        self._build_td_content()

        # 3. Inicializar Datos
        self.vista_proyectos.cargar_proyectos()

    def _build_td_content(self):
        """Construye los paneles de configuración y los inyecta en el layout central."""

        self.stacked_content = QStackedWidget()

        # Index 0: Project Management List
        self.vista_proyectos = ProjectListWidget(
            parent=self.stacked_content,
            nas_dir=self.nas_dir,
            auth_manager=self.auth,
            vault_manager=self.vault,
            config_factory=self.config_factory,
            status_callback=self.actualizar_status  # Método heredado
        )
        self.stacked_content.addWidget(self.vista_proyectos)

        # Index 1: Watchtower Hub Window (Placeholder)
        # placeholder_wt = QLabel(self.tr("🚧 Watchtower module under construction..."))
        # placeholder_wt.setAlignment(Qt.AlignCenter)
        # placeholder_wt.setObjectName("PlaceholderText")
        # self.stacked_content.addWidget(placeholder_wt)

        # Index 2: Infrastructure Configuration Panel
        self.vista_infra = InfrastructureWidget(
            parent=self.stacked_content,
            config_factory=self.config_factory,
            status_callback=self.actualizar_status
        )
        self.stacked_content.addWidget(self.vista_infra)

        # Index 3: Global System Settings
        self.vista_configuraciones = SettingsWidget(
            parent=self.stacked_content,
            config_factory=self.config_factory,
            auth_manager=self.auth,
            status_callback=self.actualizar_status
        )
        self.stacked_content.addWidget(self.vista_configuraciones)

        # Inyectar el stack completo en el contenedor de la clase padre
        self.content_layout.addWidget(self.stacked_content, stretch=1)

    def _cambiar_panel(self, panel_id: str):
        """Visual Router: Actualiza el sidebar y cambia la vista del stack."""
        self.set_active_sidebar_button(panel_id) # Método heredado

        indices = {"proyectos": 0, "infra": 1, "settings": 2}
        self.stacked_content.setCurrentIndex(indices.get(panel_id, 0))
