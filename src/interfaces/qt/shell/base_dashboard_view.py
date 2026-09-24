# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/shell/base_dashboard_view.py
# Architectural role: UI Component / Master Layout & Shell (PySide6)
# =========================================================================================

"""Master layout shell shared by every dashboard.

Composes the Sidebar, TopBar, content area and StatusBar. The dashboard
ViewModels report status through a shared ``StatusSink`` that is wired once
to the global status bar.
"""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from src.interfaces.qt.components.sidebar import Sidebar
from src.interfaces.qt.components.status_bar import StatusBar
from src.interfaces.qt.components.top_bar import TopBar
from src.interfaces.qt.viewmodels.base_viewmodel import StatusSink


class BaseDashboardView(QWidget):
    def __init__(self, parent, auth_service, config_factory, on_logout, status_sink: StatusSink | None = None, **kwargs) -> None:
        super().__init__(parent, **kwargs)

        self.auth = auth_service
        self.config_factory = config_factory
        self.on_logout = on_logout

        self.setObjectName("ViewBase")
        self._build_shell()

        if status_sink is not None:
            status_sink.message.connect(self.update_status)
            status_sink.progress.connect(self.update_progress)

    def _build_shell(self) -> None:
        """Build the immutable shell by composing the submodules."""
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 1. SIDEBAR (full height, includes branding)
        self.sidebar = Sidebar(self, self.config_factory)
        self.main_layout.addWidget(self.sidebar)

        # 2. RIGHT PANEL (fluid container)
        self.right_panel = QFrame()
        self.right_panel.setObjectName("MainContentFrame")
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(0)

        # 3. TOP BAR
        self.top_bar = TopBar(self.right_panel, self.auth, self.config_factory, self.on_logout)
        self.right_layout.addWidget(self.top_bar)

        # 4. CONTENT AREA (canvas for subclasses)
        self.content_container = QFrame()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(15, 25, 15, 20)
        self.content_layout.setSpacing(20)
        self.right_layout.addWidget(self.content_container, stretch=1)

        # 5. STATUS BAR
        self.status_bar = StatusBar(self.right_panel)
        self.right_layout.addWidget(self.status_bar)

        self.main_layout.addWidget(self.right_panel, stretch=1)

    # ------------------------------------------------------------------
    # WRAPPERS / PROXIES (kept so subclasses stay simple)
    # ------------------------------------------------------------------
    def add_sidebar_button(self, btn_id: str, text: str, emoji: str, icon_name: str, callback, active: bool = False) -> None:
        self.sidebar.add_button(btn_id, text, emoji, icon_name, callback, active)

    def set_active_sidebar_button(self, btn_id: str) -> None:
        self.sidebar.set_active_button(btn_id)

    def update_status(self, message: str, color: str = "white") -> None:
        self.status_bar.update_status(message, color)

    def update_progress(self, percent: int) -> None:
        self.status_bar.set_progress(percent)
