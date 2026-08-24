# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/web_context_view.py
# Rol Arquitectónico: UI View / Immersive Web Context (Kitsu / Watchtower)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.1.0
# =========================================================================================

from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices

# Módulos específicos del navegador web embebido
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings

class CustomWebPage(QWebEnginePage):
    """
    Página web personalizada para interceptar la navegación.
    Evita que el usuario salga del contexto de Kitsu/Watchtower haciendo
    clic en enlaces externos (como Google Drive, YouTube, etc).
    """
    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self.allowed_hosts = []

    def set_allowed_hosts(self, hosts: list):
        self.allowed_hosts = hosts

    def acceptNavigationRequest(self, url: QUrl, _type: QWebEnginePage.NavigationType, isMainFrame: bool) -> bool:
        # Si el usuario hace clic explícitamente en un enlace
        if _type == QWebEnginePage.NavigationTypeLinkClicked:
            host = url.host()
            # Validamos si el host del link está en nuestra lista blanca
            if not any(allowed in host for allowed in self.allowed_hosts):
                print(f"[WebContext] Redirigiendo enlace externo al SO: {url.toString()}")
                QDesktopServices.openUrl(url)
                return False # Bloqueamos que se abra dentro de nuestro Hub
                
        return super().acceptNavigationRequest(url, _type, isMainFrame)


class WebContextView(QFrame):
    # Señal que avisará al Orquestador (OpenStudioHub) que debe cambiar de capa
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WebContextView")
        self.setStyleSheet("background-color: #0F172A;") # Fondo base del Hub

        # --- Control de estado para SSO ---
        #self.sso_token = None
        #self._token_injected = False
        
        
        self._build_ui()

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # ---------------------------------------------------------
        # 1. TOP BAR (Controles de Navegación)
        # ---------------------------------------------------------
        self.top_bar = QFrame()
        self.top_bar.setFixedHeight(50)
        self.top_bar.setStyleSheet("background-color: #1E293B; border-bottom: 1px solid #141820;")
        
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(15, 0, 15, 0)
        top_layout.setSpacing(15)

        # Botón Volver
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

        # Indicador de estado/Título
        self.lbl_title = QLabel("Initializing...")
        self.lbl_title.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 13px; border: none;")
        top_layout.addWidget(self.lbl_title)
        
        top_layout.addStretch()
        self.main_layout.addWidget(self.top_bar)

        # ---------------------------------------------------------
        # 2. WEB ENGINE (El navegador incrustado)
        # ---------------------------------------------------------
        self.web_view = QWebEngineView()
        
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        # Inyectamos nuestra página personalizada con lógica de enlaces
        # Usamos el perfil por defecto (o podríamos crear uno aislado si queremos modo incógnito)
        self.custom_page = CustomWebPage(self.web_view.page().profile(), self.web_view)
        self.web_view.setPage(self.custom_page)
        
        self.main_layout.addWidget(self.web_view, stretch=1)

        # Conectar señales de estado del navegador
        self.web_view.loadStarted.connect(lambda: self.lbl_title.setText("Loading..."))
        self.web_view.loadFinished.connect(self._on_load_finished)

    def load_context(self, url_str: str, context_name: str, allowed_hosts: list, sso_token: str = None):
        """
        Inicia la carga de la vista web.
        Ejemplo: load_context("http://localhost:8080", "Kitsu", ["localhost", "kitsu.midominio.com"])
        """
        self.lbl_title.setText(f"Connecting to {context_name}...")
        self.custom_page.set_allowed_hosts(allowed_hosts)

        scripts = self.web_view.page().scripts()
        for script in scripts.toList():
            if script.name() == "Kitsu_SSO_Injector":
                scripts.remove(script)

        if sso_token:
            sso_script = QWebEngineScript()
            sso_script.setName("Kitsu_SSO_Injetor")

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
                        console.error('Error inyectando SSO token nativo:', e);
                    }}
                }})();
            """)

            sso_script.setInjectionPoint(QWebEngineScript.DocumentCreation)
            sso_script.setWorldId(QWebEngineScript.MainWorld)
            sso_script.setRunsOnSubFrames(False)

            scripts.insert(sso_script)

        self.web_view.setUrl(QUrl(url_str))

    def inject_javascript(self, js_code: str):
        """Método de utilidad para inyectar tokens o cookies (Problema de Doble Login)."""
        self.web_view.page().runJavaScript(js_code)

    def _on_load_finished(self, success: bool):
        if success:
            # Tomamos el título real de la página web (Ej: "Kitsu - My Project")
            self.lbl_title.setText(self.web_view.title())

        else:
            self.lbl_title.setText("Connection failed. Please check network.")

    def _on_back_clicked(self):
        """Se ejecuta al intentar volver. Limpia procesos y notifica al Orquestador."""
        self.lbl_title.setText("Closing...")
        self.web_view.stop()
        
        # Navegamos a about:blank para purgar el DOM, destruir iframes y detener videos/scripts
        self.web_view.setUrl(QUrl("about:blank"))
        
        # Le decimos al Orquestador que quite esta capa
        self.back_requested.emit()
