# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/components/top_bar.py
# Rol Arquitectónico: UI Component / Header (User Utilities)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.3.0
# =========================================================================================

"""
Header superior del Hub.
Diseño minimalista: Alojamiento exclusivo para utilidades de usuario alineadas a la derecha.
Utiliza íconos Lucide para una estética corporativa.
"""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QIcon
from pathlib import Path

class TopBar(QFrame):
    def __init__(self, parent, auth_manager, config_factory, on_logout):
        super().__init__(parent)
        self.auth = auth_manager
        self.config_factory = config_factory
        self.on_logout = on_logout
        
        self.setObjectName("TopBarFrame")
        self.setFixedHeight(65)
        self._build_ui()

    def _crear_icono_coloreado(self, icon_path: Path, color_hex: str) -> QIcon:
        """Helper para pintar íconos SVG monocromáticos (Lucide)."""
        if not icon_path.exists(): return QIcon()
        try:
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            svg_content = svg_content.replace('currentColor', color_hex)
            svg_content = svg_content.replace('#000000', color_hex)
            svg_content = svg_content.replace('stroke-width="2"', 'stroke-width="2.5"') # Hacemos el trazo más grueso
            pixmap = QPixmap()
            pixmap.loadFromData(svg_content.encode('utf-8'), "SVG")
            return QIcon(pixmap)
        except Exception:
            return QIcon(str(icon_path))

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(30, 0, 30, 0)
        layout.setSpacing(15)

        # Resorte expansivo para empujar todas las herramientas hacia la extrema derecha
        layout.addStretch()

        # --- Botón de Kitsu (Con ícono SVG Lucide) ---
        self.btn_kitsu = QPushButton("  Kitsu")
        self.btn_kitsu.setFixedSize(100, 34)
        self.btn_kitsu.setCursor(Qt.PointingHandCursor)
        
        kitsu_icon_path = Path("assets/icons/kitsu.svg")
        if kitsu_icon_path.exists():
            self.btn_kitsu.setIcon(self._crear_icono_coloreado(kitsu_icon_path, "#FFFFFF"))
            self.btn_kitsu.setIconSize(QSize(18, 18))
        else:
            self.btn_kitsu.setText("🎬 Kitsu")

        self.btn_kitsu.setStyleSheet("""
            QPushButton {
                background-color: #F97316; color: white; border: none; 
                font-weight: bold; border-radius: 6px; padding-right: 8px;
            }
            QPushButton:hover { background-color: #EA580C; }
        """)
        self.btn_kitsu.clicked.connect(self._on_kitsu_clicked)
        layout.addWidget(self.btn_kitsu)
        # -----------------------------

        # Info de Usuario
        rol = self.auth.get_user_role().capitalize() if self.auth else "Offline"
        nombre_user = self.auth.user_data.get("first_name", "User") if self.auth and self.auth.user_data else "User"
        
        self.lbl_name = QLabel(self.tr("{0} ({1})").format(nombre_user, rol))
        self.lbl_name.setObjectName("TopBarUserLabel")
        self.lbl_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_name.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 13px; margin-left: 15px;")
        layout.addWidget(self.lbl_name)

        # Icono de Usuario (SVG Coloreado)
        self.btn_avatar = QPushButton()
        self.btn_avatar.setFixedSize(36, 36)
        self.btn_avatar.setStyleSheet("background-color: #2E3643; border-radius: 18px; border: none;")
        avatar_path = Path("assets/icons/user.svg")
        if avatar_path.exists():
            self.btn_avatar.setIcon(self._crear_icono_coloreado(avatar_path, "#94A3B8"))
            self.btn_avatar.setIconSize(QSize(20, 20))
        else:
            self.btn_avatar.setText("👤")
        layout.addWidget(self.btn_avatar)

        # Icono de Campana (Notificaciones)
        self.btn_bell = QPushButton()
        self.btn_bell.setFixedSize(36, 36)
        self.btn_bell.setStyleSheet("background: transparent; border: none; margin-right: 15px;")
        self.btn_bell.setCursor(Qt.PointingHandCursor)
        bell_path = Path("assets/icons/bell.svg")
        if bell_path.exists():
            self.btn_bell.setIcon(self._crear_icono_coloreado(bell_path, "#64748B"))
            self.btn_bell.setIconSize(QSize(22, 22))
        else:
            self.btn_bell.setText("🔔")
        layout.addWidget(self.btn_bell)

        # Botón Logout
        self.btn_logout = QPushButton(self.tr("Log Out"))
        self.btn_logout.setObjectName("SecondaryButton")
        self.btn_logout.setFixedSize(80, 32)
        self.btn_logout.setCursor(Qt.PointingHandCursor)
        if self.on_logout:
            self.btn_logout.clicked.connect(self.on_logout)
        layout.addWidget(self.btn_logout)

    def _on_kitsu_clicked(self):
        """Busca el orquestador principal y dispara el cambio de vista."""
        main_win = self.window()
        if hasattr(main_win, 'abrir_kitsu'):
            main_win.abrir_kitsu()
