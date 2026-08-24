# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/widget_task_list.py
# Rol Arquitectónico: UI Component / JIT Interceptor / Artist Dashboard (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.1.0
# =========================================================================================

"""
Task Grid Component (Task List).
Refactored to apply Separation of Concerns (SoC) and native i18n.
Emits the project tree to the main view for lateral routing.
Adapted to the new VFS topology (local, shared, svn).
"""

import json
import time
from pathlib import Path

from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QScrollArea, QWidget)
from PySide6.QtCore import Qt, QThread, Signal, QTimer

from src.infrastructure.env_launcher import lanzar_blender
from src.application.local_installer import LocalInstaller
from src.infrastructure.vcs.vcs_router import VCSRouter
from src.domain.path_resolver import PathResolver

from src.interfaces.qt.window_svn_login import SVNLoginWindow
from src.interfaces.qt.components.task_card import TaskCard


class DataWorker(QThread):
    data_ready = Signal(list, dict, dict)
    status_update = Signal(str, str)

    def __init__(self, auth_manager, nextcloud_dir, config_factory):
        super().__init__()
        self.auth_manager = auth_manager
        self.nextcloud_dir = nextcloud_dir
        self.config_factory = config_factory

    def run(self):
        kitsu_projects_map = self.auth_manager.obtener_proyectos_activos()
        tasks = self.auth_manager.get_assigned_tasks()
        
        local_projects_map = {}
        prod_folder = self.config_factory.get_production_folder_name()

        if self.nextcloud_dir.exists():
            for carpeta in self.nextcloud_dir.iterdir():
                if carpeta.is_dir():
                    # Nueva ruta B2B alineada con Blender Studio Tools
                    init_path = carpeta / prod_folder / "pipeline" / "project_init.json"
                    if init_path.exists():
                        try:
                            with open(init_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                            nombre = data.get("project_name", carpeta.name).lower()
                            
                            if nombre in kitsu_projects_map:
                                local_projects_map[nombre] = carpeta
                        except Exception:
                            pass
                            
        self.data_ready.emit(tasks, local_projects_map, kitsu_projects_map)


class InstallWorker(QThread):
    status_update = Signal(str, str)
    finished_install = Signal(bool)

    def __init__(self, installer, project_root, svn_user, svn_pwd, user_role, task_metadata):
        super().__init__()
        self.installer = installer
        self.project_root = project_root
        self.svn_user = svn_user
        self.svn_pwd = svn_pwd
        self.user_role = user_role
        self.task_metadata = task_metadata

    def run(self):
        def safe_callback(msg, color="white"):
            self.status_update.emit(msg, color)

        exito, mensaje = self.installer.instalar_entorno(
            self.project_root, self.svn_user, self.svn_pwd, safe_callback,
            user_role=self.user_role, task_metadata=self.task_metadata
        )
        
        color_msg = "green" if exito else "red"
        self.status_update.emit(mensaje, color_msg)
        self.finished_install.emit(exito)


class LaunchWorker(QThread):
    status_update = Signal(str, str)
    process_finished = Signal()

    def __init__(self, project_root, config_path, svn_user, svn_pwd, kitsu_user, kitsu_pwd, 
                 kitsu_host, user_role, task_data, target_file, prod_folder, config_factory, auth_manager):
        super().__init__()
        self.project_root = project_root
        self.config_path = config_path
        self.svn_user = svn_user
        self.svn_pwd = svn_pwd
        self.kitsu_user = kitsu_user
        self.kitsu_pwd = kitsu_pwd
        self.kitsu_host = kitsu_host
        self.user_role = user_role
        self.task_data = task_data
        self.target_file = target_file
        self.prod_folder = prod_folder
        self.config_factory = config_factory
        self.auth_manager = auth_manager

    def run(self):
        def safe_callback(msg, color="white"):
            self.status_update.emit(msg, color)

        print(f"\n[LaunchWorker DEBUG] Orchestrating process for target_file: {self.target_file}")

        task_type = self.task_data.get("task_type_name", "unknown")
        adapter = None
        ruta_bloqueo = "edit/master_edit.blend"
        
        try:
            vcs_type = self.config_factory.get_vcs_adapter_type()
            base_url = self.config_factory.get_vcs_repository_url()
            repo_url = f"{base_url}/{self.project_root.name}/{self.prod_folder}"
            workspace = self.project_root / self.prod_folder
            
            router = VCSRouter(vcs_type=vcs_type, repo_url=repo_url, workspace_dir=workspace)
            adapter = router.get_adapter()
            adapter.cleanup()
        except Exception as e:
            print(f"[CLEANUP WARNING] Could not execute automatic workspace cleanup: {e}")

        requiere_bloqueo = task_type.lower() in ["edit", "editorial", "montaje"]
        cargo_usuario = self.auth_manager.get_user_position()
        
        cargos_autorizados = ["editor", "director", "lead"]
        roles_autorizados = ["td", "supervisor", "lead", "manager"]
        esta_autorizado = (self.user_role in roles_autorizados) or (cargo_usuario in cargos_autorizados)
        
        if requiere_bloqueo:
            if esta_autorizado:
                try:
                    adapter.lock(path=ruta_bloqueo, username=self.svn_user, password=self.svn_pwd)
                except Exception as e:
                    err_msg = str(e).lower()
                    if not ("already locked" in err_msg or "was not found" in err_msg or "e155010" in err_msg or "unversioned" in err_msg):
                        safe_callback("Access Denied: The file is currently in use by another artist.", "red")
                        self.process_finished.emit()
                        return
        
        try:
            print(f"[LaunchWorker DEBUG] Executing lanzar_blender with file: {self.target_file}")
            lanzar_blender(
                self.project_root, self.config_path, self.svn_user, self.svn_pwd, 
                self.kitsu_user, self.kitsu_pwd, self.kitsu_host, self.user_role, 
                self.task_data, self.target_file, safe_callback, 
                production_folder=self.prod_folder
            )
        except Exception as e:
            safe_callback(f"Critical error launching Blender: {str(e)}", "red")

        if adapter and requiere_bloqueo and esta_autorizado:
            try:
                adapter.unlock(path=ruta_bloqueo, username=self.svn_user, password=self.svn_pwd)
            except Exception:
                pass
                    
        self.process_finished.emit()


class TaskListWidget(QFrame):
    
    projects_discovered = Signal(dict) 

    def __init__(self, parent, nextcloud_dir: Path, auth_manager, vault_manager, config_factory, status_callback, **kwargs):
        super().__init__(parent, **kwargs)
        self.nextcloud_dir = nextcloud_dir
        self.auth_manager = auth_manager
        self.vault = vault_manager
        self.config_factory = config_factory
        self.status_callback = status_callback
        self.installer = LocalInstaller(nextcloud_dir, config_factory)
        self.all_tasks = []
        self.local_projects_map = {}
        self.active_kitsu_projects = {}
        self.current_filter = "All"
        self._last_refresh_time = 0
        
        self.setObjectName("TaskListWidgetBase")
        self.setStyleSheet("background: transparent;")
        
        self._build_ui()
        self.cargar_proyectos()

    def _build_ui(self):
        content_layout = QVBoxLayout(self)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        self.header_frame = QFrame(self)
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(0, 0, 0, 10)
        
        self.header_label = QLabel(self.tr("All Your Tasks"))
        self.header_label.setObjectName("H1Title")
        header_layout.addWidget(self.header_label)
        header_layout.addStretch()
        
        self.refresh_btn = QPushButton(self.tr("↻ Refresh"))
        self.refresh_btn.setObjectName("SecondaryButton")
        self.refresh_btn.setFixedSize(100, 28)
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._forzar_recarga)
        header_layout.addWidget(self.refresh_btn)
        content_layout.addWidget(self.header_frame)
        
        self.cards_scroll = QScrollArea(self)
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.cards_widget = QWidget()
        self.cards_widget.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setAlignment(Qt.AlignTop)
        
        self.cards_scroll.setWidget(self.cards_widget)
        content_layout.addWidget(self.cards_scroll, stretch=1)

    def aplicar_filtro(self, nombre_proyecto: str):
        self.current_filter = nombre_proyecto
        if nombre_proyecto == "All":
            self.header_label.setText(self.tr("All Your Tasks"))
        else:
            self.header_label.setText(self.tr("Tasks in: {0}").format(nombre_proyecto))
        self._render_tasks()

    def _clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _emit_status(self, msg: str, color: str = "white"):
        if self.status_callback:
            self.status_callback(msg, color)

    def _forzar_recarga(self):
        now = time.time()
        if now - self._last_refresh_time < 3:
            self._emit_status(self.tr("Please wait a few seconds before refreshing again..."), "yellow")
            return
        self._last_refresh_time = now
        self._emit_status(self.tr("Manual synchronization forced."), "white")
        self.cargar_proyectos()

    def cargar_proyectos(self):
        self._clear_layout(self.cards_layout)
        self.loading_label = QLabel(self.tr("Syncing tasks with database..."))
        self.loading_label.setStyleSheet("color: #94A3B8; font-style: italic;")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.cards_layout.addWidget(self.loading_label)
        
        self.worker_data = DataWorker(self.auth_manager, self.nextcloud_dir, self.config_factory)
        self.worker_data.data_ready.connect(self._almacenar_y_renderizar)
        self.worker_data.finished.connect(self.worker_data.deleteLater)
        self.worker_data.start()

    def _almacenar_y_renderizar(self, tasks: list, local_projects_map: dict, kitsu_projects_map: dict):
        if hasattr(self, 'loading_label'):
            self.loading_label.hide()
            self.loading_label.deleteLater()
            
        self.all_tasks = tasks
        self.local_projects_map = local_projects_map
        self.active_kitsu_projects = kitsu_projects_map
        
        project_counts = {}
        for t in self.all_tasks:
            p_name = t.get("project_name", "Unknown Project")
            project_counts[p_name] = project_counts.get(p_name, 0) + 1
            
        self.projects_discovered.emit(project_counts)

        active_projects = {t.get("project_name", "Unknown Project") for t in tasks}
        if self.current_filter != "All" and self.current_filter not in active_projects:
            self.current_filter = "All"
            self.header_label.setText(self.tr("All Your Tasks"))

        self._render_tasks()

    def _render_tasks(self):
        self._clear_layout(self.cards_layout)

        if not self.all_tasks:
            msg = QLabel(self.tr("You have no pending tasks (TODO/WIP). Great job!"))
            msg.setStyleSheet("color: #10B981; font-size: 14px;")
            msg.setAlignment(Qt.AlignCenter)
            self.cards_layout.addWidget(msg)
            return

        filtered_tasks = [t for t in self.all_tasks if self.current_filter == "All" or t.get("project_name") == self.current_filter]

        resolver = PathResolver()
        user_role = self.auth_manager.get_user_role()
        is_admin = user_role in ["lead", "supervisor", "td", "manager"]
        prod_folder = self.config_factory.get_production_folder_name()

        for task in filtered_tasks:
            proyecto_nombre = task["project_name"].lower()
            project_root = self.local_projects_map.get(proyecto_nombre)
            
            if proyecto_nombre in self.active_kitsu_projects:
                task["project_id"] = self.active_kitsu_projects[proyecto_nombre]
            
            esta_instalado = False
            can_work = True
            blocked_reason = ""

            if project_root:
                esta_instalado = self.installer.verificar_instalacion(project_root)
                if esta_instalado:
                    try:
                        relative_target = resolver.resolve(task)
                        if relative_target:
                            target_file = project_root / prod_folder / "pro" / relative_target
                            if not target_file.exists() and not is_admin:
                                can_work = False
                                blocked_reason = self.tr("File missing (Setup Required)")
                    except Exception as e:
                        print(f"[DEBUG _render_tasks] PathResolver Exception: {e}")
            else:
                can_work = False
                blocked_reason = self.tr("Project Desynced / Archived")
                
            tarjeta = TaskCard(
                parent=self.cards_widget,
                task_data=task,
                project_root=project_root,
                is_installed=esta_instalado,
                auth_manager=self.auth_manager,
                on_launch_callback=self.iniciar_proyecto_hilo,
                on_install_callback=self.ejecutar_instalacion_hilo,
                can_work=can_work,
                blocked_reason=blocked_reason
            )
            self.cards_layout.addWidget(tarjeta)

    def iniciar_proyecto_hilo(self, project_root: Path, config_path: Path, task_data: dict):
        if not self.vault.has_svn_credentials():
            self._emit_status(self.tr("Waiting for repository credentials..."), "yellow")
            self.modal_login = SVNLoginWindow(
                parent=self.window(),
                vault_manager=self.vault,
                on_success_callback=lambda: self.iniciar_proyecto_hilo(project_root, config_path, task_data)
            )
            self.modal_login.show()
            return

        user_role = self.auth_manager.get_user_role()
        prod_folder = self.config_factory.get_production_folder_name()
        target_file = None
        
        try:
            resolver = PathResolver()
            relative_target = resolver.resolve(task_data)
            
            if relative_target:
                target_file = project_root / prod_folder / "pro" / relative_target
                
                if user_role not in ["lead", "supervisor", "td", "manager"]:
                    if not target_file.exists():
                        self._emit_status(self.tr("❌ File not found. Please request Lead to create the shot."), "red")
                        return
        except Exception as e:
            self._emit_status(self.tr("Internal error resolving path: {0}").format(str(e)), "red")
            return

        svn_user, svn_pwd = self.vault.get_svn_credentials()
        kitsu_user, kitsu_pwd = self.vault.get_kitsu_credentials()
        kitsu_host = self.auth_manager.kitsu_host

        app_root = self.window()
        if hasattr(app_root, "registrar_instancia"):
            app_root.registrar_instancia(activa=True)

        self.worker_launch = LaunchWorker(
            project_root, config_path, svn_user, svn_pwd, kitsu_user, kitsu_pwd, kitsu_host, 
            user_role, task_data, target_file, prod_folder, self.config_factory, self.auth_manager
        )
        self.worker_launch.status_update.connect(self._emit_status)
        
        def on_launch_finished():
            if hasattr(app_root, "registrar_instancia"):
                app_root.registrar_instancia(activa=False)
            self.worker_launch.deleteLater()
            
        self.worker_launch.process_finished.connect(on_launch_finished)
        self.worker_launch.start()

    def ejecutar_instalacion_hilo(self, project_root: Path, task_data: dict):
        if not self.vault.has_svn_credentials():
            self._emit_status(self.tr("Waiting for repository credentials..."), "yellow")
            self.modal_login_install = SVNLoginWindow(
                parent=self.window(),
                vault_manager=self.vault,
                on_success_callback=lambda: self.ejecutar_instalacion_hilo(project_root, task_data)
            )
            self.modal_login_install.show()
            return
            
        user_role = self.auth_manager.get_user_role()
        svn_user, svn_pwd = self.vault.get_svn_credentials()
        
        task_metadata = None
        if user_role == "vendor":
            task_id = task_data.get("task_id")
            if task_id:
                task_metadata = self.auth_manager.get_task_metadata(task_id)
        
        self.worker_install = InstallWorker(
            self.installer, project_root, svn_user, svn_pwd, user_role, task_metadata
        )
        self.worker_install.status_update.connect(self._emit_status)
        
        def on_install_finished(exito):
            if exito:
                QTimer.singleShot(500, self.cargar_proyectos)
            else:
                self.vault.clear()
            self.worker_install.deleteLater()
            
        self.worker_install.finished_install.connect(on_install_finished)
        self.worker_install.start()
