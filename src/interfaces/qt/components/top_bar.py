# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/top_bar.py
# Architectural role: UI Component / Header (User Utilities)
# =========================================================================================

"""Top header of the Hub.

Minimalist design: hosts only the user utilities aligned to the right.
"""

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from src.application.services.auth_service import AuthService
from src.interfaces.qt.components.notification_panel import NotificationPanel


class TopBar(QFrame):
    def __init__(
        self,
        parent,
        auth_service: AuthService,
        config_factory,
        on_logout,
        notifications_vm=None,
    ) -> None:
        super().__init__(parent)
        self.auth = auth_service
        self.config_factory = config_factory
        self.on_logout = on_logout
        self.notifications_vm = notifications_vm
        self.notification_panel = None

        self.setObjectName("TopBar")
        self.setFixedHeight(65)
        self._build_ui()
        if self.notifications_vm is not None:
            self.notifications_vm.unread_count_changed.connect(self._on_unread_count)
            self.notifications_vm.notifications_changed.connect(self._on_notifications)
            self.notifications_vm.refresh()
            self._on_unread_count(self.notifications_vm.unread_count())

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
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(15)

        layout.addStretch()

        self.btn_kitsu = QPushButton("  Kitsu")
        self.btn_kitsu.setObjectName("TopBarKitsuButton")
        self.btn_kitsu.setFixedSize(100, 34)
        self.btn_kitsu.setCursor(Qt.PointingHandCursor)

        kitsu_icon_path = Path("assets/icons/kitsu.svg")
        if kitsu_icon_path.exists():
            self.btn_kitsu.setIcon(self._create_colored_icon(kitsu_icon_path, "#FFFFFF"))
            self.btn_kitsu.setIconSize(QSize(18, 18))
        else:
            self.btn_kitsu.setText("🎬 Kitsu")

        self.btn_kitsu.clicked.connect(self._on_kitsu_clicked)
        layout.addWidget(self.btn_kitsu)

        role = self.auth.current_role().label if self.auth else "Offline"
        user = self.auth.current_user if self.auth else None
        user_name = user.first_name if user else "User"

        self.lbl_name = QLabel(self.tr("{0} ({1})").format(user_name, role))
        self.lbl_name.setObjectName("TopBarUserLabel")
        self.lbl_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.lbl_name)

        self.btn_avatar = QPushButton()
        self.btn_avatar.setObjectName("TopBarAvatarButton")
        self.btn_avatar.setFixedSize(36, 36)
        avatar_path = Path("assets/icons/user.svg")
        if avatar_path.exists():
            self.btn_avatar.setIcon(self._create_colored_icon(avatar_path, "#94A3B8"))
            self.btn_avatar.setIconSize(QSize(20, 20))
        else:
            self.btn_avatar.setText("👤")
        layout.addWidget(self.btn_avatar)

        bell_container = QWidget()
        bell_grid = QGridLayout(bell_container)
        bell_grid.setContentsMargins(0, 0, 0, 0)
        bell_grid.setSpacing(0)
        self.btn_bell = QPushButton()
        self.btn_bell.setObjectName("TopBarBellButton")
        self.btn_bell.setFixedSize(36, 36)
        self.btn_bell.setCursor(Qt.PointingHandCursor)
        bell_path = Path("assets/icons/bell.svg")
        if bell_path.exists():
            self.btn_bell.setIcon(self._create_colored_icon(bell_path, "#64748B"))
            self.btn_bell.setIconSize(QSize(22, 22))
        else:
            self.btn_bell.setText("🔔")
        self.btn_bell.clicked.connect(self._toggle_notifications)
        bell_grid.addWidget(self.btn_bell, 0, 0)
        self.bell_badge = QLabel("0", bell_container)
        self.bell_badge.setObjectName("TopBarBellBadge")
        self.bell_badge.setAlignment(Qt.AlignCenter)
        self.bell_badge.setFixedSize(16, 16)
        self.bell_badge.hide()
        bell_grid.addWidget(self.bell_badge, 0, 0, Qt.AlignTop | Qt.AlignRight)
        layout.addWidget(bell_container)

        self.btn_logout = QPushButton(self.tr("Log Out"))
        self.btn_logout.setObjectName("SecondaryButton")
        self.btn_logout.setFixedSize(80, 32)
        self.btn_logout.setCursor(Qt.PointingHandCursor)
        if self.on_logout:
            self.btn_logout.clicked.connect(self.on_logout)
        layout.addWidget(self.btn_logout)

    def _on_unread_count(self, count: int) -> None:
        if count <= 0:
            self.bell_badge.hide()
            return
        self.bell_badge.setText("99+" if count > 99 else str(count))
        self.bell_badge.show()
        self.bell_badge.raise_()

    def _on_notifications(self, notifications: list) -> None:
        if self.notification_panel is not None and self.notification_panel.isVisible():
            self.notification_panel.set_notifications(notifications)

    def _toggle_notifications(self) -> None:
        if self.notifications_vm is None:
            return
        if self.notification_panel is not None and self.notification_panel.isVisible():
            self.notification_panel.hide()
            return

        if self.notification_panel is None:
            self.notification_panel = NotificationPanel(self)
            self.notification_panel.mark_all_read.connect(self.notifications_vm.mark_all_read)
            self.notification_panel.notification_clicked.connect(self._on_notification_clicked)

        self.notifications_vm.refresh()
        self.notification_panel.set_notifications(self.notifications_vm.list())
        anchor = self.btn_bell.mapToGlobal(QPoint(0, self.btn_bell.height() + 6))
        screen = self.screen().availableGeometry() if self.screen() else None
        x = anchor.x()
        y = anchor.y()
        if screen is not None:
            x = min(x, screen.right() - self.notification_panel.width())
            x = max(x, screen.left())
            y = min(y, screen.bottom() - self.notification_panel.height())
        self.notification_panel.move(x, y)
        self.notification_panel.show()

    def _on_notification_clicked(self, notification_id: str) -> None:
        if self.notifications_vm is not None:
            self.notifications_vm.mark_read(notification_id)

    def _on_kitsu_clicked(self) -> None:
        """Find the main orchestrator and trigger the view switch."""
        main_window = self.window()
        if hasattr(main_window, "open_kitsu"):
            main_window.open_kitsu()
