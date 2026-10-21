# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/shell/web_context_view.py
# Architectural role: UI View / Immersive Web Context (Kitsu / Watchtower)
# =========================================================================================

"""Embedded web view for the Kitsu / Watchtower contexts.

Kitsu's web frontend authenticates with the JWT cookies set by Zou, not with
localStorage tokens. The view therefore uses a dedicated off-the-record profile,
sets the access/refresh cookies from the Hub's current session and installs an
``Authorization`` header interceptor as a fallback for the Kitsu API.
"""

from PySide6.QtCore import QDateTime, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

ACCESS_COOKIE = "access_token_cookie"
REFRESH_COOKIE = "refresh_token_cookie"
REFRESH_COOKIE_PATH = "/auth/refresh-token"


class KitsuAuthInterceptor(QWebEngineUrlRequestInterceptor):
    """Inject the current JWT as a Bearer header on Kitsu API requests."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._host = ""
        self._token = ""

    def set_auth(self, host: str, token: str) -> None:
        self._host = (host or "").lower()
        self._token = token or ""

    def clear_auth(self) -> None:
        self._host = ""
        self._token = ""

    def interceptRequest(self, info) -> None:  # noqa: N802 (Qt override)
        if not self._host or not self._token:
            return
        url = info.requestUrl()
        if (url.host() or "").lower() != self._host:
            return
        if "/api/" not in (url.path() or ""):
            return
        info.setHttpHeader(
            b"Authorization", f"Bearer {self._token}".encode("utf-8")
        )


class CustomWebPage(QWebEnginePage):
    """Custom web page that intercepts navigation to external hosts."""

    def __init__(self, profile: QWebEngineProfile, parent=None) -> None:
        super().__init__(profile, parent)
        self.allowed_hosts = []

    def set_allowed_hosts(self, hosts: list) -> None:
        self.allowed_hosts = hosts

    def acceptNavigationRequest(self, url: QUrl, navigation_type, is_main_frame: bool) -> bool:
        if navigation_type == QWebEnginePage.NavigationTypeLinkClicked:
            host = (url.host() or "").lower()
            allowed = any(
                host == item.lower() or host.endswith("." + item.lower())
                for item in self.allowed_hosts
                if item
            )
            if not allowed:
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

        # Off-the-record profile: tokens/cookies stay in RAM only. Parent it to
        # the application so it outlives the page during teardown.
        app = QApplication.instance()
        self.profile = QWebEngineProfile(app if app is not None else self)
        self.auth_interceptor = KitsuAuthInterceptor(self)
        self.profile.setUrlRequestInterceptor(self.auth_interceptor)

        self._build_ui()

        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

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

        self.custom_page = CustomWebPage(self.profile, self.web_view)
        self.web_view.setPage(self.custom_page)

        self.main_layout.addWidget(self.web_view, stretch=1)

        self.web_view.loadStarted.connect(lambda: self.lbl_title.setText("Loading..."))
        self.web_view.loadFinished.connect(self._on_load_finished)

    def load_context(
        self,
        url_str: str,
        context_name: str,
        allowed_hosts: list,
        access_token: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        """Load a web context, optionally bootstrapping a Kitsu session."""
        self.lbl_title.setText(f"Connecting to {context_name}...")
        self.custom_page.set_allowed_hosts(allowed_hosts)

        parsed = QUrl(url_str)
        host = parsed.host()
        scheme = parsed.scheme() or "https"
        origin = QUrl(f"{scheme}://{parsed.authority()}/")

        self.auth_interceptor.clear_auth()
        if access_token and host:
            self.auth_interceptor.set_auth(host, access_token)
            self._set_auth_cookie(
                ACCESS_COOKIE, access_token, host, "/", origin, 7
            )
            if refresh_token:
                self._set_auth_cookie(
                    REFRESH_COOKIE,
                    refresh_token,
                    host,
                    REFRESH_COOKIE_PATH,
                    origin,
                    15,
                )

        self.web_view.setUrl(QUrl(url_str))

    @staticmethod
    def build_auth_cookie(
        name: str,
        value: str,
        host: str,
        path: str,
        secure: bool,
        days: int = 7,
    ) -> QNetworkCookie:
        cookie = QNetworkCookie(name.encode("utf-8"), value.encode("utf-8"))
        cookie.setDomain(host)
        cookie.setPath(path)
        cookie.setSecure(secure)
        cookie.setHttpOnly(True)
        cookie.setSameSitePolicy(QNetworkCookie.SameSite.Lax)
        cookie.setExpirationDate(QDateTime.currentDateTimeUtc().addDays(days))
        return cookie

    def _set_auth_cookie(
        self,
        name: str,
        value: str,
        host: str,
        path: str,
        origin: QUrl,
        days: int,
    ) -> None:
        cookie = self.build_auth_cookie(
            name,
            value,
            host,
            path,
            origin.scheme() == "https",
            days,
        )
        self.profile.cookieStore().setCookie(cookie, origin)

    def clear_auth(self) -> None:
        """Drop the Kitsu token and cookies (used on logout)."""
        self.auth_interceptor.clear_auth()
        self.profile.cookieStore().deleteAllCookies()
        self.web_view.setUrl(QUrl("about:blank"))

    def shutdown(self) -> None:
        """Release the page before the profile (QtWebEngine teardown order)."""
        try:
            self.web_view.stop()
            self.web_view.setPage(None)
        except RuntimeError:
            pass
        try:
            self.profile.setUrlRequestInterceptor(None)
        except RuntimeError:
            pass

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
