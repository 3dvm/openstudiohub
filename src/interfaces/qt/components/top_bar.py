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
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
)

from src.application.services.auth_service import AuthService
from src.domain.identity.value_objects import Role, ViewProfile
from src.interfaces.qt.components.notification_panel import NotificationPanel
from src.interfaces.qt.components.remote_images import (
    RemoteImageWorker,
    circular_icon,
    thumbnail_url,
)


class TopBar(QFrame):
    def __init__(
        self,
        parent,
        auth_service: AuthService,
        config_factory,
        on_logout,
        notifications_vm=None,
        profiles=None,
        active_profile="",
        on_profile_selected=None,
        profile_labels=None,
    ) -> None:
        super().__init__(parent)
        self.auth = auth_service
        self.config_factory = config_factory
        self.on_logout = on_logout
        self.notifications_vm = notifications_vm
        self.on_profile_selected = on_profile_selected
        self.profiles = [
            profile.value if isinstance(profile, ViewProfile) else str(profile)
            for profile in (profiles or [])
        ]
        self.active_profile = str(active_profile or "")
        self.profile_labels = dict(profile_labels or {})
        self.notification_panel = None
        self._avatar_worker = None

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
        self._load_kitsu_avatar()

        role = self.auth.current_role() if self.auth else None
        user = self.auth.current_user if self.auth else None
        user_name = user.first_name if user else "User"

        self.lbl_name = QLabel(user_name)
        self.lbl_name.setObjectName("TopBarUserLabel")
        self.lbl_name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.lbl_name)

        self.btn_profile = QToolButton()
        self.btn_profile.setObjectName("TopBarProfileButton")
        self.btn_profile.setCursor(Qt.PointingHandCursor)
        self.btn_profile.setFixedHeight(30)
        self.btn_profile.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._configure_profile_button(role)
        layout.addWidget(self.btn_profile)


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

    def _profile_label(self, profile: str, role) -> str:
        if profile in self.profile_labels:
            return str(self.profile_labels[profile])
        view = ViewProfile.from_value(profile)
        if view is not None:
            position = str(getattr(self.auth.current_user, "position", "") or "")
            if isinstance(role, Role):
                return role.profile_label(view, position)
            return view.label
        return str(getattr(role, "label", "Offline") or "Offline")

    def _configure_profile_button(self, role) -> None:
        profiles = list(self.profiles)
        if not profiles and role is not None:
            value = str(getattr(role, "value", "") or "").strip()
            if value:
                profiles = [value]
        if not profiles:
            self.btn_profile.setText(str(getattr(role, "label", "Offline") or "Offline"))
            self.btn_profile.setEnabled(False)
            return

        active = self.active_profile if self.active_profile in profiles else profiles[0]
        self.active_profile = active
        self.btn_profile.setText(self._profile_label(active, role))

        if len(profiles) <= 1 or not callable(self.on_profile_selected):
            self.btn_profile.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
            return

        menu = QMenu(self.btn_profile)
        for profile in profiles:
            action = menu.addAction(self._profile_label(profile, role))
            action.setCheckable(True)
            action.setChecked(profile == active)
            action.triggered.connect(
                lambda checked=False, p=profile: self.on_profile_selected(p)
            )
        self.btn_profile.setMenu(menu)
        self.btn_profile.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

    def _load_kitsu_avatar(self) -> None:
        if self.auth is None:
            return
        raw = getattr(self.auth, "raw_user_data", None) or {}
        user = getattr(self.auth, "current_user", None)
        user_id = str((raw or {}).get("id") or getattr(user, "id", "") or "")
        if not user_id or not bool((raw or {}).get("has_avatar")):
            return
        url = thumbnail_url(getattr(self.auth, "host", ""), "persons", user_id)
        if not url:
            return
        worker = RemoteImageWorker(url, getattr(self.auth, "access_token", lambda: "")())
        worker.image_ready.connect(self._on_avatar_ready)
        self._avatar_worker = worker
        worker.start()

    def _on_avatar_ready(self, data: bytes) -> None:
        icon = circular_icon(data, 28)
        if icon is not None:
            self.btn_avatar.setIcon(icon)
            self.btn_avatar.setIconSize(QSize(28, 28))

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
            self.notification_panel.dismiss_notification.connect(self.notifications_vm.dismiss)
            self.notification_panel.clear_all.connect(self.notifications_vm.dismiss_all)

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
