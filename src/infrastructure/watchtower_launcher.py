# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/watchtower_launcher.py
# Rol Arquitectónico: Subprocess Orchestrator / Ephemeral Web Server
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.6.5
# =========================================================================================

"""
Orquestador encargado de la integración de Watchtower (Visualización de Producción).
Extrae datos desde Kitsu, compila el cliente web mediante watchtower-pipeline 
y sirve los archivos JSON generados a través de un servidor HTTP local efímero 
en el navegador predeterminado del usuario.
"""

import os
import sys
import time
import socket
import threading
import subprocess
#import webbrowser
import http.server
import socketserver
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QUrl

from PySide6.QtGui import QCloseEvent, QDesktopServices

class WatchtowerLauncher(QObject):

    server_ready = Signal(str)

    def __init__(self, project_root: Path, kitsu_host: str, kitsu_user: str, kitsu_pwd: str, status_callback, config_factory):
        super().__init__()
        self.project_root = project_root
        self.kitsu_host = kitsu_host
        self.kitsu_user = kitsu_user
        self.kitsu_pwd = kitsu_pwd
        self.status_callback = status_callback
        self.config_factory = config_factory
        
        self.server_thread = None
        self.httpd = None

    def launch(self):
        """Inicia la extracción y el servidor en un hilo secundario."""
        threading.Thread(target=self._run_pipeline_and_serve, daemon=True).start()

    def _get_free_port(self) -> int:
        """Encuentra un puerto libre en el sistema operativo para evitar colisiones."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]

    def _run_pipeline_and_serve(self):
        # 1. Preparar directorio de trabajo aislado
        vfs_local = self.config_factory.get_vfs_local_name()
        wt_dir = self.project_root / vfs_local / "watchtower_build"
        wt_dir.mkdir(parents=True, exist_ok=True)

        self.status_callback("Watchtower: Extrayendo datos desde la API de Kitsu...", "yellow")

        # 2. Inyectar credenciales JIT en un .env temporal (0o600, siempre eliminado).
        #    NOTE: watchtower_pipeline reads a dotenv file, so the password touches disk
        #    only for the subprocess lifetime; it is removed in `finally` on every path.
        env_file_path = wt_dir / ".env.local"
        env_content = (
            f"KITSU_DATA_SOURCE_URL={self.kitsu_host}/api\n"
            f"KITSU_DATA_SOURCE_USER_EMAIL={self.kitsu_user}\n"
            f"KITSU_DATA_SOURCE_USER_PASSWORD={self.kitsu_pwd}\n"
        )

        # 3. Ejecutar el compilador (watchtower_pipeline.kitsu -b)
        try:
            fd = os.open(env_file_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(env_content)

            cmd = [sys.executable, "-m", "watchtower_pipeline.kitsu", "-b"]
            # Redirigimos el CWD al directorio temporal
            result = subprocess.run(cmd, cwd=str(wt_dir), capture_output=True, text=True)

            if result.returncode != 0:
                self.status_callback("Watchtower: Error al procesar datos de Kitsu.", "red")
                print("[WATCHTOWER ERROR DETALLADO]")
                print(f"--- STDOUT ---\n{result.stdout}")
                print(f"--- STDERR ---\n{result.stderr}")
                print("----------------------------")
                return

            self.status_callback("Watchtower: Datos procesados. Iniciando servidor local...", "yellow")

            # 4. Iniciar el servidor local apuntando al bundle generado
            serve_dir = wt_dir / "watchtower"
            if not serve_dir.exists():
                serve_dir = wt_dir  # Fallback en caso de que la API de watchtower cambie

            self._start_ephemeral_server(serve_dir)

        except Exception as e:
            self.status_callback(f"Watchtower: Fallo crítico en subproceso: {e}", "red")
        finally:
            if env_file_path.exists():
                env_file_path.unlink()

    def _start_ephemeral_server(self, serve_dir: Path):
        """Levanta un SimpleHTTPRequestHandler y abre el navegador del OS."""
        if self.httpd:
            self.status_callback("Watchtower ya se encuentra en ejecución.", "green")
            QDesktopServices.openUrl(QUrl(f"http://localhost:{self.httpd.server_address[1]}"))
            # self.server_ready.emit(f"http://localhost:{self.httpd.server_address[1]}")
            return 

        port = self._get_free_port()
        
        # Redirigir la ruta al directorio estático
        os.chdir(str(serve_dir))
        
        #Handler = http.server.SimpleHTTPRequestHandler
        try:
            from RangeHTTPServer import RangeRequestHandler as Handler
        except ImportError:
            self.status_callback("Watchtower: RangeHTTPServer no instalado. El video fallará.", "red")
            Handler = http.server.SimpleHTTPRequestHandler

        class DualStackServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True

        try:
            self.httpd = DualStackServer(("", port), Handler)
            
            # Lanzamos el servidor de forma asíncrona
            self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.server_thread.start()

            self.status_callback(f"Watchtower activo en puerto {port}", "green")
            
            # Damos un pequeño respiro al socket antes de abrir el navegador
            time.sleep(1.0)
            QDesktopServices.openUrl(QUrl(f"http://localhost:{port}"))
            #self.server_ready.emit(f"http://localhost:{port}")

        except OSError as e:
            self.status_callback(f"Watchtower: Fallo al enlazar el servidor local: {e}", "red")
