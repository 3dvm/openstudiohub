# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/view_pm.py
# Rol Arquitectónico: UI Component / Production Manager Dashboard
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 2.1.0 (Widget Extraction / Routing Only)
# =========================================================================================

from PySide6.QtWidgets import QStackedWidget#, QLabel
#from PySide6.QtCore import Qt

#from core import vault_manager
from ui.base_dashboard import BaseDashboardView
from ui.widget_blend_builder import WidgetBlendBuilder

# Importaremos el widget unificado (actualmente el del TD, que unificaremos en el siguiente paso)
from ui.widget_project_list import ProjectListWidget

class ViewPM(BaseDashboardView):
    def __init__(self, parent, auth_manager, config_factory, on_logout, vault_manager=None, **kwargs):
        self.vault_manager = vault_manager
        super().__init__(parent, auth_manager, config_factory, on_logout, **kwargs)

        self.setObjectName("ViewPMBase")

        # 1. Configurar Navegación Lateral
        self.add_sidebar_button("btn_projects", self.tr("Projects"), "📁", "folder.svg", lambda: self._cambiar_panel("btn_projects"), activo=True)
        # Espacio preparado para futuros paneles del PM
        self.add_sidebar_button("btn_batch", self.tr("Batch Creation"), "📦", "box.svg", lambda: self._cambiar_panel("btn_batch"))

        # 2. Construir el Contenido Central
        self._build_pm_content()

    def _build_pm_content(self):
        """Prepara el StackedWidget e inyecta los widgets de trabajo modulares."""
        self.stacked_content = QStackedWidget()

        # Index 0: Lista de Proyectos (Unificada)
        # Le pasamos un callback para que la tarjeta sepa qué hacer al hacer clic en "Open Wizard"
        self.project_list = ProjectListWidget(
            parent=self.stacked_content,
            nas_dir=self.config_factory.get_workspace_root(),
            auth_manager=self.auth,
            vault_manager=None, # El PM delega esto al config_factory en la nueva arquitectura
            config_factory=self.config_factory,
            status_callback=self.actualizar_status,
            on_open_wizard_callback=self._abrir_wizard_para_proyecto # <--- NUEVO HOOK
        )
        self.stacked_content.addWidget(self.project_list)

        # Index 0: Batch Entity Genesis Tool
        self.widget_builder = WidgetBlendBuilder(
            parent=self.stacked_content,
            auth_manager=self.auth,
            config_factory=self.config_factory,
            status_callback=self.actualizar_status,
            vault_manager=self.vault_manager
        )
        self.stacked_content.addWidget(self.widget_builder)

        # Inyectar el stack completo en el contenedor de la clase padre
        self.content_layout.addWidget(self.stacked_content, stretch=1)

        #if panel_id == "btn_projects":
        self.project_list.cargar_proyectos()

    def _cambiar_panel(self, panel_id: str):
        """Visual Router: Actualiza el sidebar y cambia la vista del stack."""
        self.set_active_sidebar_button(panel_id)
        indices = {"btn_projects": 0, "btn_batch": 1}
        self.stacked_content.setCurrentIndex(indices.get(panel_id, 0))
        
        # Auto-recargar proyectos al entrar a la vista
        if panel_id == "btn_projects":
            self.project_list.cargar_proyectos()

    def _abrir_wizard_para_proyecto(self, project_name: str):
        """Hook que recibe la señal de la tarjeta y transiciona al Wizard."""
        self._cambiar_panel("btn_batch")
        # Forzar al combo box del Wizard a seleccionar el proyecto en el que hicimos clic
        index = self.widget_builder.combo_projects.findText(project_name)
        if index >= 0:
            self.widget_builder.combo_projects.setCurrentIndex(index)
