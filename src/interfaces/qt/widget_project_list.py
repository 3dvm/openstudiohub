# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/widget_project_list.py
# Rol Arquitectónico: UI Component / TD Project Grid (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.4.0 (Auto-Refresh & Reload Hooks)
# =========================================================================================

"""
Componente independiente para la Lista de Proyectos del TD.
Encapsula la lógica de cuadrícula responsiva, extracción de datos vía Kitsu
y el botón de creación de nuevos proyectos.
Integra ganchos (hooks) de auto-recarga tras operaciones destructivas.
"""

from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QPushButton, QScrollArea, QWidget)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QResizeEvent
from pathlib import Path

from src.interfaces.qt.window_new_project import NewProjectWindow
from src.interfaces.qt.components.project_card import ProjectCard

class ProjectGridWorker(QThread):
    """Hilo secundario para extraer los proyectos abiertos del estudio desde Kitsu."""
    data_ready = Signal(list)

    def __init__(self, auth_manager):
        super().__init__()
        self.auth = auth_manager

    def run(self):
        try:
            proyectos = self.auth.production_service.list_open_projects()
            self.data_ready.emit(proyectos)
        except Exception as e:
            print(f"[ProjectList] Error retrieving projects: {e}")
            self.data_ready.emit([])


class ProjectListWidget(QFrame):
    def __init__(self, parent, nas_dir: Path, auth_manager, vault_manager, config_factory,
                 status_callback, on_open_wizard_callback=None, **kwargs):
        super().__init__(parent, **kwargs)

        self.nas_dir = nas_dir
        self.auth = auth_manager
        self.vault = vault_manager
        self.config_factory = config_factory
        self.status_callback = status_callback
        self.on_open_wizard_callback = on_open_wizard_callback

        self.user_role = self.auth.get_user_role() if hasattr(self.auth, 'get_user_role') else "user"

        self._project_widgets = []
        self._current_cols = 0

        self.setObjectName("ProjectListWidgetBase")

        self._build_ui()

    def _build_ui(self):
        content_layout = QVBoxLayout(self)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(20)

        # ---------------------------------------------------------
        # HERO ACTION (Botones de Cabecera)
        # ---------------------------------------------------------
        hero_layout = QHBoxLayout()
        hero_layout.setContentsMargins(0, 0, 0, 0)

        if self.user_role != "td":
            lbl_title = QLabel(self.tr("My Assigned Projects"))
            lbl_title.setObjectName("H2Title")
            hero_layout.addWidget(lbl_title)

        hero_layout.addStretch()

        self.btn_refrescar = QPushButton(self.tr("🔄 Refresh List"))
        self.btn_refrescar.setObjectName("SecondaryButton")
        self.btn_refrescar.setFixedSize(150, 40)
        self.btn_refrescar.setCursor(Qt.PointingHandCursor)
        self.btn_refrescar.clicked.connect(self.cargar_proyectos)
        hero_layout.addWidget(self.btn_refrescar)

        if self.user_role == "td":
            self.btn_nuevo_proy = QPushButton(self.tr("Create New Project"))
            self.btn_nuevo_proy.setObjectName("PrimaryButton")
            self.btn_nuevo_proy.setFixedSize(220, 40)
            self.btn_nuevo_proy.setCursor(Qt.PointingHandCursor)
            self.btn_nuevo_proy.clicked.connect(self.abrir_wizard_proyecto)
            hero_layout.addWidget(self.btn_nuevo_proy)

        content_layout.addLayout(hero_layout)

        # ---------------------------------------------------------
        # CONTENEDOR GRID CON SCROLL
        # ---------------------------------------------------------
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("InvisibleScrollArea")
        #self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.grid_widget = QWidget()
        self.grid_widget.setObjectName("TransparentGridContainer")
        #self.grid_widget.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.scroll_area.setWidget(self.grid_widget)
        content_layout.addWidget(self.scroll_area, stretch=1)

    # ---------------------------------------------------------
    # RESPONSIVE GRID LOGIC
    # ---------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._rearrange_grid()

    def _rearrange_grid(self):
        if not self._project_widgets: return
        viewport_width = self.scroll_area.viewport().width()
        card_width = 340 if self.user_role != "td" else 320
        spacing = self.grid_layout.spacing()
        cols = max(1, (viewport_width + spacing) // (card_width + spacing))

        if getattr(self, '_current_cols', 0) == cols: return
        self._current_cols = cols
        row, col = 0, 0

        for widget in self._project_widgets:
            self.grid_layout.removeWidget(widget)
            self.grid_layout.addWidget(widget, row, col)

            col += 1
            if col >= cols:
                col = 0
                row += 1

    # ---------------------------------------------------------
    # LÓGICA DE DATOS
    # ---------------------------------------------------------

    def _emit_status(self, mensaje: str, color: str = "white"):
        if self.status_callback: self.status_callback(mensaje, color)

    def cargar_proyectos(self):
        self._emit_status(self.tr("Syncing projects catalog..."), "yellow")
        self.btn_refrescar.setEnabled(False)

        for widget in self._project_widgets:
            widget.hide()
            widget.deleteLater()
        self._project_widgets.clear()

        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()

        self.worker = ProjectGridWorker(self.auth)
        self.worker.data_ready.connect(self._renderizar_proyectos)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _renderizar_proyectos(self, proyectos: list):
        self.btn_refrescar.setEnabled(True)
        if not proyectos:
            self._emit_status(self.tr("No active projects found."), "yellow")
            return

        self._emit_status(self.tr("🟢 Synchronized: {0} active projects.").format(len(proyectos)), "green")

        for project_data in proyectos:
            tarjeta = ProjectCard(
                parent=self.grid_widget,
                project_data=project_data,
                auth_manager=self.auth,
                nas_dir=self.nas_dir,
                config_factory=self.config_factory,
                vault_manager=self.vault,
                on_rebuild_callback=self.cargar_proyectos,
                on_open_wizard_callback=self.on_open_wizard_callback,
                status_callback=self.status_callback
            )

            self._project_widgets.append(tarjeta)

        self._current_cols = 0
        self._rearrange_grid()

    def abrir_wizard_proyecto(self):
        self.wizard_window = NewProjectWindow(
            parent=self.window(),
            config_factory=self.config_factory,
            on_success_callback=self.cargar_proyectos
        )
        self.wizard_window.show()
