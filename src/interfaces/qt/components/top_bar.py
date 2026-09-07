# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/top_bar.py
# Architectural role: UI Component / Header (User Utilities)
# =========================================================================================

"""Top header of the Hub.

Minimalist design: hosts only the user utilities aligned to the right.
"""

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from src.application.services.auth_service import AuthService


class TopBar(QFrame):
    def __init__(self, parent, auth_service: AuthService, config_factory, on_logout) -> None:
        super().__init__(parent)
        self.auth = auth_service
        self.config_factory = config_factory
        self.on_logout = on_logout

        self.setObjectName("TopBarFrame")
        self.setFixedHeight(65)
        self._build_ui()

    def _create_colored_icon(self, icon_path: Path, color_hex: str) -> QIcon:
        """Helper to tint monochromatic SVG icons at runtime."""
        if not icon_path.exists():
            return QIcon()
        try:
            with open(icon_path, "r", encoding="utf-8") as handle:
                svg_content = handle.read()
            svg_content = svg_content.replace("currentColor", color_hex)
            svg_content = svg_content.replace("#000000", color_hex)
            svg_content = svg_content.replace('stroke-width="2"', 'stroke-width="2.5"')
            pixmap = QPixmap()
            pixmap.loadFromData(svg_content.encode("utf-8"), "SVG")
            return QIcon(pixmap)
        except Exception:  # noqa: BLE001
            return QIcon(str(icon_path))

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(30, 0, 30, 0)
        layout.setSpacing(15)

        layout.addStretch()

        self.btn_kitsu = QPushButton("  Kitsu")
        self.btn_kitsu.setFixedSize(100, 34)
        self.btn_kitsu.setCursor(Qt.PointingHandCursor)

        kitsu_icon_path = Path("assets/icons/kitsu.svg")
        if kitsu_icon_path.exists():
            self.btn_kitsu.setIcon(self._create_colored_icon(kitsu_icon_path, "#FFFFFF"))
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

        role = self.auth.current_role().label if self.auth else "Offline"
        user = self.auth.current_user if self.auth else None
        user_name = user.first_name if user else "User"

        self.lbl_name = QLabel(self.tr("{0} ({1})").format(user_name, role))
        self.lbl_name.setObjectName("TopBarUserLabel")
        self.lbl_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_name.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 13px; margin-left: 15px;")
        layout.addWidget(self.lbl_name)

        self.btn_avatar = QPushButton()
        self.btn_avatar.setFixedSize(36, 36)
        self.btn_avatar.setStyleSheet("background-color: #2E3643; border-radius: 18px; border: none;")
        avatar_path = Path("assets/icons/user.svg")
        if avatar_path.exists():
            self.btn_avatar.setIcon(self._create_colored_icon(avatar_path, "#94A3B8"))
            self.btn_avatar.setIconSize(QSize(20, 20))
        else:
            self.btn_avatar.setText("👤")
        layout.addWidget(self.btn_avatar)

        self.btn_bell = QPushButton()
        self.btn_bell.setFixedSize(36, 36)
        self.btn_bell.setStyleSheet("background: transparent; border: none; margin-right: 15px;")
        self.btn_bell.setCursor(Qt.PointingHandCursor)
        bell_path = Path("assets/icons/bell.svg")
        if bell_path.exists():
            self.btn_bell.setIcon(self._create_colored_icon(bell_path, "#64748B"))
            self.btn_bell.setIconSize(QSize(22, 22))
        else:
            self.btn_bell.setText("🔔")
        layout.addWidget(self.btn_bell)

        self.btn_logout = QPushButton(self.tr("Log Out"))
        self.btn_logout.setObjectName("SecondaryButton")
        self.btn_logout.setFixedSize(80, 32)
        self.btn_logout.setCursor(Qt.PointingHandCursor)
        if self.on_logout:
            self.btn_logout.clicked.connect(self.on_logout)
        layout.addWidget(self.btn_logout)

    def _on_kitsu_clicked(self) -> None:
        """Find the main orchestrator and trigger the view switch."""
        main_window = self.window()
        if hasattr(main_window, "abrir_kitsu"):
            main_window.abrir_kitsu()
