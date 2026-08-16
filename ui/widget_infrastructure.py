# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/widget_infrastructure.py
# Rol Arquitectónico: UI Component / Infrastructure Controller
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.1.0 (Database Seeders & Healthchecks)
# =========================================================================================

"""
Panel de control de infraestructura del estudio.
Permite aprovisionar, iniciar y detener servidores locales (SVN, Kitsu) 
utilizando contenedores Docker efímeros para pruebas y desarrollo.
Incluye comandos automatizados para inyectar datos de prueba en la BD local.
"""

#import os
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QMessageBox, QGridLayout)
from PySide6.QtCore import QThread, Signal

from core.kitsu_manager import KitsuManager

class DockerWorker(QThread):
    """Hilo secundario para no congelar la UI mientras Docker descarga y levanta contenedores."""
    finished_signal = Signal(bool, str)
    
    def __init__(self, command: list, cwd: Path = None):
        super().__init__()
        self.command = command
        self.cwd = cwd

    def run(self):
        try:
            result = subprocess.run(
                self.command,
                cwd=self.cwd,
                check=True,
                capture_output=True,
                text=True
            )
            self.finished_signal.emit(True, "Operación completada exitosamente.")
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else str(e)
            self.finished_signal.emit(False, f"Fallo en Docker: {error_msg}")
        except Exception as e:
            self.finished_signal.emit(False, f"Error del sistema: {str(e)}")


class KitsuSeederWorker(QThread):
    """Hilo dedicado a interactuar con la base de datos de Kitsu vía Gazu y línea de comandos."""
    finished_signal = Signal(bool, str)

    def __init__(self, action: str):
        super().__init__()
        self.action = action

    def run(self):
        try:
            if self.action == "admin":
                # 1. Creamos al admin vía CLI de Zou en Docker para bypassear la falta inicial de sesión
                # La contraseña debe tener al menos 8 caracteres para no fallar la validación interna
                pwd = "entrando1"
                cmd = [
                    "docker", "exec", "kitsu_local-zou-app", "zou", 
                    "create-admin", "admin@example.com", "--password", pwd
                ]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                self.finished_signal.emit(True, "Admin Creado: admin@example.com / entrando1")

            elif self.action == "dummy":
                # 2. Inyectamos a los usuarios Dummy consumiendo el Manager
                kitsu_mgr = KitsuManager()
                # Sobrescribimos temporalmente el host para apuntar al entorno de prueba local (Docker)
                import gazu
                gazu.set_host('http://localhost:8080/api')
                
                success, msg = kitsu_mgr.seed_test_database(
                    admin_email="admin@example.com", 
                    admin_pwd="entrando1"
                )
                self.finished_signal.emit(success, msg)
                
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else str(e)
            self.finished_signal.emit(False, f"Error del Contenedor: {error_msg}")
        except Exception as e:
            self.finished_signal.emit(False, f"Fallo en Seeder: {str(e)}")


class InfrastructureWidget(QFrame):
    def __init__(self, parent, config_factory, status_callback, **kwargs):
        super().__init__(parent, **kwargs)
        self.config_factory = config_factory
        self.status_callback = status_callback
        
        self.infra_dir = self.config_factory.get_workspace_root() / ".openstudio_infra"
        self.infra_dir.mkdir(parents=True, exist_ok=True)
        
        self.setObjectName("InfrastructureBase")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # ---------------------------------------------------------
        # HEADER
        # ---------------------------------------------------------
        header = QLabel(self.tr("Studio Infrastructure (Zero-Config Environments)"))
        header.setStyleSheet("color: #F8FAFC; font-size: 20px; font-weight: bold;")
        layout.addWidget(header)
        
        desc = QLabel(self.tr("Deploy local instances of Subversion and Kitsu for testing and development. Requires Docker installed and running."))
        desc.setStyleSheet("color: #94A3B8; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ---------------------------------------------------------
        # GRID CARDS
        # ---------------------------------------------------------
        grid = QGridLayout()
        grid.setSpacing(20)

        # TARJETA 1: SVN SERVER
        svn_card = self._build_service_card(
            title="Local VCS Server (SVN)",
            desc=self.tr("Centralized version control system for binary assets and scenes."),
            port="3690",
            start_callback=self._deploy_svn,
            stop_callback=self._stop_svn
        )
        grid.addWidget(svn_card, 0, 0)

        # TARJETA 2: KITSU TRACKER (CON BOTONES EXTRA)
        kitsu_card = self._build_kitsu_service_card()
        grid.addWidget(kitsu_card, 0, 1)

        layout.addLayout(grid)
        layout.addStretch()

    def _build_service_card(self, title: str, desc: str, port: str, start_callback, stop_callback) -> QFrame:
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background-color: #1E293B; border-radius: 12px; border: 1px solid #334155; }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 20, 20, 20)
        
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #F8FAFC; font-size: 16px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_title)
        
        lbl_desc = QLabel(desc)
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px; border: none;")
        lbl_desc.setWordWrap(True)
        c_layout.addWidget(lbl_desc)
        
        lbl_port = QLabel(f"Port: {port}")
        lbl_port.setStyleSheet("color: #3B82F6; font-size: 11px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_port)
        
        c_layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_start = QPushButton(self.tr("Deploy & Start"))
        btn_start.setStyleSheet("""
            QPushButton { background-color: #10B981; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #059669; }
        """)
        btn_start.clicked.connect(start_callback)
        
        btn_stop = QPushButton(self.tr("Stop & Destroy"))
        btn_stop.setStyleSheet("""
            QPushButton { background-color: #EF4444; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #DC2626; }
        """)
        btn_stop.clicked.connect(stop_callback)
        
        btn_layout.addWidget(btn_start)
        btn_layout.addWidget(btn_stop)
        
        c_layout.addLayout(btn_layout)
        return card

    def _build_kitsu_service_card(self) -> QFrame:
        """Constructor especializado para Kitsu que incluye los botones de sembrado de base de datos."""
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background-color: #1E293B; border-radius: 12px; border: 1px solid #334155; }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 20, 20, 20)
        c_layout.setSpacing(10)
        
        lbl_title = QLabel("Production Tracker (Kitsu 1.0+)")
        lbl_title.setStyleSheet("color: #F8FAFC; font-size: 16px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_title)
        
        lbl_desc = QLabel(self.tr("Database, API, and Web Frontend for Shot and Asset management."))
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px; border: none;")
        lbl_desc.setWordWrap(True)
        c_layout.addWidget(lbl_desc)
        
        lbl_port = QLabel(f"Port: 8080")
        lbl_port.setStyleSheet("color: #3B82F6; font-size: 11px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_port)
        
        c_layout.addStretch()
        
        # Fila 1 de Botones: Control de Ciclo de Vida
        btn_layout1 = QHBoxLayout()
        btn_start = QPushButton(self.tr("Deploy & Start"))
        btn_start.setStyleSheet("""
            QPushButton { background-color: #10B981; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #059669; }
        """)
        btn_start.clicked.connect(self._deploy_kitsu)
        
        btn_stop = QPushButton(self.tr("Stop & Destroy"))
        btn_stop.setStyleSheet("""
            QPushButton { background-color: #EF4444; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #DC2626; }
        """)
        btn_stop.clicked.connect(self._stop_kitsu)
        btn_layout1.addWidget(btn_start)
        btn_layout1.addWidget(btn_stop)
        
        # Fila 2 de Botones: Base de Datos & Sembrado
        btn_layout2 = QHBoxLayout()
        btn_seed_admin = QPushButton(self.tr("1. Create Admin Account"))
        btn_seed_admin.setToolTip("Ejecuta 'zou create-admin' dentro del contenedor.")
        btn_seed_admin.setStyleSheet("""
            QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 8px; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: #475569; }
        """)
        btn_seed_admin.clicked.connect(lambda: self._ejecutar_seeder("admin"))
        
        btn_seed_dummy = QPushButton(self.tr("2. Seed Dummy Team"))
        btn_seed_dummy.setToolTip("Inyecta a PM, TD y Artist vía Gazu API.")
        btn_seed_dummy.setStyleSheet("""
            QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 8px; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: #475569; }
        """)
        btn_seed_dummy.clicked.connect(lambda: self._ejecutar_seeder("dummy"))
        btn_layout2.addWidget(btn_seed_admin)
        btn_layout2.addWidget(btn_seed_dummy)

        c_layout.addLayout(btn_layout1)
        c_layout.addLayout(btn_layout2)
        
        return card

    # ---------------------------------------------------------
    # SVN CONTROLLERS
    # ---------------------------------------------------------
    def _deploy_svn(self):
        self.status_callback(self.tr("Deploying Local SVN Server. Please wait..."), "yellow")
        command = [
            "docker", "run", "-d", 
            "--name", "openstudio_local_svn", 
            "-p", "3690:3690", 
            "elleflorio/svn-server"
        ]
        self._run_docker_worker(command)

    def _stop_svn(self):
        self.status_callback(self.tr("Destroying SVN Server..."), "yellow")
        subprocess.run(["docker", "stop", "openstudio_local_svn"], capture_output=True)
        subprocess.run(["docker", "rm", "openstudio_local_svn"], capture_output=True)
        self.status_callback(self.tr("SVN Server destroyed."), "green")

    # ---------------------------------------------------------
    # KITSU CONTROLLERS
    # ---------------------------------------------------------
    def _deploy_kitsu(self):
        self.status_callback(self.tr("Generando nueva arquitectura Docker Compose para Kitsu. Espere por favor..."), "yellow")
        
        # 1. Preparar archivos locales requeridos por los volúmenes
        db_dir = self.infra_dir / "db"
        db_dir.mkdir(exist_ok=True)
        pg_ctl = db_dir / "pg_ctl.conf"
        if not pg_ctl.exists():
            pg_ctl.write_text("# Autogenerado por la Infraestructura de Open Studio Hub\n")

        # 2. Generar archivo 'env'
        env_content = """COMPOSE_PROJECT_NAME=kitsu_local
ENV_FILE=env
KITSU_VERSION=latest
ZOU_VERSION=latest
KV_HOST=redis
KV_PORT=6379
DB_HOST=db
DB_VERSION=18
DB_USERNAME=postgres
DB_PASSWORD=Un53cur3Pa55w0rd
DB_DATABASE=zoudb
DB_DATA_PATH=/var/lib/data
ENABLE_JOB_QUEUE=True
PREVIEW_FOLDER=/opt/zou/previews
TMP_DIR=/tmp/zou
EVENT_STREAM_HOST=zou-event
PORT=80
INDEXER_VERSION=v1.31
INDEXER_KEY=Un53cur3Ma55t3rK3y
INDEXER_HOST=indexer
INDEXER_PORT=7700
USER_LIMIT=200
SECRET_KEY=Op3nStud1oHubZ0uS3cr3tK3y2026V3ryS3cur3
"""
        with open(self.infra_dir / "env", "w") as f:
            f.write(env_content)

        # 3. Generar Docker Compose con inicialización inteligente (healthchecks y comandos pre-boot)
        compose_content = r"""x-base: &base
    restart: always
    networks:
        - internal

x-env: &env
    env_file:
        - ${ENV_FILE:-./env}

x-backend-volumes: &backend_volumes
    volumes:
        - 'previews:${PREVIEW_FOLDER:?}'
        - 'tmp:${TMP_DIR:-/tmp/zou}'

services:
    kitsu:
        <<: [*base, *env]
        container_name: ${COMPOSE_PROJECT_NAME:?}-frontend
        image: registry.gitlab.com/mathbou/docker-cgwire/kitsu:${KITSU_VERSION:-latest}
        ports:
            - "8080:80"
        depends_on:
            zou-app:
                condition: service_healthy
            zou-event:
                condition: service_started
            zou-jobs:
                condition: service_started

    zou-app:
        <<: [*base,*env, *backend_volumes]
        container_name: ${COMPOSE_PROJECT_NAME:?}-zou-app
        image: registry.gitlab.com/mathbou/docker-cgwire/zou:${ZOU_VERSION:-latest}
        depends_on:
            db:
                condition: service_healthy
            indexer:
                condition: service_healthy
        command: >
            sh -c "zou init-db || true &&
                   zou upgrade-db || true &&
                   zou init-data || true &&
                   gunicorn --error-logfile - --access-logfile - -w 3 -k gevent -b :5000 zou.app:app"
        healthcheck:
            test: "curl -s -f http://localhost:5000 | grep -q '\"api\":\"Zou\"'"

    zou-event:
        <<: [*base, *env]
        container_name: ${COMPOSE_PROJECT_NAME:?}-zou-event
        image: registry.gitlab.com/mathbou/docker-cgwire/zou:${ZOU_VERSION:-latest}
        depends_on:
            redis:
                condition: service_started
            zou-app:
                condition: service_healthy
        command: "gunicorn --error-logfile - --access-logfile - -w 1 -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -b :5001 zou.event_stream:app"
        healthcheck:
            test: "curl -s -f http://localhost:5001 | grep -q '\"api\":\"Zou\"'"

    zou-jobs:
        <<: [*base, *env, *backend_volumes]
        container_name: ${COMPOSE_PROJECT_NAME:?}-zou-jobs
        image: registry.gitlab.com/mathbou/docker-cgwire/zou:${ZOU_VERSION:-latest}
        depends_on:
            zou-app:
                condition: service_healthy
        command: "rq worker -c zou.job_settings"
        healthcheck:
            test: "rq info -u redis://${KV_HOST:?}:${KV_PORT:-6379}/3 -W | grep -v -q '0 workers'"

    db:
        <<: *base
        container_name: ${COMPOSE_PROJECT_NAME:?}-db-${DB_VERSION:?}
        image: postgres:${DB_VERSION:?}-alpine
        volumes:
            - 'db:${DB_DATA_PATH:?}'
            - ./db/pg_ctl.conf:/etc/postgresql/${DB_VERSION:?}/main/pg_ctl.conf:ro
        environment:
            - POSTGRES_PASSWORD=${DB_PASSWORD:?}
            - POSTGRES_DB=zoudb
        healthcheck:
            test: "pg_isready -d zoudb -U postgres"

    redis:
        <<: *base
        container_name: ${COMPOSE_PROJECT_NAME:?}-redis
        image: redis:alpine
        volumes:
            - 'redis:/data'
    
    indexer:
        <<: *base
        container_name: ${COMPOSE_PROJECT_NAME:?}-indexer-${INDEXER_VERSION:?}
        image: getmeili/meilisearch:${INDEXER_VERSION:?}
        volumes:
            - 'indexer:/meili_data'
        environment:
            - MEILI_MASTER_KEY=${INDEXER_KEY:?}
        healthcheck:
            test: "curl -s -f http://localhost:${INDEXER_PORT:-7700}/health | grep -q '{\"status\":\"available\"}'"

volumes:
    db:
        name: ${COMPOSE_PROJECT_NAME:?}-db-${DB_VERSION:?}
    redis:
        name: ${COMPOSE_PROJECT_NAME:?}-redis
    previews:
        name: ${COMPOSE_PROJECT_NAME:?}-previews
    tmp:
        name: ${COMPOSE_PROJECT_NAME:?}-tmp
    indexer:
        name: ${COMPOSE_PROJECT_NAME:?}-indexer-${INDEXER_VERSION:?}
        
networks:
    internal:
        name: ${COMPOSE_PROJECT_NAME:?}-internal
"""
        compose_path = self.infra_dir / "docker-compose.yml"
        with open(compose_path, "w") as f:
            f.write(compose_content)

        # 4. Levantar Contenedores asíncronamente
        command = ["docker", "compose", "--env-file", "env", "up", "-d"]
        self._run_docker_worker(command, cwd=self.infra_dir)

    def _stop_kitsu(self):
        self.status_callback(self.tr("Tearing down Kitsu Stack..."), "yellow")
        command = ["docker", "compose", "down", "-v"] 
        self._run_docker_worker(command, cwd=self.infra_dir)

    # ---------------------------------------------------------
    # SEEDER DISPATCHER
    # ---------------------------------------------------------
    def _ejecutar_seeder(self, action: str):
        self.status_callback(self.tr("Ejecutando Seeder en la Base de Datos..."), "yellow")
        self.seeder_worker = KitsuSeederWorker(action)
        self.seeder_worker.finished_signal.connect(self._on_worker_finished)
        self.seeder_worker.finished.connect(self.seeder_worker.deleteLater)
        self.seeder_worker.start()

    # ---------------------------------------------------------
    # WORKER CALLBACK
    # ---------------------------------------------------------
    def _run_docker_worker(self, command: list, cwd: Path = None):
        self.worker = DockerWorker(command, cwd)
        self.worker.finished_signal.connect(self._on_worker_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _on_worker_finished(self, success: bool, message: str):
        color = "green" if success else "red"
        self.status_callback(message, color)
        if not success:
            QMessageBox.critical(self, self.tr("Error de Infraestructura"), message)
