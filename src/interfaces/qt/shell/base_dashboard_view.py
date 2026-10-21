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

from urllib.parse import urlsplit

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.domain.production.kitsu_links import kitsu_base_url
from src.interfaces.qt.components.sidebar import Sidebar
from src.interfaces.qt.components.status_bar import StatusBar
from src.interfaces.qt.components.top_bar import TopBar
from src.interfaces.qt.viewmodels.base_viewmodel import StatusSink


class BaseDashboardView(QWidget):
    def __init__(
        self,
        parent,
        auth_service,
        config_factory,
        on_logout,
        status_sink: StatusSink | None = None,
        notifications_vm=None,
        **kwargs,
    ) -> None:
        super().__init__(parent, **kwargs)

        self.auth = auth_service
        self.config_factory = config_factory
        self.on_logout = on_logout
        self.notifications_vm = notifications_vm

        self.setObjectName("ViewBase")
        self.web_context = None
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
        self.top_bar = TopBar(
            self.right_panel,
            self.auth,
            self.config_factory,
            self.on_logout,
            notifications_vm=self.notifications_vm,
        )
        self.right_layout.addWidget(self.top_bar)

        # 4. CONTENT AREA (canvas for subclasses) + embedded web context
        self.content_container = QFrame()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(15, 25, 15, 20)
        self.content_layout.setSpacing(20)

        self.web_context_container = QFrame()
        web_layout = QVBoxLayout(self.web_context_container)
        web_layout.setContentsMargins(2, 2, 2, 2)
        web_layout.setSpacing(0)

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.content_container)
        self.content_stack.addWidget(self.web_context_container)
        self.right_layout.addWidget(self.content_stack, stretch=1)

        # 5. STATUS BAR
        self.status_bar = StatusBar(self.right_panel)
        self.right_layout.addWidget(self.status_bar)

        self.main_layout.addWidget(self.right_panel, stretch=1)

    # ------------------------------------------------------------------
    # Embedded web context (Kitsu / Watchtower)
    # ------------------------------------------------------------------
    def _ensure_web_context(self):
        if self.web_context is None:
            from src.interfaces.qt.shell.web_context_view import WebContextView

            self.web_context = WebContextView(self.web_context_container)
            self.web_context.back_requested.connect(self.show_dashboard_content)
            self.web_context_container.layout().addWidget(self.web_context)
        return self.web_context

    def show_web_context(
        self,
        url: str,
        context_name: str,
        allowed_hosts: list,
        access_token: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        web = self._ensure_web_context()
        web.load_context(
            url,
            context_name,
            allowed_hosts,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        self.content_stack.setCurrentWidget(self.web_context_container)

    def show_dashboard_content(self) -> None:
        self.content_stack.setCurrentWidget(self.content_container)

    def open_kitsu_in_hub(self, url: str, allowed_hosts: list | None = None) -> None:
        if not url:
            return
        if allowed_hosts is None:
            base = kitsu_base_url(
                self.config_factory.get_kitsu_api_url() if self.config_factory else ""
            )
            host = urlsplit(url).hostname or (urlsplit(base).hostname if base else "")
            allowed_hosts = [item for item in (host, "localhost", "127.0.0.1") if item]
        access = self.auth.access_token() if self.auth else ""
        refresh = self.auth.refresh_token() if self.auth else ""
        self.show_web_context(
            url,
            "Kitsu",
            allowed_hosts,
            access_token=access or None,
            refresh_token=refresh or None,
        )

    def open_watchtower_in_hub(self, url: str) -> None:
        self.show_web_context(url, "Watchtower", ["localhost", "127.0.0.1"])

    def clear_web_auth(self) -> None:
        if self.web_context is not None:
            self.web_context.clear_auth()
            self.web_context.shutdown()
            self.web_context.deleteLater()
            self.web_context = None
        self.show_dashboard_content()

    # ------------------------------------------------------------------
    # WRAPPERS / PROXIES (kept so subclasses stay simple)
    # ------------------------------------------------------------------
    def add_sidebar_button(self, btn_id: str, text: str, emoji: str, icon_name: str, callback, active: bool = False) -> None:
        self.sidebar.add_button(btn_id, text, emoji, icon_name, callback, active)

    def add_footer_button(self, btn_id: str, text: str, emoji: str, icon_name: str, callback, active: bool = False) -> None:
        self.sidebar.add_footer_button(btn_id, text, emoji, icon_name, callback, active)

    def set_active_sidebar_button(self, btn_id: str) -> None:
        self.sidebar.set_active_button(btn_id)

    def update_status(self, message: str, color: str = "white") -> None:
        self.status_bar.update_status(message, color)

    def update_progress(self, percent: int) -> None:
        self.status_bar.set_progress(percent)
