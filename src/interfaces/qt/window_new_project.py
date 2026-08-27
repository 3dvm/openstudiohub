# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/window_new_project.py
# Rol Arquitectónico: UI View / Modal Dialog (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.9.0 (Ephemeral VCS Auth UI Injection)
# =========================================================================================

"""
Asistente modal para la creación de nuevos proyectos (TD Wizard).
Implementa validaciones estrictas de plantillas y campos de autenticación 
VCS efímeros en la UI para sobreescribir el SSO sin persistencia en disco.
"""

from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QLineEdit, QComboBox, QCheckBox, QRadioButton, 
                               QButtonGroup, QPushButton, QScrollArea, QWidget, 
                               QFileDialog)
from PySide6.QtCore import Qt, QThread, Signal

from src.application.project_builder import ProjectBuilder
from src.application.vault_manager import VaultManager
from src.infrastructure.dev_defaults import DEV_SVN_USER, DEV_SVN_PASSWORD

class FetchKitsuTemplatesWorker(QThread):
    data_ready = Signal(list)

    def __init__(self, production_service):
        super().__init__()
        self.production_service = production_service

    def run(self):
        try:
            self.data_ready.emit(self.production_service.list_templates())
        except Exception as e:
            print(f"[FetchKitsuTemplatesWorker] Error de red: {e}")
            self.data_ready.emit([])

class ProjectCreationWorker(QThread):
    """Hilo trabajador para ejecutar la I/O pesada del ProjectBuilder sin congelar la modal."""
    result = Signal(bool, str)

    def __init__(self, builder: ProjectBuilder, nombre: str, version: str, 
                 dependencias: dict, template: str, splash: str, vcs_user: str, vcs_pwd: str):
        super().__init__()
        self.builder = builder
        self.nombre = nombre
        self.version = version
        self.dependencias = dependencias
        self.template = template
        self.splash = splash
        self.vcs_user = vcs_user
        self.vcs_pwd = vcs_pwd

    def run(self):
        exito, mensaje = self.builder.create_project(
            project_name=self.nombre, 
            blender_version=self.version, 
            dependencies=self.dependencias, 
            project_template=self.template, 
            splash_image_path=self.splash,
            vcs_user=self.vcs_user,
            vcs_pwd=self.vcs_pwd
        )
        self.result.emit(exito, mensaje)

class NewProjectWindow(QDialog):
    def __init__(self, parent: QWidget, config_factory, production_service, on_success_callback):
        super().__init__(parent)
        self.setWindowTitle(self.tr("New Project"))
        self.setFixedSize(500, 700) # Más compacta sin los campos de Auth
        self.setModal(True)
        self.ruta_splash = ""
        self.config_factory = config_factory
        self.production_service = production_service
        self.on_success = on_success_callback
        self.builder = ProjectBuilder(self.config_factory)
        self.vault_manager = VaultManager(self.config_factory)
        self.vault_data = self.vault_manager.cargar_inventario()
        self.checkboxes_herramientas = {}
        self.template_group = None
        self.setObjectName("ViewLoginBase")
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 30, 40, 30)
        main_layout.setSpacing(15)

        lbl_titulo = QLabel(self.tr("Initial Setup"))
        lbl_titulo.setObjectName("CardTitle")
        lbl_titulo.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(lbl_titulo)
        
        main_layout.addSpacing(10)

        self.entry_nombre = QLineEdit()
        self.entry_nombre.setObjectName("FormInput")
        self.entry_nombre.setPlaceholderText(self.tr("Name (e.g., p0004-new-project)"))
        self.entry_nombre.setFixedHeight(45)
        main_layout.addWidget(self.entry_nombre)

        # Dropdown de Plantilla Kitsu
        lbl_kitsu_template = QLabel(self.tr("Kitsu Template:"))
        lbl_kitsu_template.setStyleSheet("font-weight: bold; margin-top: 10px;")
        main_layout.addWidget(lbl_kitsu_template)
        
        self.combo_kitsu_template = QComboBox()
        self.combo_kitsu_template.setFixedHeight(40)
        self.combo_kitsu_template.setStyleSheet("QComboBox { background-color: #0F172A; border: 1px solid #475569; border-radius: 8px; color: #F8FAFC; padding: 5px; }")
        self.combo_kitsu_template.addItem(self.tr("Loading templates..."))
        self.combo_kitsu_template.setEnabled(False)
        main_layout.addWidget(self.combo_kitsu_template)
        
        self.worker_kitsu_templates = FetchKitsuTemplatesWorker(self.production_service)
        self.worker_kitsu_templates.data_ready.connect(self._on_kitsu_templates_loaded)
        self.worker_kitsu_templates.start()

        lbl_version = QLabel(self.tr("Target Blender Version:"))
        lbl_version.setStyleSheet("font-weight: bold; margin-top: 10px;")
        main_layout.addWidget(lbl_version)
        
        versiones = list(self.vault_data.keys()) if self.vault_data else []
        self.combo_version = QComboBox()
        self.combo_version.addItems(versiones)
        self.combo_version.setFixedHeight(40)
        self.combo_version.setStyleSheet("QComboBox { background-color: #0F172A; border: 1px solid #475569; border-radius: 8px; color: #F8FAFC; padding: 5px; }")
        self.combo_version.currentTextChanged.connect(self.dibujar_dependencias_dinamicas)
        main_layout.addWidget(self.combo_version)

        lbl_addons = QLabel(self.tr("Vault Components (vault_manifest.json):"))
        lbl_addons.setStyleSheet("font-weight: bold; margin-top: 15px;")
        main_layout.addWidget(lbl_addons)
        
        self.scroll_addons = QScrollArea()
        self.scroll_addons.setWidgetResizable(True)
        self.scroll_addons.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; background-color: #1E293B; }")
        
        self.addons_widget = QWidget()
        self.addons_widget.setStyleSheet("background: transparent;")
        self.addons_layout = QVBoxLayout(self.addons_widget)
        self.addons_layout.setAlignment(Qt.AlignTop)
        self.scroll_addons.setWidget(self.addons_widget)
        main_layout.addWidget(self.scroll_addons, stretch=1)

        if versiones:
            self.dibujar_dependencias_dinamicas(self.combo_version.currentText())

        lbl_splash = QLabel(self.tr("Custom Splash Screen (1000x500px):"))
        lbl_splash.setStyleSheet("font-weight: bold; margin-top: 10px;")
        main_layout.addWidget(lbl_splash)

        splash_layout = QHBoxLayout()
        splash_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_splash = QPushButton(self.tr("Browse PNG"))
        self.btn_splash.setObjectName("SecondaryButton")
        self.btn_splash.setFixedSize(120, 35)
        self.btn_splash.setCursor(Qt.PointingHandCursor)
        self.btn_splash.clicked.connect(self.seleccionar_splash)
        splash_layout.addWidget(self.btn_splash)

        self.lbl_splash_name = QLabel(self.tr("No image"))
        self.lbl_splash_name.setStyleSheet("color: #64748B; padding-left: 10px;")
        splash_layout.addWidget(self.lbl_splash_name, stretch=1)
        main_layout.addLayout(splash_layout)

        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.hide()
        main_layout.addWidget(self.lbl_status)

        self.btn_crear = QPushButton(self.tr("Generate Project"))
        self.btn_crear.setObjectName("PrimaryButton")
        self.btn_crear.setFixedHeight(50)
        self.btn_crear.setCursor(Qt.PointingHandCursor)
        self.btn_crear.clicked.connect(self.ejecutar_creacion)
        main_layout.addWidget(self.btn_crear)

        if not self.vault_data:
            self.lbl_status.setText(self.tr("⚠️ OPERATION BLOCKED: Vault not initialized."))
            self.lbl_status.setStyleSheet("color: #EF4444; font-weight: bold; padding: 12px; background-color: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 6px;")
            self.lbl_status.show()
            self.entry_nombre.setEnabled(False)
            self.combo_version.setEnabled(False)
            self.btn_splash.setEnabled(False)
            self.btn_crear.setEnabled(False)

    def _on_kitsu_templates_loaded(self, templates: list):
        self.combo_kitsu_template.clear()
        if not templates:
            self.combo_kitsu_template.addItem("standard-3d-production")
        else:
            for t in templates:
                self.combo_kitsu_template.addItem(t["name"])
        self.combo_kitsu_template.setEnabled(True)

    def seleccionar_splash(self):
        ruta, _ = QFileDialog.getOpenFileName(self, self.tr("Select Splash Screen"), "", self.tr("PNG Images (*.png)"))
        if ruta:
            self.ruta_splash = ruta
            self.lbl_splash_name.setText(Path(ruta).name)
            self.lbl_splash_name.setStyleSheet("color: #F8FAFC; padding-left: 10px;")

    def _clear_addons_layout(self):
        while self.addons_layout.count():
            child = self.addons_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()

    def dibujar_dependencias_dinamicas(self, version_seleccionada: str):
        self._clear_addons_layout()
        self.checkboxes_herramientas.clear()
        self.template_group = QButtonGroup(self)
        if not version_seleccionada: return

        categorias_disponibles = self.vault_data.get(version_seleccionada, {})
        if not categorias_disponibles: return

        for categoria, items in categorias_disponibles.items():
            lbl_cat = QLabel(f"[{categoria.upper()}]")
            lbl_cat.setStyleSheet("color: #10B981; font-weight: bold; margin-top: 10px;")
            self.addons_layout.addWidget(lbl_cat)
            self.checkboxes_herramientas[categoria] = {}

            for nombre_item, datos in items.items():
                version_item = datos.get("version", "1.0")
                es_obligatorio = datos.get("mandatory", False)
                texto_label = f"{nombre_item} v{version_item} - {datos.get('description', '')}"
                
                if categoria == "templates":
                    cb = QRadioButton(texto_label)
                    cb.setStyleSheet("QRadioButton { color: #F8FAFC; padding: 5px; }")
                    self.template_group.addButton(cb)
                else:
                    cb = QCheckBox(texto_label)
                    cb.setStyleSheet("QCheckBox { color: #F8FAFC; padding: 5px; }")
                
                cb.toggled.connect(lambda checked, c=categoria, n=nombre_item, r=datos.get("requires", []): self._resolver_subdependencias(checked, c, n, r))
                self.addons_layout.addWidget(cb)

                if es_obligatorio:
                    cb.setChecked(True)
                    cb.setEnabled(False)

                self.checkboxes_herramientas[categoria][nombre_item] = {'checkbox': cb, 'version': version_item}

    def _resolver_subdependencias(self, checked: bool, categoria_padre: str, nombre_padre: str, requires: list):
        for req in requires:
            partes = req.split("/")
            if len(partes) != 2: continue
            cat_req, nom_req = partes[0], partes[1]
            if cat_req in self.checkboxes_herramientas and nom_req in self.checkboxes_herramientas[cat_req]:
                cb_sub = self.checkboxes_herramientas[cat_req][nom_req]['checkbox']
                cb_sub.setChecked(checked)
                cb_sub.setEnabled(not checked)

    def ejecutar_creacion(self):
        nombre = self.entry_nombre.text().strip()
        version_blender = self.combo_version.currentText().strip()
        kitsu_template = self.combo_kitsu_template.currentText().strip()

        if not nombre or not nombre.replace("-", "").replace("_", "").isalnum():
            self.lbl_status.setText(self.tr("Invalid name."))
            self.lbl_status.show()
            return

        dependencias_finales, template_principal = {}, None
        for categoria, items in self.checkboxes_herramientas.items():
            dependencias_finales[categoria] = {}
            for nombre_item, data in items.items():
                if data['checkbox'].isChecked():
                    dependencias_finales[categoria][nombre_item] = data['version']
                    if categoria == "templates": template_principal = nombre_item

        if not template_principal: template_principal = "Macuare_Estudio"

        # RESOLUCIÓN DESDE EL JSON (Sin interfaz gráfica que estorbe)
        vcs_config = self.config_factory.get_raw_config().get("vcs_engine", {})
        user_vcs = vcs_config.get("vcs_username", DEV_SVN_USER)
        pwd_vcs = vcs_config.get("vcs_password", DEV_SVN_PASSWORD)

        self.btn_crear.setEnabled(False)
        self.btn_crear.setText(self.tr("Creating..."))
        self.lbl_status.setText(self.tr("Forging structure and connecting repositories..."))
        self.lbl_status.setStyleSheet("color: #F59E0B; font-weight: bold;")
        self.lbl_status.show()

        # Inyectar plantilla seleccionada en el Builder (IMPORTANTE)
        self.builder.kitsu_active_template = kitsu_template

        self.worker = ProjectCreationWorker(
            self.builder, nombre, version_blender, dependencias_finales, 
            template_principal, self.ruta_splash, user_vcs, pwd_vcs
        )
        self.worker.result.connect(self._on_creation_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _on_creation_finished(self, exito: bool, mensaje: str):
        if exito:
            self.lbl_status.setText(mensaje)
            self.lbl_status.setStyleSheet("color: #10B981; font-weight: bold;")
            self.on_success() 
            self.close()
        else:
            self.btn_crear.setEnabled(True)
            self.btn_crear.setText(self.tr("Generate Project"))
            self.lbl_status.setText(mensaje)
            self.lbl_status.setStyleSheet("color: #EF4444; font-weight: bold;")
