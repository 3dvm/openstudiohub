# =========================================================================================
# OPENSTUDIOHUB
# Módulo: openstudio_hub.py
# Rol Arquitectónico: Main App Root / Orquestador Inicial (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.8.0
# =========================================================================================

"""
Punto de entrada principal de OpenStudio Hub.
Inicializa el entorno gráfico nativo en Qt (PySide6), lee la configuración maestra B2B,
gestiona el enrutamiento base (Login vs Dashboard) e implementa el guardián de procesos.
Optimizado para Cero-Latencia en el arranque del Dashboard y enrutamiento PM.
"""

from _version import __version__

import sys
import os
from pathlib import Path
import urllib.parse

# --- PySide6 (Motor Gráfico) ---
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget
from ui.web_context_view import WebContextView
from PySide6.QtCore import QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon

# --- CORE (Motores) ---
#from core import vault_manager
from core.auth_manager import AuthManager
from core.vault_manager import VaultManager
from core.config_factory import ConfigFactory
from core.watchtower_launcher import WatchtowerLauncher
from core.kitsu_manager import KitsuManager

# --- UI (Vistas) ---
from ui.view_login import ViewLogin
from ui.view_artist import ViewArtist
from ui.view_td import ViewTD
from ui.view_pm import ViewPM

if getattr(sys, 'frozen', False):
    os.chdir(sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable))

class OpenStudioHub(QMainWindow):
    def __init__(self):
        super().__init__()

        # Título base (Se sobrescribe dinámicamente tras el login)
        self.setWindowTitle(f"OpenStudioHub - v{__version__}")
        self.resize(1000, 700) 
        self.setMinimumSize(800, 600)

        self.setWindowIcon(QIcon("assets/openstudiohub.ico"))

        # Guardián de Procesos (Protección de Lock Passing)
        self.blender_instances = 0

        # 1. Inicializar los Motores Base
        self.auth = AuthManager()
        settings_path = Path("settings.json")
        self.config_factory = ConfigFactory(settings_path)
        self.vault = VaultManager(self.config_factory)
        

        # 2. Enrutador Inicial (State Machine MVC)
        self.mostrar_login()

    def registrar_instancia(self, activa: bool):
        """Incrementa o decrementa el contador de instancias de Blender activas."""
        if activa:
            self.blender_instances += 1
        else:
            self.blender_instances = max(0, self.blender_instances - 1)

    def closeEvent(self, event: QCloseEvent):
        """Intercepta el cierre de la ventana nativa de Qt para proteger la integridad del SVN."""
        if self.blender_instances > 0:
            mensaje = self.tr(
                "You have {0} 3D environment session(s) open.\n\n"
                "Please close the program first to release the master files on the server (SVN Unlock) "
                "and avoid production corruption."
            ).format(self.blender_instances)
            
            QMessageBox.warning(
                self,
                self.tr("Blocked Operation"),
                mensaje
            )
            event.ignore() 
        else:
            self.auth.logout()
            self.vault.clear()
            event.accept()

    def mostrar_login(self):
        """Monta la vista de Login en el contenedor central."""
        self.setWindowTitle(f"OpenStudio Hub - v{__version__}")
        
        vista_login = ViewLogin(
            parent=self, 
            auth_manager=self.auth, 
            vault_manager=self.vault, 
            config_factory=self.config_factory,
            on_login_success=self.mostrar_dashboard
        )
        self.setCentralWidget(vista_login)

    def mostrar_dashboard(self):
        """Monta el Dashboard inyectando el contexto B2B local (Cero Latencia)."""
        # Leemos el nombre del estudio directamente de la configuración local (SSoT)
        studio_name = self.config_factory.get_studio_name()
        if not studio_name:
            studio_name = "OpenStudio"
            
        self.setWindowTitle(f"{studio_name} Hub - v{__version__}")
        
        # Enrutamiento de Vistas (Factory)
        rol = self.auth.get_user_role()
        posicion = self.auth.get_user_position()

        nas_dir = self.config_factory.get_workspace_root()
        
        if rol in ["td"]:
            self.vista_actual = ViewTD(
                parent=self, 
                auth_manager=self.auth, 
                nas_dir=nas_dir, 
                vault_manager=self.vault,
                config_factory=self.config_factory,
                on_logout=self.ejecutar_logout
            )
        elif rol in ["manager"]:
            # Función anónima para mapear el status_callback a la barra de estado de QMainWindow

            if "lead" in posicion:
                # EL INFILTRADO: Es un Manager en Kitsu, pero Artista (Editor) en el Hub
                print("[OpenStudio Hub] Perfil Híbrido Detectado: Editor (Manager+Lead). Enrutando a ViewArtist.")
                self.vista_actual = ViewArtist(
                    self,
                    self.auth,
                    nas_dir,
                    self.vault,
                    self.config_factory,
                    self.ejecutar_logout)
            else:
                # El Production Manager real
                self.vista_actual = ViewPM(
                    parent=self,
                    auth_manager=self.auth,
                    config_factory=self.config_factory,
                    vault_manager=self.vault,
                    on_logout=self.ejecutar_logout
                )
        else:
            self.vista_actual = ViewArtist(
                parent=self, 
                auth_manager=self.auth, 
                nas_dir=nas_dir,
                vault_manager=self.vault,
                config_factory=self.config_factory,
                on_logout=self.ejecutar_logout
            )

        # 2. NUEVO: Implementamos el Sistema de Capas (Stack)
        self.view_stack = QStackedWidget()
        
        # Capa 0: El Dashboard 
        self.view_stack.addWidget(self.vista_actual)
        
        # Capa 1: El Contexto Web (Kitsu/Watchtower)
        self.web_context = WebContextView(self)
        self.web_context.back_requested.connect(self.cerrar_kitsu)
        self.view_stack.addWidget(self.web_context)
        
        self.setCentralWidget(self.view_stack)

    def abrir_kitsu(self, target_url: str = None):
        """Extrae la URL de Kitsu, limpia el sufijo /api y cambia la capa visual."""
        # Obtenemos la URL (ej: "http://localhost:8080" o "http://localhost:8080/api")
        kitsu_url = self.config_factory.get_kitsu_api_url()
        
        # Limpiamos /api porque queremos cargar la Interfaz Gráfica, no el endpoint crudo
        if kitsu_url.endswith("/api"):
            kitsu_url = kitsu_url[:-4]
        
        if not target_url:
            target_url = f"{kitsu_url}/news-feed"

        if False: # hay que solucionar el SSO primero
            # Parseamos el host para inyectarlo en la lista blanca de seguridad (Whitelisting de enlaces)
            parsed_url = urllib.parse.urlparse(kitsu_url)
            allowed_hosts = [parsed_url.hostname, "localhost", "127.0.0.1"]

            token = self.auth.get_current_token()
            
            # Cargamos el navegador y cambiamos la vista
            self.web_context.load_context(target_url, "Kitsu", allowed_hosts, sso_token=token)
            self.view_stack.setCurrentWidget(self.web_context)
            
        else:
            QDesktopServices.openUrl(QUrl(target_url))

    def cerrar_kitsu(self):
        """Regresa al Dashboard nativo (Capa 0) y gatilla un refresco de datos."""
        self.view_stack.setCurrentWidget(self.vista_actual)
        
        # Aquí más adelante podemos hacer que dispare una señal para que 
        # el ActivityCard o el PM Dashboard recarguen los datos recientes.
        print("[OpenStudio Hub] Regreso de Kitsu completado.")

    def abrir_watchtower(self, project_root_path: Path, project_id: str = ""):
        """Inicializa el servidor local de Watchtower y enruta la vista."""

        # --- VERIFICACIÓN DE VIDEO DE EDICIÓN ---
        if project_id:
            kitsu_mgr = KitsuManager()
            if not kitsu_mgr.check_edit_preview_exists(project_id):
                QMessageBox.warning(
                    self, 
                    "Edición No Renderizada", 
                    "No hay un video renderizado para el Edit en Kitsu.\n\n"
                    "Watchtower requiere el archivo de edición principal para funcionar.\n"
                    "Por favor, renderiza y haz Push del Master Edit desde Blender antes de abrir Watchtower."
                )
                return
        # ----------------------------------------

        # Extraemos las credenciales guardadas en la bóveda
        kitsu_url = self.config_factory.get_kitsu_api_url()
        kitsu_user = getattr(self.vault, '_transient_email', "")
        kitsu_pwd = getattr(self.vault, '_transient_password', "")

        #breakpoint()

        # Instanciamos el launcher
        self.wt_launcher = WatchtowerLauncher(
            project_root_path,
            kitsu_url,
            kitsu_user,
            kitsu_pwd,
            lambda msg, color: print(f"[Watchtower] {msg}"),
            self.config_factory
        )
        
        # Conectamos la señal que emite la URL
        self.wt_launcher.server_ready.connect(self._on_watchtower_ready)
        self.wt_launcher.launch()

    def _on_watchtower_ready(self, url: str):
        """Recibe la URL del servidor local y cambia la capa visual."""
        # Como no enviamos el parámetro sso_token, la vista actuará como un navegador normal
        self.web_context.load_context(url, "Watchtower", ["localhost", "127.0.0.1"])
        self.view_stack.setCurrentWidget(self.web_context)

    def ejecutar_logout(self):
        """Limpia el estado global de Qt y revierte al formulario de acceso."""
        if self.blender_instances > 0:
            self.close() 
            return
            
        self.auth.logout()
        self.vault.clear()  
        self.mostrar_login()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # ---------------------------------------------------------
    # INYECCIÓN GLOBAL DE ESTILOS (QSS)
    # ---------------------------------------------------------
    theme_path = Path("macuare_theme.qss")
    if theme_path.exists():
        try:
            with open(theme_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
            print("[OPENSTUDIO HUB] ✓ Corporate QSS theme loaded successfully.")
        except Exception as e:
            print(f"[OPENSTUDIO HUB] ❌ Error reading QSS file: {e}")
    else:
        print("[OPENSTUDIO HUB] ⚠️ WARNING: 'macuare_theme.qss' not found. Starting with OS native theme.")
        
    window = OpenStudioHub()
    window.show()
    sys.exit(app.exec())
