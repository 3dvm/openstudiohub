# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/sidebar.py
# Architectural role: UI Component / Main Navigation & App Branding
# =========================================================================================

"""Left full-height sidebar.

Holds the corporate branding (logo + studio name) and the injectable
navigation routes.
"""

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class Sidebar(QFrame):
    def __init__(self, parent, config_factory) -> None:
        super().__init__(parent)
        self.config_factory = config_factory
        self.setObjectName("SidebarFrame")
        self.setFixedWidth(240)
        self.sidebar_buttons = {}

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 20, 15, 20)
        self.main_layout.setSpacing(10)

        self._build_branding()

        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(10)
        self.main_layout.addLayout(self.nav_layout)

        self.main_layout.addStretch()

    def _build_branding(self) -> None:
        self.branding_layout = QHBoxLayout()
        self.branding_layout.setContentsMargins(5, 0, 5, 25)
        self.branding_layout.setSpacing(12)

        self.logo_icon = QLabel()
        logo_path = Path("assets/logo_topbar.png")
        if logo_path.exists():
            self.logo_icon.setPixmap(QPixmap(str(logo_path)).scaledToHeight(32, Qt.SmoothTransformation))
        self.branding_layout.addWidget(self.logo_icon)

        studio_name = self.config_factory.get_studio_name() or "OpenStudio"
        self.lbl_title = QLabel(self.tr("{0} Hub").format(studio_name))
        self.lbl_title.setObjectName("SidebarBrandTitle")
        self.lbl_title.setStyleSheet("color: #F8FAFC; font-size: 15px; font-weight: bold;")
        self.lbl_title.setWordWrap(True)
        self.branding_layout.addWidget(self.lbl_title)

        self.branding_layout.addStretch()
        self.main_layout.addLayout(self.branding_layout)

    def add_button(self, btn_id: str, text: str, emoji: str, icon_name: str, callback, active: bool = False) -> None:
        btn = QPushButton()
        color_hex = "#F97316" if active else "#94A3B8"

        icon_path = Path(f"assets/icons/{icon_name}")
        if icon_name and icon_path.exists() and icon_path.is_file():
            btn.setIcon(self._create_colored_icon(icon_path, color_hex))
            btn.setIconSize(QSize(22, 22))
            btn.setText(f"   {text}")
        else:
            btn.setText(f"{emoji}   {text}")

        btn.setCursor(Qt.PointingHandCursor)
        btn.setObjectName("SidebarNavActive" if active else "SidebarNavInactive")
        btn.clicked.connect(callback)

        self.sidebar_buttons[btn_id] = btn
        self.nav_layout.addWidget(btn)

    def set_active_button(self, btn_id: str) -> None:
        for key, btn in self.sidebar_buttons.items():
            btn.setObjectName("SidebarNavActive" if key == btn_id else "SidebarNavInactive")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _create_colored_icon(self, icon_path: Path, color_hex: str) -> QIcon:
        if not icon_path.exists():
            return QIcon()
        try:
            with open(icon_path, "r", encoding="utf-8") as handle:
                svg_content = handle.read()
            svg_content = svg_content.replace("currentColor", color_hex)
            svg_content = svg_content.replace("#000000", color_hex)
            svg_content = svg_content.replace('#000"', f'{color_hex}"')
            svg_content = svg_content.replace("#000'", f"{color_hex}'")
            pixmap = QPixmap()
            pixmap.loadFromData(svg_content.encode("utf-8"), "SVG")
            return QIcon(pixmap)
        except Exception:  # noqa: BLE001
            return QIcon(str(icon_path))
