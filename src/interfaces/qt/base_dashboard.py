# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/base_dashboard.py
# Rol Arquitectónico: UI Component / Master Layout & Shell (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.2.0 (Full-Height Layout Integration)
# =========================================================================================

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame

from src.interfaces.qt.components.top_bar import TopBar
from src.interfaces.qt.components.sidebar import Sidebar
from src.interfaces.qt.components.status_bar import StatusBar

class BaseDashboardView(QWidget):
    def __init__(self, parent, auth_manager, config_factory, on_logout, **kwargs):
        super().__init__(parent, **kwargs)

        self.auth = auth_manager
        self.config_factory = config_factory
        self.on_logout = on_logout

        self.setObjectName("ViewBase")
        self._build_shell()

    def _build_shell(self):
        """Construye el esqueleto inmutable ensamblando los submódulos."""
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 1. SIDEBAR (Instanciado por Composición con Branding)
        # La barra lateral ahora abarca el 100% de la altura y contiene el Logo
        self.sidebar = Sidebar(self, self.config_factory)
        self.main_layout.addWidget(self.sidebar)

        # 2. RIGHT PANEL (Contenedor fluido derecho)
        self.right_panel = QFrame()
        self.right_panel.setObjectName("MainContentFrame")
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(0)

        # 3. TOP BAR (Instanciado por Composición - Header Limpio)
        self.top_bar = TopBar(self.right_panel, self.auth, self.config_factory, self.on_logout)
        self.right_layout.addWidget(self.top_bar)

        # 4. CONTENT AREA (Lienzo para subclases)
        self.content_container = QFrame()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(15, 25, 15, 20)
        self.content_layout.setSpacing(20)
        self.right_layout.addWidget(self.content_container, stretch=1)

        # 5. STATUS BAR (Instanciado por Composición)
        self.status_bar = StatusBar(self.right_panel)
        self.right_layout.addWidget(self.status_bar)

        self.main_layout.addWidget(self.right_panel, stretch=1)

    # -------------------------------------------------------------
    # WRAPPERS/PROXIES (Para no romper las subclases existentes)
    # -------------------------------------------------------------
    def add_sidebar_button(self, btn_id: str, texto: str, emoji: str, icon_name: str, callback, activo: bool = False):
        self.sidebar.add_button(btn_id, texto, emoji, icon_name, callback, activo)

    def set_active_sidebar_button(self, btn_id: str):
        self.sidebar.set_active_button(btn_id)

    def actualizar_status(self, mensaje: str, color: str = "white"):
        self.status_bar.actualizar_status(mensaje, color)
