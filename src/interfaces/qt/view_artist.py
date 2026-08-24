
# OPENSTUDIOHUB
# Módulo: ui/view_artist.py
# Rol Arquitectónico: UI View / Artist Dashboard (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.4.3 (Strict NAS Path Validation)
# =========================================================================================

"""
Main dashboard for Studio Artists.
Inherits from BaseDashboardView to enforce DRY principles and corporate UI guidelines.
Fetches assigned tasks from Kitsu (Gazu API) and renders them in a responsive grid.
Validates VFS semantic topography with strict physical path checks to prevent I/O crashes.
"""

from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel,
                               QScrollArea, QStackedWidget, QFrame, QPushButton,
                               QHBoxLayout, QComboBox) # <-- Añadidos QHBoxLayout y QComboBox
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QResizeEvent

from src.application.auth_manager import AuthManager
from src.application.vault_manager import VaultManager
from src.infrastructure.config_factory import ConfigFactory

from src.interfaces.qt.base_dashboard import BaseDashboardView
from src.application.local_installer import LocalInstaller
from src.infrastructure.dev_defaults import DEV_SVN_USER, DEV_SVN_PASSWORD

# Intenta importar el componente nativo de Tarjeta de Tarea, si existe.
try:
    from src.interfaces.qt.components.task_card import TaskCard
except ImportError:
    TaskCard = None


class FetchArtistTasksWorker(QThread):
    """Hilo secundario asíncrono para consultar las tareas asignadas al usuario en Kitsu."""
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, auth_manager=None):
        super().__init__()
        self.auth = auth_manager

    def run(self):
        try:
            user = self.auth.kitsu.get_current_user()
            all_tasks = self.auth.kitsu.all_tasks_for_person(user)

            status_targets = ["Todo", "Work In Progress", "Waiting For Approval", "Retake", "Ready To Start"]
            tasks = [
                t for t in all_tasks
                if (t.get("task_status_name") in status_targets or
                    t.get("task_status", {}).get("name") in status_targets)
            ]

            # --- NUEVO: ENRIQUECIMIENTO DEL TASK DATA ---
            for t in tasks:
                entity_type = t.get("entity_type_name", t.get("entity_type", "")).lower()

                # Si la tarea pertenece a un Asset, Kitsu no nos da la subcategoría nativamente,
                # así que debemos consultarla y empaquetarla nosotros.
                if entity_type == "asset":
                    try:
                        # 1. Consultar el Asset real usando el entity_id
                        asset_completo = self.auth.kitsu.get_asset(t["entity_id"])
                        if asset_completo:
                            # En Kitsu, el ID del 'Asset Type' se guarda como 'entity_type_id' dentro del Asset
                            t["asset_type_id"] = asset_completo.get("entity_type_id", "")

                            # 2. Opcional pero vital para tu PathResolver: Traer también el nombre del tipo
                            asset_type = self.auth.kitsu.get_asset_type(t["asset_type_id"])
                            if asset_type:
                                t["asset_type_name"] = asset_type.get("name", "")
                    except Exception as inner_e:
                        print(f"[Worker] Advertencia: Fallo al enriquecer Asset: {inner_e}")
            # --------------------------------------------

            self.data_ready.emit(tasks)
        except Exception as e:
            self.error_occurred.emit(str(e))


class InstallProjectWorker(QThread):
    """Hilo secundario asíncrono para ejecutar el motor de instalación local sin congelar la UI."""
    progress_updated = Signal(str, str)
    finished_install = Signal(bool, str)

    def __init__(self, project_root: Path, auth_manager: AuthManager, config_factory: ConfigFactory, task_data: dict):
        super().__init__()
        self.project_root = project_root
        self.auth = auth_manager
        self.config_factory = config_factory
        self.task_data = task_data

    def run(self):
        try:
            installer = LocalInstaller(self.project_root.parent, self.config_factory)

            vcs_user = self.auth.user_data.get("email", "artist") if self.auth.user_data else "artist"
            vcs_pwd = self.auth.get_current_token()

            total_steps = 7
            current_step = 0

            def interceptor_progreso(mensaje: str, color: str):
                nonlocal current_step
                trigger_words = ["Reading structural", "Synchronizing", "Extracting", "Injecting", "Deploying", "Configuring", "Generating"]
                if any(word in mensaje for word in trigger_words):
                    current_step += 1

                pct = int((current_step / total_steps) * 100)
                if pct > 100: pct = 100
                self.progress_updated.emit(f"⏳ {pct}% - {mensaje}", "yellow")

            success, msg = installer.instalar_entorno(
                project_root=self.project_root,
                vcs_user=vcs_user,
                vcs_pwd=vcs_pwd,
                status_callback=interceptor_progreso,
                user_role="artist",
                task_metadata=self.task_data
            )

            self.finished_install.emit(success, msg)
        except Exception as e:
            self.finished_install.emit(False, str(e))

class LaunchTaskWorker(QThread):
    """Hilo secundario para ejecutar Blender sin congelar la interfaz gráfica."""
    finished_launch = Signal(bool, str)

    def __init__(self, kwargs_dict):
        super().__init__()
        self.kwargs = kwargs_dict

    def run(self):
        try:
            from src.infrastructure.env_launcher import lanzar_blender
            lanzar_blender(**self.kwargs)
            self.finished_launch.emit(True, "Sesión de DCC finalizada y Lock liberado.")
        except Exception as e:
            self.finished_launch.emit(False, f"Error lanzando DCC: {str(e)}")

class ViewArtist(BaseDashboardView):
    def __init__(self, parent: QWidget, auth_manager: AuthManager, nas_dir: Path,
                 vault_manager: VaultManager, config_factory: ConfigFactory, on_logout: Callable[[], None], **kwargs):

        super().__init__(parent, auth_manager, config_factory, on_logout, **kwargs)

        self.nas_dir = nas_dir
        self.vault = vault_manager

        self._task_widgets = []
        self._all_fetched_tasks = []
        self._current_cols = 0
        self._install_worker = None

        self.setObjectName("ViewArtistBase")

        self.add_sidebar_button("mis_tareas", self.tr("My Tasks"), "📋", "list.svg", lambda: self._cambiar_panel("mis_tareas"), activo=True)
        #self.add_sidebar_button("watchtower", self.tr("Watchtower"), "🗼", "radar.svg", lambda: self._cambiar_panel("watchtower"))

        self._build_artist_content()
        self.cargar_tareas()

    def _build_artist_content(self):
        self.stacked_content = QStackedWidget()

        self.panel_tareas = QFrame()
        layout_tareas = QVBoxLayout(self.panel_tareas)
        layout_tareas.setContentsMargins(0, 0, 0, 0)
        layout_tareas.setSpacing(20)

        # =======================================================
        # NUEVO: Header con Título y Selector de Proyecto
        # =======================================================
        header_layout = QHBoxLayout()

        lbl_title = QLabel(self.tr("My Assigned Tasks"))
        lbl_title.setObjectName("PageTitle")

        self.combo_projects = QComboBox()
        self.combo_projects.setObjectName("StandardComboBox")
        self.combo_projects.setFixedSize(250, 35)
        # Conectamos el cambio del combo a la función de filtrado
        self.combo_projects.currentIndexChanged.connect(self._aplicar_filtro_proyecto)

        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(QLabel(self.tr("Project:")))
        header_layout.addWidget(self.combo_projects)

        layout_tareas.addLayout(header_layout)
        # =======================================================

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("InvisibleScrollArea")

        self.grid_widget = QWidget()
        self.grid_widget.setObjectName("TransparentGridContainer")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.scroll_area.setWidget(self.grid_widget)
        layout_tareas.addWidget(self.scroll_area, stretch=1)

        self.stacked_content.addWidget(self.panel_tareas)

        # placeholder_wt = QLabel(self.tr("🚧 Watchtower module under construction..."))
        # placeholder_wt.setAlignment(Qt.AlignCenter)
        # placeholder_wt.setObjectName("PlaceholderText")
        # self.stacked_content.addWidget(placeholder_wt)

        self.content_layout.addWidget(self.stacked_content, stretch=1)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._rearrange_grid()

    def _rearrange_grid(self):
        if not self._task_widgets: return

        viewport_width = self.scroll_area.viewport().width()
        card_width = 280
        spacing = self.grid_layout.spacing()

        cols = max(1, (viewport_width + spacing) // (card_width + spacing))

        if getattr(self, '_current_cols', 0) == cols: return

        self._current_cols = cols
        row, col = 0, 0

        for widget in self._task_widgets:
            self.grid_layout.removeWidget(widget)
            self.grid_layout.addWidget(widget, row, col)

            col += 1
            if col >= cols:
                col = 0
                row += 1

    def _cambiar_panel(self, panel_id: str):
        self.set_active_sidebar_button(panel_id)
        indices = {"mis_tareas": 0, "watchtower": 1}
        self.stacked_content.setCurrentIndex(indices.get(panel_id, 0))

    def cargar_tareas(self):
        self.actualizar_status(self.tr("Fetching your assigned tasks from Kitsu..."), "yellow")

        self.combo_projects.clear()
        self._all_fetched_tasks = []

        for widget in self._task_widgets:
            widget.hide()
            widget.deleteLater()
        self._task_widgets.clear()

        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.worker = FetchArtistTasksWorker(self.auth)
        self.worker.data_ready.connect(self._procesar_nuevas_tareas)
        self.worker.error_occurred.connect(lambda e: self.actualizar_status(f"Network error: {e}", "red"))
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _procesar_nuevas_tareas(self, tasks: list):
        """Recibe las tareas de la API, extrae los proyectos y prepara la UI."""
        if not tasks:
            self.actualizar_status(self.tr("You have no pending tasks. Enjoy your coffee! ☕"), "white")
            return

        self.actualizar_status(self.tr("🟢 Synchronized: {0} active tasks found.").format(len(tasks)), "green")

        # 1. Guardar en memoria local
        self._all_fetched_tasks = tasks

        # 2. Extraer dinámicamente los proyectos que existen dentro de esas tareas
        self.combo_projects.blockSignals(True)
        self.combo_projects.clear()
        self.combo_projects.addItem(self.tr("All Projects"), "ALL")

        proyectos_unicos = {}
        for t in tasks:
            p_name = t.get('project_name') or (t.get('project') or {}).get('name', 'Unknown')
            p_id = t.get('project_id')
            if p_name and p_id and p_id not in proyectos_unicos:
                proyectos_unicos[p_id] = p_name

        # Insertar ordenados alfabéticamente
        for p_id, p_name in sorted(proyectos_unicos.items(), key=lambda item: item[1]):
            self.combo_projects.addItem(p_name, p_id)

        self.combo_projects.blockSignals(False)

        # 3. Disparar el primer renderizado (por defecto mostrará "All Projects")
        self._aplicar_filtro_proyecto()

    def _aplicar_filtro_proyecto(self, index=0):
        """Filtra la lista de tareas en caché y dibuja el Grid."""

        # 1. Limpiar Grid Actual
        for widget in self._task_widgets:
            widget.hide()
            widget.deleteLater()
        self._task_widgets.clear()

        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # 2. Obtener el ID del proyecto a filtrar
        selected_project_id = self.combo_projects.currentData()

        if selected_project_id == "ALL":
            filtered_tasks = self._all_fetched_tasks
        else:
            filtered_tasks = [t for t in self._all_fetched_tasks if t.get('project_id') == selected_project_id]

        vfs_pipeline = self.config_factory.get_vfs_pipeline_name()
        nas_root = self.config_factory.get_workspace_root()

        # 3. Renderizar Tarjetas
        for task_data in filtered_tasks:
            if TaskCard:
                # 1. Extracción directa respaldada por nuestro dump forense
                p_name = task_data.get('project_name') or (task_data.get('project') or {}).get('name', 'Unknown')

                # 2. Normalización de carpeta según la convención del ProjectBuilder
                folder_name = p_name.strip().lower().replace(" ", "-")
                temp_root = nas_root / folder_name

                # === PRINTS DE DEPURACIÓN ===
                print(f"\n[DEBUG] --- TAREA ENCONTRADA ---")
                print(f"[DEBUG] Nombre extraído (p_name): '{p_name}'")
                print(f"[DEBUG] Carpeta calculada: '{folder_name}'")
                print(f"[DEBUG] Buscando ruta física en: {temp_root}")
                print(f"[DEBUG] ¿Existe la carpeta?: {temp_root.exists()}")
                print(f"----------------------------\n")
                # ============================

                # Verificación de existencia física en el NAS
                if temp_root.exists():
                    project_root = temp_root
                else:
                    project_root = None

                is_installed = False
                can_work = True
                blocked_reason = ""

                if project_root:
                    try:
                        is_installed = LocalInstaller(project_root.parent, self.config_factory).verificar_instalacion(project_root)
                    except Exception:
                        is_installed = False

                    if not is_installed:
                        init_json_path = project_root / vfs_pipeline / "project_init.json"
                        if not init_json_path.exists():
                            can_work = False
                            blocked_reason = self.tr("Missing NAS Setup")
                else:
                    can_work = False
                    blocked_reason = self.tr("Folder Missing on NAS")

                # 2. INYECCIÓN DEL PATH RESOLVER EN EL CALLBACK DE LAUNCH
                # 2. DELEGACIÓN AL ORQUESTADOR DCC (Env Launcher)
                def launch_cb(p_root: Path, conf_path: Path, t_data: dict):
                    #from core.env_launcher import lanzar_blender

                    self.actualizar_status(self.tr("🚀 Delegando al Orquestador DCC..."), "yellow")

                    if not conf_path.exists():
                        self.actualizar_status(self.tr("Config file missing. Reinstall workspace."), "red")
                        return

                    # Extraer credenciales base (El env_launcher aplicará el bypass de admin en localhost)
                    #import os
                    vcs_user = DEV_SVN_USER
                    vcs_pwd = DEV_SVN_PASSWORD

                    kitsu_user = self.vault._transient_email
                    kitsu_pwd = self.vault._transient_password

                    if not kitsu_pwd:
                        # Fallback (si la bóveda está vacía, pedimos que re-inicie sesión)
                        self.actualizar_status("Kitsu Password lost in RAM. Please log out and log in again.", "red")
                        return

                    kitsu_host = self.config_factory.get_kitsu_api_url()

                    # Delegar todo el trabajo pesado, sandboxing y variables de entorno al motor central
                    # 1. BLOQUEAR EL CIERRE DEL HUB
                    main_window = self.window()
                    if hasattr(main_window, 'registrar_instancia'):
                        main_window.registrar_instancia(True)

                    # 2. PREPARAR ARGUMENTOS PARA EL WORKER
                    kwargs = {
                        "project_root": p_root,
                        "config_path": conf_path,
                        "svn_user": vcs_user,
                        "svn_pwd": vcs_pwd,
                        "kitsu_user": kitsu_user,
                        "kitsu_pwd": kitsu_pwd,
                        "kitsu_host": kitsu_host,
                        "user_role": "artist",
                        "task_data": t_data,
                        "target_file": None,
                        "status_callback": self.actualizar_status,
                        "config_factory": self.config_factory
                    }

                    # 3. LANZAR EN HILO SECUNDARIO
                    self.launch_worker = LaunchTaskWorker(kwargs)

                    def on_launch_finished(success, msg):
                        # 4. LIBERAR EL CIERRE DEL HUB
                        if hasattr(main_window, 'registrar_instancia'):
                            main_window.registrar_instancia(False)
                        self.actualizar_status(msg, "green" if success else "red")

                    self.launch_worker.finished_launch.connect(on_launch_finished)
                    self.launch_worker.start()

                def install_cb(p_root: Path, t_data: dict):
                    self.iniciar_instalacion_fisica(p_root, t_data)

                # =========================================================
                # INSERTA ESTO: Creación de la tarjeta y guardado en la lista
                # =========================================================
                tarjeta = TaskCard(
                    parent=self.grid_widget,
                    task_data=task_data,
                    project_root=project_root,
                    is_installed=is_installed,
                    auth_manager=self.auth,
                    config_factory=self.config_factory,
                    on_launch_callback=launch_cb,
                    on_install_callback=install_cb,
                    can_work=can_work,
                    blocked_reason=blocked_reason
                )
            else:
                # Fallback por si la importación de TaskCard falla
                tarjeta = QFrame()
                tarjeta.setFixedSize(280, 220)

            # ¡Añadimos la tarjeta a la cuadrícula!
            self._task_widgets.append(tarjeta)
            # =========================================================

        self._current_cols = 0
        self._rearrange_grid()

    def iniciar_instalacion_fisica(self, project_root: Path, task_data: dict):
        if not project_root:
            self.actualizar_status(self.tr("Cannot install: Project folder is missing on NAS."), "red")
            return

        if self._install_worker and self._install_worker.isRunning():
            self.actualizar_status(self.tr("Please wait, an installation is already running..."), "red")
            return

        self._install_worker = InstallProjectWorker(
            project_root=project_root,
            auth_manager=self.auth,
            config_factory=self.config_factory,
            task_data=task_data
        )

        self._install_worker.progress_updated.connect(self.actualizar_status)
        self._install_worker.finished_install.connect(self._on_install_finished)
        self._install_worker.start()

    def _on_install_finished(self, success: bool, message: str):
        if success:
            self.actualizar_status(self.tr("🟢 100% - {0}").format(message), "green")
            self.cargar_tareas()
        else:
            self.actualizar_status(self.tr("🔴 Install Error: {0}").format(message), "red")
