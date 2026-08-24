# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/components/project_card.py
# Rol Arquitectónico: UI Component / Role-Aware Project Card
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.9.0 (Controller Injection & Code Purge)
# =========================================================================================

"""
Componente visual reutilizable para las Tarjetas de Proyectos.
Actúa estrictamente como la capa de Presentación (View). Delega todas las operaciones
de red (HTTP/Gazu) al KitsuManager y las operaciones de disco (Shutil/JSON) al NasManager,
respetando el patrón MVC y el Principio de Responsabilidad Única.
"""

import subprocess
import json
#import urllib.parse
from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QWidget, QToolButton, QMenu,
                               QDialog, QLineEdit, QMessageBox, QApplication,
                               QStackedWidget, QSizePolicy)
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QPixmap, QImage, QCursor, QAction, QDesktopServices, QColor, QIcon

from src.infrastructure.kitsu_manager import KitsuManager
from src.infrastructure.nas_manager import NasManager
from src.application.local_installer import LocalInstaller
from src.infrastructure.dev_defaults import DEV_SVN_USER, DEV_SVN_PASSWORD

class ProjectThumbnailWorker(QThread):
    """QThread dedicado a la descarga HTTP asíncrona de los avatares de proyectos."""
    image_downloaded = Signal(bytes)
    error_occurred = Signal(str)

    def __init__(self, kitsu_manager: KitsuManager, project_id: str, token: str, host_url: str):
        super().__init__()
        self.kitsu_mgr = kitsu_manager
        self.project_id = project_id
        self.token = token
        self.host_url = host_url

    def run(self):
        img_bytes = self.kitsu_mgr.download_project_thumbnail(self.project_id, self.token, self.host_url)
        if img_bytes: self.image_downloaded.emit(img_bytes)
        else: self.error_occurred.emit("Sin miniatura")

class ProjectInstallWorker(QThread):
    progress_update = Signal(str, str)
    finished_install = Signal(bool, str)

    def __init__(self, installer, project_root, vcs_user, vcs_pwd, user_role):
        super().__init__()
        self.installer = installer
        self.project_root = project_root
        self.vcs_user = vcs_user
        self.vcs_pwd = vcs_pwd
        self.user_role = user_role

    def run(self):
        success, msg = self.installer.instalar_entorno(
            project_root=self.project_root,
            vcs_user=self.vcs_user,
            vcs_pwd=self.vcs_pwd,
            status_callback=self._emit_status,
            user_role=self.user_role
        )
        self.finished_install.emit(success, msg)

    def _emit_status(self, mensaje, color):
        self.progress_update.emit(mensaje, color)

class DeleteProjectDialog(QDialog):
    """Modal de Seguridad (Type-to-Delete) estilo GitHub."""
    def __init__(self, parent, project_name: str):
        super().__init__(parent)
        self.project_name = project_name
        self.setWindowTitle(self.tr("⚠️ Warning: Project Destruction"))
        self.setFixedSize(450, 220)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        lbl_warn = QLabel(self.tr("You are about to permanently delete the project:\n<b>{0}</b>\n\nThis action will destroy Kitsu data, the SVN repository, and local files.").format(self.project_name))
        lbl_warn.setWordWrap(True)
        lbl_warn.setStyleSheet("color: #EF4444; font-size: 13px;")
        layout.addWidget(lbl_warn)

        lbl_instruct = QLabel(self.tr("To confirm, type <b>{0}</b> below:").format(self.project_name))
        lbl_instruct.setStyleSheet("color: #94A3B8;")
        layout.addWidget(lbl_instruct)

        self.entry_confirm = QLineEdit()
        self.entry_confirm.setObjectName("FormInput")
        self.entry_confirm.setFixedHeight(35)
        self.entry_confirm.textChanged.connect(self._validar_input)
        layout.addWidget(self.entry_confirm)

        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton(self.tr("Cancel"))
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.setFixedHeight(35)
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_delete = QPushButton(self.tr("Permanently Delete"))
        self.btn_delete.setStyleSheet("background-color: #EF4444; color: white; font-weight: bold; border-radius: 6px;")
        self.btn_delete.setFixedHeight(35)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_delete)
        layout.addLayout(btn_layout)

    def _validar_input(self, text: str):
        self.btn_delete.setEnabled(text == self.project_name)

class ProjectCard(QFrame):
    def __init__(self, parent: QWidget, project_data: dict, auth_manager, nas_dir: Path, 
                 config_factory=None, vault_manager=None, on_rebuild_callback: Callable = None, 
                 on_open_wizard_callback: Callable = None, status_callback: Callable = None):
        super().__init__(parent)
        
        self.project_data = project_data
        self.auth = auth_manager
        self.config_factory = config_factory
        self.vault = vault_manager
        self.on_rebuild_callback = on_rebuild_callback
        self.on_open_wizard_callback = on_open_wizard_callback
        self.status_callback = status_callback
        
        # Instanciar Controladores
        self.kitsu_mgr = KitsuManager()
        self.nas_mgr = NasManager(nas_dir)
        
        self.project_dir = None
        self.user_role = self.auth.get_user_role() if hasattr(self.auth, 'get_user_role') else "user"
        
        self.setObjectName("FloatingCard")
        #self.setFixedWidth(320)
        # Tarjeta más alta para acomodar el botón en roles No-Admin
        #card_height = 280 if self.user_role == "td" else 330
        self.setFixedSize(320, 330)
        
        self.setStyleSheet("""
            QFrame#FloatingCard { background-color: #1E293B; border-radius: 12px; border: 1px solid #334155; }
            QFrame#FloatingCard:hover { border: 1px solid #3B82F6; }
        """)

        self._build_ui()
        self._check_nas_status()
        self._cargar_miniatura()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        # ---------------------------------------------------------
        # Fila 1: Cabecera (Estado del proyecto y Menú de Contexto)
        # ---------------------------------------------------------
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        lbl_status = QLabel(self.project_data.get("project_status_name", self.tr("Active Project")))
        lbl_status.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: bold;")
        header_layout.addWidget(lbl_status)
        
        header_layout.addStretch()
        
        # Menú de Contexto (Los 3 puntitos)
        self.btn_options = QToolButton()
        self.btn_options.setText("⋮")
        self.btn_options.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_options.setStyleSheet("""
            QToolButton { background: transparent; color: #94A3B8; font-size: 20px; font-weight: bold; border: none; padding-bottom: 5px; } 
            QToolButton:hover { color: #F8FAFC; } 
            QToolButton::menu-indicator { image: none; }
        """)
        self.btn_options.setPopupMode(QToolButton.InstantPopup)
        
        self.options_menu = QMenu(self)
        # Inyectamos estilos para el menú y un pseudo-clase para el botón rojo
        self.options_menu.setStyleSheet("""
            QMenu { background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155; border-radius: 6px; } 
            QMenu::item { padding: 8px 25px; } 
            QMenu::item:selected { background-color: #3B82F6; }
        """)
        
        # Acción Esporádica de Configuración
        action_config = QAction(self.tr("⚙️ Configure Project"), self)
        action_config.triggered.connect(lambda: self._abrir_kitsu_interno("/production-settings"))
        self.options_menu.addAction(action_config)
        
        # Acciones Peligrosas / Administrativas
        if self.user_role == "td":
            self.options_menu.addSeparator()
            action_archive = QAction(self.tr("📦 Archive Project"), self)
            self.options_menu.addAction(action_archive)
            self.options_menu.addSeparator()
            
            # Pseudo-truco en PySide6: Usar HTML en el texto de QAction suele ser ignorado en macOS/Windows, 
            # pero funciona en el estilo Fusion de Linux. Para asegurar el rojo, creamos un icono rojo dinámico.
            red_pixmap = QPixmap(12, 12)
            red_pixmap.fill(QColor("#EF4444"))
            action_delete = QAction(QIcon(red_pixmap), self.tr("Delete Project"), self)
            action_delete.triggered.connect(self._on_delete_requested)
            self.options_menu.addAction(action_delete)

        self.btn_options.setMenu(self.options_menu)
        header_layout.addWidget(self.btn_options)
        main_layout.addLayout(header_layout)

        # ---------------------------------------------------------
        # Fila 2: Miniatura del Proyecto (QStackedWidget)
        # ---------------------------------------------------------
        # ... (Mantén aquí el mismo código de self.thumb_stack y sus páginas que tenías) ...
        self.thumb_stack = QStackedWidget()
        self.thumb_stack.setFixedHeight(130)
        self.thumb_stack.setStyleSheet("QStackedWidget { background-color: #0F172A; border-radius: 8px; border: 1px solid #1E293B; }")
        
        self.page_placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.page_placeholder)
        placeholder_layout.setAlignment(Qt.AlignCenter)
        self.lbl_placeholder_text = QLabel(self.tr("AWESOME PROJECT"))
        self.lbl_placeholder_text.setStyleSheet("color: #64748B; font-size: 10px; font-weight: bold;")
        placeholder_layout.addWidget(self.lbl_placeholder_text)
        
        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("border-radius: 8px; background-color: transparent;")
        
        self.thumb_stack.addWidget(self.page_placeholder)
        self.thumb_stack.addWidget(self.thumb_label)
        main_layout.addWidget(self.thumb_stack)

        # ---------------------------------------------------------
        # Fila 3 y 4: Títulos y Sincronización
        # ---------------------------------------------------------
        title_layout = QHBoxLayout()
        self.project_name = self.project_data.get("name", self.tr("Unknown Project"))
        self.lbl_title = QLabel(self.project_name)
        self.lbl_title.setStyleSheet("color: #F8FAFC; font-size: 15px; font-weight: bold;")
        title_layout.addWidget(self.lbl_title)
        title_layout.addStretch()
        
        self.lbl_badge = QLabel(self.tr("Checking..."))
        self.lbl_badge.setAlignment(Qt.AlignCenter)
        self.lbl_badge.setStyleSheet("background-color: #0F172A; color: #94A3B8; border: 1px solid #334155; border-radius: 6px; padding: 2px 8px; font-size: 10px; font-weight: bold;")
        title_layout.addWidget(self.lbl_badge)
        main_layout.addLayout(title_layout)

        self.lbl_sync_status = QLabel(self.tr("🗄️ Checking..."))
        self.lbl_sync_status.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: bold;")
        main_layout.addWidget(self.lbl_sync_status)

        # ---------------------------------------------------------
        # Fila 5: Matriz Dinámica de Botones (CTA) por Rol
        # ---------------------------------------------------------
        self.actions_layout = QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 5, 0, 0)
        self.actions_layout.setSpacing(10)
        main_layout.addLayout(self.actions_layout)

        # A) Construir el Split Button de Kitsu (Dropdown)
        self.btn_kitsu_dropdown = QToolButton()
        self.btn_kitsu_dropdown.setPopupMode(QToolButton.InstantPopup)
        self.btn_kitsu_dropdown.setCursor(Qt.PointingHandCursor)
        self.btn_kitsu_dropdown.setFixedHeight(35)
        
        kitsu_menu = QMenu(self)
        kitsu_menu.setStyleSheet("QMenu { background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155; border-radius: 6px; } QMenu::item { padding: 8px 25px; } QMenu::item:selected { background-color: #3B82F6; }")
        
        # Deeplinks Divulgación Progresiva
        kitsu_menu.addAction("To: Assets", lambda: self._abrir_kitsu_interno("/assets"))
        kitsu_menu.addAction("To: Shots", lambda: self._abrir_kitsu_interno("/shots"))
        kitsu_menu.addAction("To: Sequences", lambda: self._abrir_kitsu_interno("/sequences"))
        kitsu_menu.addAction("To: Edit", lambda: self._abrir_kitsu_interno("/edits"))
        self.btn_kitsu_dropdown.setMenu(kitsu_menu)

        # B) Construir el Ghost Button de Watchtower
        self.btn_watchtower = QPushButton("")
        self.btn_watchtower.setText("")
        self.btn_watchtower.setFixedSize(35, 35)
        self.btn_watchtower.setCursor(Qt.PointingHandCursor)
        self.btn_watchtower.setToolTip(self.tr("Open Watchtower Dashboard"))
        # Cargar SVG si existe, fallback a emoji
        wt_icon_path = Path("assets/icons/radar.svg")
        if wt_icon_path.exists() and wt_icon_path.is_file():
            # Pintamos el SVG de un gris acorde a los bordes
            try:
                with open(wt_icon_path, 'r', encoding='utf-8') as f:
                    svg_content = f.read()
                svg_content = svg_content.replace('currentColor', '#94A3B8')
                svg_content = svg_content.replace('stroke-width="2"', 'stroke-width="2.5"')
                pixmap = QPixmap()
                pixmap.loadFromData(svg_content.encode('utf-8'), "SVG")
                self.btn_watchtower.setIcon(QIcon(pixmap))
                self.btn_watchtower.setIconSize(QSize(20, 20))
            except Exception:
                self.btn_watchtower.setText("")
        else:
            self.btn_watchtower.setText("")
        self.btn_watchtower.clicked.connect(self._on_watchtower_clicked)

        # C) Construir el CTA Primario del Hub (Wizard / Launch)
        self.btn_primary_action = QPushButton()
        self.btn_primary_action.setFixedHeight(35)
        self.btn_primary_action.setCursor(Qt.PointingHandCursor)

        # MATRIZ DE RENDERIZADO POR ROL
        if self.user_role == "td":
            # TD Layout: Kitsu Dropdown (Orange) + Watchtower
            self.btn_kitsu_dropdown.setText("Open in Kitsu ▼")
            self.btn_kitsu_dropdown.setStyleSheet("""
                QToolButton { background-color: #F97316; color: white; font-weight: bold; border-radius: 6px; padding: 0 15px; }
                QToolButton:hover { background-color: #EA580C; }
                QToolButton::menu-indicator { image: none; }
            """)
            self.btn_kitsu_dropdown.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            
            self.btn_watchtower.setStyleSheet("""
                QPushButton { background: transparent; border: 1px solid #334155; border-radius: 6px; font-size: 16px;}
                QPushButton:hover { background-color: #334155; }
            """)
            
            self.actions_layout.addWidget(self.btn_kitsu_dropdown)
            self.actions_layout.addWidget(self.btn_watchtower)
            self.btn_primary_action.hide() # El TD no usa el botón estándar primario aquí
            
        else:
            # PM & Artist Layout: Primary Action (Orange/Blue) + Kitsu Ghost + Watchtower Ghost
            self.btn_kitsu_dropdown.setText("▼")
            # Cargar SVG para la claqueta de Kitsu (clapperboard.svg)
            kitsu_icon_path = Path("assets/icons/kitsu.svg")
            if kitsu_icon_path.exists() and kitsu_icon_path.is_file():
                try:
                    with open(kitsu_icon_path, 'r', encoding='utf-8') as f:
                        svg_content = f.read()
                    svg_content = svg_content.replace('currentColor', '#F97316')
                    svg_content = svg_content.replace('stroke-width="2"', 'stroke-width="2.5"')
                    pixmap = QPixmap()
                    pixmap.loadFromData(svg_content.encode('utf-8'), "SVG")
                    self.btn_kitsu_dropdown.setIcon(QIcon(pixmap))
                    self.btn_kitsu_dropdown.setIconSize(QSize(18, 18))
                except Exception:
                    self.btn_kitsu_dropdown.setText("🎬 ▼")
            else:
                self.btn_kitsu_dropdown.setText("🎬 ▼")
            self.btn_kitsu_dropdown.setStyleSheet("""
                QToolButton { background: transparent; color: #F97316; border: 1px solid #334155; border-radius: 6px; padding: 0 10px; font-weight: bold;}
                QToolButton:hover { background-color: rgba(249, 115, 22, 0.1); border-color: #F97316; }
                QToolButton::menu-indicator { image: none; }
            """)
            
            self.actions_layout.addWidget(self.btn_primary_action, stretch=1)
            self.actions_layout.addWidget(self.btn_kitsu_dropdown)
            
            if self.user_role == "manager":
                self.btn_watchtower.setStyleSheet("""
                    QPushButton { background: transparent; border: 1px solid #334155; border-radius: 6px; font-size: 16px;}
                    QPushButton:hover { background-color: #334155; }
                """)
                self.actions_layout.addWidget(self.btn_watchtower)
            else:
                self.btn_watchtower.hide() #

    def _abrir_kitsu_interno(self, sub_ruta: str):
        """Genera el deeplink absoluto y lo envía al WebContext nativo del Hub."""
        project_id = self.project_data.get("id")
        kitsu_url = self.config_factory.get_kitsu_api_url()
        
        if kitsu_url.endswith("/api"):
            kitsu_url = kitsu_url[:-4]
            
        full_url = f"{kitsu_url}/productions/{project_id}{sub_ruta}"
        
        main_win = self.window()
        if hasattr(main_win, 'abrir_kitsu'):
            main_win.abrir_kitsu(full_url)
        else:
            # Fallback seguro al navegador de OS
            QDesktopServices.openUrl(QUrl(full_url))
    
    def _abrir_ruta_kitsu(self, sub_ruta: str):
        """Enruta al usuario directamente a un módulo específico del proyecto en Kitsu."""
        project_id = self.project_data.get("id")
        host = getattr(self.auth, 'kitsu_host', '')
        url = self.kitsu_mgr.build_web_url(host, project_id, sub_ruta)
        if url: QDesktopServices.openUrl(QUrl(url))

    def _on_watchtower_clicked(self):
        """Enruta la petición de Watchtower al Orquestador pasándole la ruta física."""
        if self.project_dir:
            main_win = self.window()
            if hasattr(main_win, 'abrir_watchtower'):
                project_id = self.project_data.get("id", "")
                main_win.abrir_watchtower(self.project_dir)
        else:
            QMessageBox.warning(self, "Watchtower", self.tr("The project must be mounted on your disk to visualize Watchtower."))

    def _check_nas_status(self):
        """Actualiza estado y colores del botón Primario (Wizard / Launch / Install)."""
        p_name = self.project_data.get("name", "")
        p_code = self.project_data.get("code", "")
        self.project_dir = self.nas_mgr.resolve_project_dir(p_name, p_code)
        
        is_installed = False
        if self.config_factory and self.project_dir:
            installer = LocalInstaller(self.config_factory.get_workspace_root(), self.config_factory)
            is_installed = installer.verificar_instalacion(self.project_dir)

        if is_installed and self.project_dir:
            self.lbl_sync_status.setText(self.tr("🗄️ 🟢 Ready on Disk"))
            self.lbl_sync_status.setStyleSheet("color: #10B981; font-size: 12px; font-weight: bold;")
            blueprint = self.nas_mgr.get_project_blueprint(self.project_dir)
            self.lbl_badge.setText(blueprint.get("blender_version", "Blender"))
            
            # Setup Action Button
            if hasattr(self, 'btn_primary_action') and self.user_role != "td":
                if self.user_role == "manager":
                    self.btn_primary_action.setText(self.tr("Pipeline Wizard"))
                    self.btn_primary_action.setStyleSheet("background-color: #F59E0B; color: #0F172A; font-weight: bold; border-radius: 6px; border: none;")
                    try: self.btn_primary_action.clicked.disconnect()
                    except RuntimeError: pass
                    
                    if self.on_open_wizard_callback:
                        self.btn_primary_action.clicked.connect(lambda: self.on_open_wizard_callback(self.project_name))
                else:
                    self.btn_primary_action.setText(self.tr("Launch Project"))
                    self.btn_primary_action.setStyleSheet("background-color: #3B82F6; color: white; font-weight: bold; border-radius: 6px; border: none;")
                    try: self.btn_primary_action.clicked.disconnect()
                    except RuntimeError: pass
                    
                    self.btn_primary_action.clicked.connect(lambda: self._lanzar_blender(self.project_dir))
        else:
            self.lbl_sync_status.setText(self.tr("🗄️ ⚪ Cloud Only"))
            self.lbl_sync_status.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: bold;")
            self.lbl_badge.setText(self.tr("Not Mounted"))
            
            # Setup Action Button
            if hasattr(self, 'btn_primary_action') and self.user_role != "td":
                self.btn_primary_action.setText(self.tr("Install Workspace ↓"))
                self.btn_primary_action.setStyleSheet("background-color: #10B981; color: #0F172A; font-weight: bold; border-radius: 6px; border: none;")
                try: self.btn_primary_action.clicked.disconnect()
                except RuntimeError: pass
                
                target_path = self.config_factory.get_workspace_root() / p_name.lower().replace(" ", "-")
                self.btn_primary_action.clicked.connect(lambda _, p=target_path, b=self.btn_primary_action: self._instalar_entorno(p, b))
    

    def _instalar_entorno(self, project_path: Path, boton: QPushButton):
        boton.setEnabled(False)
        boton.setText(self.tr("Installing..."))
        boton.setStyleSheet("background-color: #94A3B8; color: #0F172A; font-weight: bold; border-radius: 6px; border: none;")
        
        installer = LocalInstaller(self.config_factory.get_workspace_root(), self.config_factory)
        
        # Recuperamos credenciales SVN (vía VaultManager)
        vcs_user, vcs_pwd = "", ""
        if self.vault:
            vcs_config = self.config_factory.get_raw_config().get("vcs_engine", {})
            vcs_user = vcs_config.get("vcs_username", DEV_SVN_USER)
            vcs_pwd = vcs_config.get("vcs_password", DEV_SVN_PASSWORD)

        self.install_worker = ProjectInstallWorker(installer, project_path, vcs_user, vcs_pwd, self.user_role)
        if self.status_callback:
            self.install_worker.progress_update.connect(self.status_callback)
        self.install_worker.finished_install.connect(self._on_install_finished)
        self.install_worker.start()

    def _on_install_finished(self, success: bool, msg: str):
        if success:
            if self.status_callback: self.status_callback(self.tr("✓ Workspace deployed"), "green")
            self._check_nas_status() # Refrescar botones
            if self.on_rebuild_callback: self.on_rebuild_callback()
        else:
            if self.status_callback: self.status_callback(self.tr("✗ Install Failed: {0}").format(msg), "red")
            QMessageBox.critical(self, self.tr("Deployment Error"), msg)
            if hasattr(self, 'btn_action'):
                self.btn_action.setEnabled(True)
                self.btn_action.setText(self.tr("Retry Install ↓"))

    def _lanzar_blender(self, project_path: Path):
        config_path = project_path / "local" / "project_config.json"
        if not config_path.exists():
            if self.status_callback: self.status_callback(self.tr("Error: config missing."), "red")
            return
            
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                local_config = json.load(f)
            blender_version = local_config.get("blender_version", "")
            
            installer = LocalInstaller(self.config_factory.get_workspace_root(), self.config_factory)
            os_name, _ = installer._get_os_info()
            blender_folder = installer.boveda_blender / f"blender-{blender_version}-{os_name}-x64"
            
            if os_name == "windows": blender_bin = blender_folder / "blender.exe"
            elif os_name == "macos": blender_bin = blender_folder / "Blender.app" / "Contents" / "MacOS" / "Blender"
            else: blender_bin = blender_folder / "blender"

            if not blender_bin.exists():
                if self.status_callback: self.status_callback(self.tr("Blender not found."), "red")
                return

            if self.status_callback: self.status_callback(self.tr("🚀 Launching Blender..."), "green")
            subprocess.Popen([str(blender_bin), "--", "--project_root", str(project_path)])
            
            main_window = self.window()
            if hasattr(main_window, 'registrar_instancia'):
                main_window.registrar_instancia(True)

        except Exception as e:
            if self.status_callback: self.status_callback(self.tr("Failed to launch: {0}").format(str(e)), "red")

    def _on_rebuild_clicked(self):
        # En lugar de solo recargar, forzamos la instalación de infraestructura base (Sandbox)
        p_name = self.project_data.get("name", "")
        target_path = self.config_factory.get_workspace_root() / p_name.lower().replace(" ", "-")
        
        self.btn_rebuild.setEnabled(False)
        self.btn_rebuild.setText(self.tr("Rebuilding..."))
        self._instalar_entorno(target_path, self.btn_rebuild)

    def _on_delete_requested(self):
        dialog = DeleteProjectDialog(self, self.project_name)
        if dialog.exec() == QDialog.Accepted:
            self._ejecutar_destruccion_nuclear(self.project_name)

    def _ejecutar_destruccion_nuclear(self, project_name: str):
        """Coordina la eliminación a través de los controladores y notifica al usuario."""
        project_id = self.project_data.get("id")
        folder_name = project_name.lower().replace(" ", "-")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        try:
            # 1. Kitsu DB
            success, msg = self.kitsu_mgr.delete_project(project_id)
            if not success: QMessageBox.warning(self, self.tr("Warning"), msg)
            try: subprocess.run(["docker", "exec", "openstudio_local_svn", "rm", "-rf", f"/home/svn/{folder_name}"], check=False)
            except Exception: pass
            if self.project_dir: self.nas_mgr.delete_project_folder(self.project_dir)
            
            QMessageBox.information(self, self.tr("Deleted"), self.tr("Project destroyed."))
            if self.on_rebuild_callback: self.on_rebuild_callback()

        finally:
            QApplication.restoreOverrideCursor()

    def _cargar_miniatura(self):
        project_id = self.project_data.get("id")
        token = getattr(self.auth, 'get_current_token', lambda: "")()
        base_url = getattr(self.auth, 'kitsu_host', "")
        
        self.worker = ProjectThumbnailWorker(self.kitsu_mgr, project_id, token, base_url)
        self.worker.image_downloaded.connect(self._on_thumbnail_ready)
        self.worker.error_occurred.connect(self._on_thumbnail_error)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _on_thumbnail_ready(self, img_bytes: bytes):
        image = QImage.fromData(img_bytes)
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            pixmap = pixmap.scaled(290, 140, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x_offset = (pixmap.width() - 290) // 2
            y_offset = (pixmap.height() - 140) // 2
            self.thumb_label.setPixmap(pixmap.copy(x_offset, y_offset, 290, 140))
            
            # Cambiar a la Página 1 (Mostrar imagen)
            self.thumb_stack.setCurrentIndex(1)
        else:
            self._on_thumbnail_error(self.tr("Archivo corrupto"))

    def _on_thumbnail_error(self, message: str):
        # Ante cualquier error o falta de imagen, forzamos la Página 0 (Placeholder visual)
        self.thumb_stack.setCurrentIndex(0)
