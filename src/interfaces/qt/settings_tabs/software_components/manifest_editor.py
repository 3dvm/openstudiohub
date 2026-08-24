# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/settings_tabs/software_components/manifest_editor.py
# Rol Arquitectónico: UI Component / Manifest Tree & Addon Injector
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0 (Decoupled Component)
# =========================================================================================

import shutil
import os
import zipfile
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QComboBox, QPushButton, QTreeWidget, QTreeWidgetItem, 
                               QFrame, QProgressBar, QFileDialog)
from PySide6.QtCore import Qt, Signal

from src.domain.addon_inspector import AddonInspector
from src.infrastructure.provisioning_workers import StudioToolsFetchWorker

class ManifestEditorWidget(QFrame):
    modified = Signal()

    def __init__(self, parent, vault_manager, status_callback):
        super().__init__(parent)
        self.vault_manager = vault_manager
        self.status_callback = status_callback
        self._is_loading = True
        self.manifest_data = {}
        self._fetch_worker = None

        self.setObjectName("FloatingCard")
        self._build_ui()

    def _build_ui(self):
        manifest_layout = QVBoxLayout(self)
        manifest_layout.setContentsMargins(20, 20, 20, 20)
        manifest_layout.setSpacing(15)

        # --- Controles Superiores ---
        control_layout = QHBoxLayout()
        lbl_active_v = QLabel(self.tr("Target Context (Blender Version):"))
        lbl_active_v.setObjectName("H2Title")
        control_layout.addWidget(lbl_active_v)

        self.combo_versions = QComboBox()
        self.combo_versions.setObjectName("FormInput")
        self.combo_versions.setFixedWidth(120)
        self.combo_versions.currentTextChanged.connect(self._redibujar_arbol)
        control_layout.addWidget(self.combo_versions)

        control_layout.addStretch()

        # self.btn_fetch_studio_tools = QPushButton(self.tr("Auto-Fetch Blender Studio Tools"))
        # self.btn_fetch_studio_tools.setStyleSheet("background-color: #06B6D4; color: white; font-weight: bold; border-radius: 6px; border: none; padding: 0 15px;")
        # self.btn_fetch_studio_tools.setObjectName("SecondaryButton")
        # self.btn_fetch_studio_tools.setFixedHeight(30)
        # self.btn_fetch_studio_tools.clicked.connect(self._disparar_fetch_studio_tools)
        # control_layout.addWidget(self.btn_fetch_studio_tools)

        self.btn_addons_fetch_pack = QPushButton(self.tr("Fetch and Pack Pipeline addons"))
        # self.btn_pack_toolkit.setStyleSheet("background-color: #F59E0B; color: #0F172A; font-weight: bold; border-radius: 6px; border: none; padding: 0 15px;")
        self.btn_addons_fetch_pack.setObjectName("SecondaryButton")
        self.btn_addons_fetch_pack.setFixedHeight(30)
        self.btn_addons_fetch_pack.clicked.connect(self._fetch_pack_pipe_addons)
        control_layout.addWidget(self.btn_addons_fetch_pack)

        manifest_layout.addLayout(control_layout)

        # --- Árbol Interactivo ---
        self.tree_manifest = QTreeWidget()
        self.tree_manifest.setColumnCount(4)
        self.tree_manifest.setHeaderLabels([self.tr("Component / Addon"), self.tr("Version"), self.tr("Description"), self.tr("Mandatory")])
        self.tree_manifest.setColumnWidth(0, 220)
        self.tree_manifest.setColumnWidth(1, 80)
        self.tree_manifest.setColumnWidth(2, 350)
        self.tree_manifest.setStyleSheet("""
            QTreeWidget { background-color: #1E293B; border: 1px solid #334155; border-radius: 8px; color: #F8FAFC; outline: none; }
            QHeaderView::section { background-color: #0F172A; color: #94A3B8; font-weight: bold; padding: 5px; border: 1px solid #334155; }
            QTreeWidget::item:hover { background-color: #334155; }
        """)
        self.tree_manifest.itemChanged.connect(self._on_tree_item_changed)
        manifest_layout.addWidget(self.tree_manifest, stretch=1)

        # --- Inyección Manual de ZIP ---
        inject_layout = QHBoxLayout()
        self.btn_load_local_zip = QPushButton(self.tr("📂 Add / Load Local .zip Addon"))
        self.btn_load_local_zip.setObjectName("SecondaryButton")
        self.btn_load_local_zip.setFixedSize(220, 35)
        self.btn_load_local_zip.clicked.connect(self._inyectar_zip_local)
        inject_layout.addWidget(self.btn_load_local_zip)
        
        inject_layout.addStretch()
        manifest_layout.addLayout(inject_layout)

        # --- Barra de Progreso ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: #1F2531; border: none; } QProgressBar::chunk { background-color: #06B6D4; }")
        self.progress_bar.hide()
        manifest_layout.addWidget(self.progress_bar)

    # ---------------------------------------------------------
    # CORE LOGIC: ACTUALIZACIONES Y RENDERIZADO
    # ---------------------------------------------------------
    def _on_field_modified(self):
        if not self._is_loading:
            self.modified.emit()

    def set_versiones_disponibles(self, versiones: list, auto_select: str = None):
        """Actualiza el dropdown basado en los binarios descubiertos."""
        self.combo_versions.blockSignals(True)
        self.combo_versions.clear()
        self.combo_versions.addItems(versiones)
        if auto_select and auto_select in versiones:
            self.combo_versions.setCurrentText(auto_select)
        self.combo_versions.blockSignals(False)
        self._redibujar_arbol()

    def _redibujar_arbol(self):
        self.tree_manifest.blockSignals(True)
        self.tree_manifest.clear()
        version_activa = self.combo_versions.currentText()
        
        if not version_activa or version_activa not in self.manifest_data:
            self.tree_manifest.blockSignals(False)
            return

        bloque_categorias = self.manifest_data[version_activa]
        
        for cat_name, items in bloque_categorias.items():
            cat_item = QTreeWidgetItem(self.tree_manifest)
            cat_item.setText(0, f"{cat_name.upper()}")
            cat_item.setForeground(0, Qt.lightGray)
            cat_item.setExpanded(True)
            
            for item_name, data in items.items():
                child = QTreeWidgetItem(cat_item)
                child.setText(0, item_name)
                child.setText(1, str(data.get("version", "1.0")))
                child.setText(2, data.get("description", ""))
                
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(3, Qt.Checked if data.get("mandatory", False) else Qt.Unchecked)
                
                child.setData(0, Qt.UserRole, cat_name)
                child.setData(1, Qt.UserRole, item_name)

        self.tree_manifest.blockSignals(False)

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        if column == 3:
            cat_name = item.data(0, Qt.UserRole)
            item_name = item.data(1, Qt.UserRole)
            version_activa = self.combo_versions.currentText()
            
            if cat_name and item_name and version_activa in self.manifest_data:
                is_checked = (item.checkState(3) == Qt.Checked)
                self.manifest_data[version_activa][cat_name][item_name]["mandatory"] = is_checked
                self._on_field_modified()

    def _fetch_pack_pipe_addons(self):
        self.btn_addons_fetch_pack.setEnabled(False)
        self._disparar_fetch_studio_tools()
        self._empaquetar_toolkit_local()

    # ---------------------------------------------------------
    # OPERACIONES: FETCH, PACK & INJECT
    # ---------------------------------------------------------
    def _disparar_fetch_studio_tools(self):
        version = self.combo_versions.currentText()
        if not version: return

        vault_root = self.vault_manager.config_factory.get_vault_path()
        # self.btn_fetch_studio_tools.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()

        self._fetch_worker = StudioToolsFetchWorker(vault_root, version)
        self._fetch_worker.status_update.connect(self.status_callback)
        self._fetch_worker.progress_updated.connect(self.progress_bar.setValue) 
        self._fetch_worker.finished_packing.connect(self._on_studio_tools_finished)
        self._fetch_worker.error_occurred.connect(self._on_studio_tools_error)
        self._fetch_worker.finished.connect(self._cleanup_fetch_worker)
        self._fetch_worker.start()

    def _on_studio_tools_finished(self, herramientas_nuevas: dict):
        self.btn_addons_fetch_pack.setEnabled(True)
        self.progress_bar.hide()
        version_activa = self.combo_versions.currentText()
        
        if version_activa and version_activa in self.manifest_data:
            if "addons" not in self.manifest_data[version_activa]:
                self.manifest_data[version_activa]["addons"] = {}
            self.manifest_data[version_activa]["addons"].update(herramientas_nuevas)

        self._redibujar_arbol()
        self._on_field_modified()

    def _on_studio_tools_error(self, error: str):
        self.btn_addons_fetch_pack.setEnabled(True)
        self.progress_bar.hide()
        self.status_callback(self.tr("Studio Tools Fetch Failed: {0}").format(error), "red")

    def _cleanup_fetch_worker(self):
        if self._fetch_worker:
            self._fetch_worker.deleteLater()
            self._fetch_worker = None

    def _inyectar_zip_local(self):
        version_activa = self.combo_versions.currentText()
        if not version_activa:
            self.status_callback(self.tr("✗ Select Target Context first."), "yellow")
            return

        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("Select Addon .zip"), "", "ZIP Files (*.zip)")
        if not file_path: return

        zip_path = Path(file_path)
        meta = AddonInspector.inspect_zip(zip_path)

        if not meta or meta["name"] == "unknown_addon":
            self.status_callback(self.tr("✗ Invalid Addon: No manifest found."), "red")
            return

        addon_name = meta["name"]
        addon_ver = meta["version"]
        
        addons_dir = self.vault_manager.manifest_path.parent / "addons"
        addons_dir.mkdir(parents=True, exist_ok=True)
        
        target_zip_name = f"{addon_name}-{addon_ver}.zip"
        target_zip_path = addons_dir / target_zip_name
        
        if not target_zip_path.exists():
            shutil.copy2(zip_path, target_zip_path)
            self.status_callback(self.tr("✓ Addon '{0}' imported.").format(target_zip_name), "green")
        
        if "addons" not in self.manifest_data[version_activa]:
            self.manifest_data[version_activa]["addons"] = {}

        self.manifest_data[version_activa]["addons"][addon_name] = {
            "version": addon_ver,
            "description": meta["description"][:60] + "...",
            "mandatory": False,
            "requires": []
        }

        self._redibujar_arbol()
        self._on_field_modified()

    def _empaquetar_toolkit_local(self):
        version_activa = self.combo_versions.currentText()
        if not version_activa: return

        origen_toolkit = Path("addons/openstudio_toolkit")
        if not origen_toolkit.exists() or not origen_toolkit.is_dir():
            self.status_callback(self.tr("✗ Source folder 'openstudio_toolkit' not found."), "red")
            return

        self.status_callback(self.tr("Packaging OpenStudio Toolkit..."), "yellow")
        temp_dir = Path(tempfile.mkdtemp())
        zip_path = temp_dir / "openstudio_toolkit.zip"

        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(origen_toolkit):
                    for file in files:
                        if file.endswith(".pyc") or "__pycache__" in root: continue
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(origen_toolkit)
                        zipf.write(file_path, arcname)

            addon_name = "openstudio_toolkit"
            addon_ver = "0.5.0"
            addons_dir = self.vault_manager.manifest_path.parent / "addons"
            addons_dir.mkdir(parents=True, exist_ok=True)
            
            target_zip_name = f"{addon_name}-{addon_ver}.zip"
            shutil.copy2(zip_path, addons_dir / target_zip_name)
            self.status_callback(self.tr("✓ Addon '{0}' packaged and injected.").format(target_zip_name), "green")

            if "addons" not in self.manifest_data[version_activa]:
                self.manifest_data[version_activa]["addons"] = {}

            self.manifest_data[version_activa]["addons"][addon_name] = {
                "version": addon_ver,
                "description": "OpenStudio Pipeline Gatekeeper & Kitsu Synergy",
                "mandatory": True, 
                "requires": []
            }

            self._redibujar_arbol()
            self._on_field_modified()

        except Exception as e:
            self.status_callback(f"✗ Failed to pack toolkit: {e}", "red")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
