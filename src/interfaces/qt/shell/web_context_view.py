# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/shell/web_context_view.py
# Architectural role: UI View / Immersive Web Context (Kitsu / Watchtower)
# =========================================================================================

"""Embedded web view for the Kitsu / Watchtower contexts.

The custom page intercepts navigation so external links open in the OS browser
instead of escaping the Hub context.
"""

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class CustomWebPage(QWebEnginePage):
    """Custom web page that intercepts navigation to external hosts."""

    def __init__(self, profile: QWebEngineProfile, parent=None) -> None:
        super().__init__(profile, parent)
        self.allowed_hosts = []

    def set_allowed_hosts(self, hosts: list) -> None:
        self.allowed_hosts = hosts

    def acceptNavigationRequest(self, url: QUrl, navigation_type, is_main_frame: bool) -> bool:
        if navigation_type == QWebEnginePage.NavigationTypeLinkClicked:
            host = url.host()
            if not any(allowed in host for allowed in self.allowed_hosts):
                print(f"[WebContext] Redirecting external link to the OS: {url.toString()}")
                QDesktopServices.openUrl(url)
                return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


class WebContextView(QFrame):
    """Immersive web layer. Emits ``back_requested`` when the user returns."""

    back_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("WebContextView")
        self.setStyleSheet("background-color: #0F172A;")

        self._build_ui()

    def _build_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.top_bar = QFrame()
        self.top_bar.setFixedHeight(50)
        self.top_bar.setStyleSheet("background-color: #1E293B; border-bottom: 1px solid #141820;")

        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(15, 0, 15, 0)
        top_layout.setSpacing(15)

        self.btn_back = QPushButton("⬅  Return to Hub")
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6; color: white; border-radius: 6px;
                padding: 6px 15px; font-weight: bold; font-size: 13px; border: none;
            }
            QPushButton:hover { background-color: #2563EB; }
        """)
        self.btn_back.clicked.connect(self._on_back_clicked)
        top_layout.addWidget(self.btn_back)

        self.lbl_title = QLabel("Initializing...")
        self.lbl_title.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 13px; border: none;")
        top_layout.addWidget(self.lbl_title)

        top_layout.addStretch()
        self.main_layout.addWidget(self.top_bar)

        self.web_view = QWebEngineView()
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self.custom_page = CustomWebPage(self.web_view.page().profile(), self.web_view)
        self.web_view.setPage(self.custom_page)

        self.main_layout.addWidget(self.web_view, stretch=1)

        self.web_view.loadStarted.connect(lambda: self.lbl_title.setText("Loading..."))
        self.web_view.loadFinished.connect(self._on_load_finished)

    def load_context(self, url_str: str, context_name: str, allowed_hosts: list, sso_token: str | None = None) -> None:
        """Start loading the web view."""
        self.lbl_title.setText(f"Connecting to {context_name}...")
        self.custom_page.set_allowed_hosts(allowed_hosts)

        scripts = self.web_view.page().scripts()
        for script in scripts.toList():
            if script.name() == "Kitsu_SSO_Injector":
                scripts.remove(script)

        if sso_token:
            sso_script = QWebEngineScript()
            sso_script.setName("Kitsu_SSO_Injector")

            sso_script.setSourceCode(f"""
                (function() {{
                    if (window.location.protocol === 'about:' || window.location.protocol === 'data:') {{
                        return;
                    }}
                    try {{
                        window.localStorage.setItem('access_token', '{sso_token}');
                        window.localStorage.setItem('refresh_token', '{sso_token}');
                        window.localStorage.setItem('token', '{sso_token}');
                    }} catch (e) {{
                        console.error('Error injecting native SSO token:', e);
                    }}
                }})();
            """)

            sso_script.setInjectionPoint(QWebEngineScript.DocumentCreation)
            sso_script.setWorldId(QWebEngineScript.MainWorld)
            sso_script.setRunsOnSubFrames(False)

            scripts.insert(sso_script)

        self.web_view.setUrl(QUrl(url_str))

    def inject_javascript(self, js_code: str) -> None:
        """Inject tokens or cookies (double login problem)."""
        self.web_view.page().runJavaScript(js_code)

    def _on_load_finished(self, success: bool) -> None:
        if success:
            self.lbl_title.setText(self.web_view.title())
        else:
            self.lbl_title.setText("Connection failed. Please check network.")

    def _on_back_clicked(self) -> None:
        """Clean up the web process and notify the orchestrator."""
        self.lbl_title.setText("Closing...")
        self.web_view.stop()

        self.web_view.setUrl(QUrl("about:blank"))
        self.back_requested.emit()
