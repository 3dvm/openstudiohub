# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/components/sidebar.py
# Rol Arquitectónico: UI Component / Main Navigation & App Branding
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.1.0
# =========================================================================================

"""
Barra lateral izquierda (Sidebar) de altura completa.
Ahora actúa como el ancla principal de la marca corporativa (Logo + Nombre del Estudio),
además de contener las rutas de navegación dinámicas inyectables por el MasterLayout.
"""

from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QIcon
from pathlib import Path

class Sidebar(QFrame):
    def __init__(self, parent, config_factory):
        super().__init__(parent)
        self.config_factory = config_factory
        self.setObjectName("SidebarFrame") 
        self.setFixedWidth(240)
        self.sidebar_buttons = {}
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 20, 15, 20)
        self.main_layout.setSpacing(10)

        # 1. Inyección de Branding Unificado
        self._build_branding()

        # 2. Contenedor de Navegación
        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(10)
        self.main_layout.addLayout(self.nav_layout)
        
        self.main_layout.addStretch()

    def _build_branding(self):
        self.branding_layout = QHBoxLayout()
        self.branding_layout.setContentsMargins(5, 0, 5, 25) # Espacio negativo inferior
        self.branding_layout.setSpacing(12)

        self.logo_icon = QLabel()
        logo_path = Path("assets/logo_topbar.png")
        if logo_path.exists():
            self.logo_icon.setPixmap(QPixmap(str(logo_path)).scaledToHeight(32, Qt.SmoothTransformation))
        self.branding_layout.addWidget(self.logo_icon)
        
        studio_name = self.config_factory.get_studio_name() or "OpenStudio"
        self.lbl_title = QLabel(self.tr("{0} Hub").format(studio_name))
        self.lbl_title.setObjectName("SidebarBrandTitle")
        # Estilo inline tolerado como base de fallback, idealmente se sobrescribe en QSS
        self.lbl_title.setStyleSheet("color: #F8FAFC; font-size: 15px; font-weight: bold;")
        self.lbl_title.setWordWrap(True)
        self.branding_layout.addWidget(self.lbl_title)

        self.branding_layout.addStretch()
        self.main_layout.addLayout(self.branding_layout)

    def add_button(self, btn_id: str, texto: str, emoji: str, icon_name: str, callback, activo: bool = False):
        btn = QPushButton()
        color_hex = "#F97316" if activo else "#94A3B8"
        
        # Validación robusta para evitar que intente leer un directorio si icon_name está vacío
        icon_path = Path(f"assets/icons/{icon_name}")
        if icon_name and icon_path.exists() and icon_path.is_file():
            btn.setIcon(self._crear_icono_coloreado(icon_path, color_hex))
            btn.setIconSize(QSize(22, 22))
            btn.setText(f"   {texto}")
        else:
            # Fallback seguro al Emoji si el SVG no existe
            btn.setText(f"{emoji}   {texto}")
            
        btn.setCursor(Qt.PointingHandCursor)
        btn.setObjectName("SidebarNavActive" if activo else "SidebarNavInactive")
        btn.clicked.connect(callback)
        
        self.sidebar_buttons[btn_id] = btn
        self.nav_layout.addWidget(btn)

    def set_active_button(self, btn_id: str):
        for key, btn in self.sidebar_buttons.items():
            if key == btn_id:
                btn.setObjectName("SidebarNavActive")
            else:
                btn.setObjectName("SidebarNavInactive")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _crear_icono_coloreado(self, icon_path: Path, color_hex: str) -> QIcon:
        if not icon_path.exists(): return QIcon()
        try:
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            svg_content = svg_content.replace('currentColor', color_hex)
            svg_content = svg_content.replace('#000000', color_hex)
            svg_content = svg_content.replace('#000"', f'{color_hex}"')
            svg_content = svg_content.replace("#000'", f"{color_hex}'")
            pixmap = QPixmap()
            pixmap.loadFromData(svg_content.encode('utf-8'), "SVG")
            return QIcon(pixmap)
        except Exception:
            return QIcon(str(icon_path))
