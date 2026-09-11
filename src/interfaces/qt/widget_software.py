# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/widget_software.py
# Rol Arquitectónico: UI Component / Software Provisioning & Manifest Wizard
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.2.0
# =========================================================================================

"""
Software Provisioning Tab for the Global Settings.
Integrates the asynchronous Blender index web scraper and the Vault Manifest Wizard.
Connects with AddonParser to natively inspect and validate add-on compatibility.
Features the Blender Studio Tools Auto-Fetcher, which downloads, repackages, 
and bulk-registers upstream studio dependencies on the fly.
"""

import re
import requests
# import zipfile
# import tempfile
# import shutil
from pathlib import Path

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QScrollArea, QFrame, QLineEdit, 
                               QFileDialog, QCheckBox, QProgressBar, QComboBox,
                               QMessageBox)
from PySide6.QtCore import Qt, QThread, Signal

from src.infrastructure.file_downloader import FileDownloaderWorker
from src.infrastructure.manifest_manager import ManifestManager
from src.domain.addon_parser import AddonParser

# from core.git_packager import StudioToolsPackagerWorker

# Importa el nuevo Worker encapsulado
from src.infrastructure.provisioning_workers import StudioToolsFetchWorker

MACUARE_LTS_VERSIONS = ("2.83", "2.93", "3.3", "3.6", "4.2", "4.5", "5.2")

class BlenderBaseScraper(QThread):
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def run(self):
        url = "https://download.blender.org/release/"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            matches = re.findall(r'href="Blender([0-9a-zA-Z.-]+)/"', response.text)
            versiones = sorted(list(set(matches)), reverse=True)
            self.data_ready.emit(versiones)
        except Exception as e:
            self.error_occurred.emit(f"Base connection failed: {str(e)}")

class SubversionScraper(QThread):
    data_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, base_version: str):
        super().__init__()
        self.base_version = base_version

    def run(self):
        url = f"https://download.blender.org/release/Blender{self.base_version}/"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            
            archivos = re.findall(r'href="([^"]+\.(?:zip|tar\.xz|dmg|tar\.bz2))"', response.text)
            sub_versions = {}
            
            for f in archivos:
                fl = f.lower()
                if "linux" in fl: os_type = "linux"
                elif "win" in fl: os_type = "windows"
                elif "mac" in fl or "darwin" in fl: os_type = "macos"
                else: continue
                
                v_match = re.search(r'blender-([0-9]+\.[0-9]+\.[0-9a-zA-Z.-]+)-', fl)
                if not v_match: continue
                    
                v_num = v_match.group(1)
                if v_num not in sub_versions:
                    sub_versions[v_num] = {}
                sub_versions[v_num][os_type] = url + f
                
            self.data_ready.emit(sub_versions)
        except Exception as e:
            self.error_occurred.emit(f"Sub-version parsing failed: {str(e)}")

class SoftwareProvisioningWidget(QWidget):
    def __init__(self, parent, config_factory, status_callback, **kwargs):
        super().__init__(parent, **kwargs)
        self.config_factory = config_factory
        self.status_callback = status_callback
        
        vault_root = self.config_factory.get_workspace_root() / "openstudio_vault"
        self.manifest_manager = ManifestManager(vault_root)
        self.boveda_blender = self.manifest_manager.software_dir / "blender_versions"
        
        self.download_queue = []
        self.current_downloader = None
        self.studio_downloader = None
        
        self.setObjectName("SoftwareProvisioningWidgetBase")
        self._build_ui()
        self._refresh_manifest_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        split_layout = QHBoxLayout()
        split_layout.setSpacing(20)

        # --- LEFT PANEL: Blender Scraper ---
        scraper_frame = QFrame(self)
        scraper_frame.setObjectName("FloatingCard")
        scraper_frame.setStyleSheet("QFrame#FloatingCard { border: 1px solid #334155; border-radius: 8px; background: #0F172A; }")
        scraper_layout = QVBoxLayout(scraper_frame)
        
        remote_header = QHBoxLayout()
        lbl_remote = QLabel(self.tr("Remote Index (Blender.org)"))
        lbl_remote.setStyleSheet("color: #F8FAFC; font-size: 14px; font-weight: bold;")
        remote_header.addWidget(lbl_remote)
        remote_header.addStretch()
        
        self.btn_fetch = QPushButton(self.tr("Sync Index"))
        self.btn_fetch.setObjectName("SecondaryButton")
        self.btn_fetch.setFixedSize(100, 28)
        self.btn_fetch.clicked.connect(self._obtener_versiones_base)
        remote_header.addWidget(self.btn_fetch)
        scraper_layout.addLayout(remote_header)

        os_layout = QHBoxLayout()
        lbl_os = QLabel(self.tr("Target OS:"))
        lbl_os.setStyleSheet("color: #64748B; font-weight: bold; font-size: 12px;")
        os_layout.addWidget(lbl_os)
        
        self.chk_win = QCheckBox("Win")
        self.chk_win.setChecked(True)
        self.chk_lin = QCheckBox("Lin")
        self.chk_mac = QCheckBox("Mac")
        
        for chk in [self.chk_win, self.chk_lin, self.chk_mac]:
            chk.setStyleSheet("color: #94A3B8; font-size: 12px; margin-left: 5px;")
            os_layout.addWidget(chk)
        os_layout.addStretch()
        scraper_layout.addLayout(os_layout)

        self.remote_scroll = QScrollArea()
        self.remote_scroll.setWidgetResizable(True)
        self.remote_scroll.setStyleSheet("border: none; background: transparent; margin-top: 10px;")
        
        self.remote_widget = QWidget()
        self.remote_list_layout = QVBoxLayout(self.remote_widget)
        self.remote_list_layout.setAlignment(Qt.AlignTop)
        self.remote_scroll.setWidget(self.remote_widget)
        
        scraper_layout.addWidget(self.remote_scroll)
        split_layout.addWidget(scraper_frame, stretch=1)

        # --- RIGHT PANEL: Manifest Wizard ---
        wizard_frame = QFrame(self)
        wizard_frame.setObjectName("FloatingCard")
        wizard_frame.setStyleSheet("QFrame#FloatingCard { border: 1px solid #334155; border-radius: 8px; background: #0F172A; }")
        wizard_layout = QVBoxLayout(wizard_frame)

        lbl_wizard = QLabel(self.tr("Vault Manifest Wizard"))
        lbl_wizard.setStyleSheet("color: #F8FAFC; font-size: 14px; font-weight: bold;")
        wizard_layout.addWidget(lbl_wizard)
        
        lbl_desc = QLabel(self.tr("Map required add-ons to local Blender binaries."))
        lbl_desc.setStyleSheet("color: #64748B; font-size: 11px; margin-bottom: 10px;")
        wizard_layout.addWidget(lbl_desc)

        # Version Selector
        select_layout = QHBoxLayout()
        lbl_sel = QLabel(self.tr("Blender Version:"))
        lbl_sel.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 12px;")
        select_layout.addWidget(lbl_sel)
        
        self.combo_versions = QComboBox()
        self.combo_versions.setFixedHeight(30)
        self.combo_versions.setStyleSheet("background-color: #1E293B; border: 1px solid #475569; color: white; border-radius: 4px;")
        self.combo_versions.currentIndexChanged.connect(self._render_mapped_addons)
        select_layout.addWidget(self.combo_versions, stretch=1)
        
        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setFixedSize(30, 30)
        self.btn_refresh.setStyleSheet("background-color: #334155; color: white; border-radius: 4px;")
        self.btn_refresh.clicked.connect(self._refresh_manifest_ui)
        select_layout.addWidget(self.btn_refresh)
        wizard_layout.addLayout(select_layout)

        # Add-on List
        self.addons_scroll = QScrollArea()
        self.addons_scroll.setWidgetResizable(True)
        self.addons_scroll.setStyleSheet("border: 1px solid #1E293B; border-radius: 4px; background: #0F172A; margin-top: 10px;")
        
        self.addons_widget = QWidget()
        self.addons_layout = QVBoxLayout(self.addons_widget)
        self.addons_layout.setAlignment(Qt.AlignTop)
        self.addons_scroll.setWidget(self.addons_widget)
        wizard_layout.addWidget(self.addons_scroll, stretch=1)

        # Registration Forms
        form_layout = QHBoxLayout()
        self.btn_register_addon = QPushButton(self.tr("+ Link New (.zip)"))
        self.btn_register_addon.setObjectName("PrimaryButton")
        self.btn_register_addon.setFixedHeight(35)
        self.btn_register_addon.setCursor(Qt.PointingHandCursor)
        self.btn_register_addon.clicked.connect(self._trigger_addon_registration)
        form_layout.addWidget(self.btn_register_addon)
        
        self.btn_fetch_studio = QPushButton(self.tr("🌐 Auto-Fetch Studio Tools"))
        self.btn_fetch_studio.setObjectName("SecondaryButton")
        self.btn_fetch_studio.setFixedHeight(35)
        self.btn_fetch_studio.setCursor(Qt.PointingHandCursor)
        self.btn_fetch_studio.clicked.connect(self._trigger_studio_tools_fetch)
        form_layout.addWidget(self.btn_fetch_studio)

        wizard_layout.addLayout(form_layout)
        split_layout.addWidget(wizard_frame, stretch=1)
        main_layout.addLayout(split_layout, stretch=1)

        # PROGRESS BAR
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: none; background-color: #1E293B; border-radius: 3px; }
            QProgressBar::chunk { background-color: #10B981; border-radius: 3px; }
        """)
        self.progress_bar.hide()
        main_layout.addWidget(self.progress_bar)

    def _limpiar_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()

    # --- SCRAPER LOGIC ---

    def _obtener_versiones_base(self):
        self._limpiar_layout(self.remote_list_layout)
        self.btn_fetch.setEnabled(False)
        self.scraper_base = BlenderBaseScraper()
        self.scraper_base.data_ready.connect(self._renderizar_versiones_base)
        self.scraper_base.start()

    def _renderizar_versiones_base(self, versiones: list):
        self._limpiar_layout(self.remote_list_layout)
        self.btn_fetch.setEnabled(True)
        for v in versiones:
            row = QHBoxLayout()
            lbl = QLabel(f"Blender {v}")
            lbl.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 13px;")
            row.addWidget(lbl)
            
            if v in MACUARE_LTS_VERSIONS:
                lts = QLabel("LTS")
                lts.setStyleSheet("background-color: #3B82F6; color: white; padding: 2px 6px; border-radius: 4px; font-size: 9px; font-weight: bold;")
                row.addWidget(lts)
            
            row.addStretch()
            btn = QPushButton(self.tr("Inspect"))
            btn.setObjectName("SecondaryButton")
            btn.setFixedSize(70, 24)
            btn.clicked.connect(lambda _, version=v: self._obtener_subversiones(version))
            row.addWidget(btn)
            
            self.remote_list_layout.addWidget(self._wrap_in_frame(row))

    def _obtener_subversiones(self, base_version: str):
        self._limpiar_layout(self.remote_list_layout)
        lbl_loading = QLabel(self.tr("Scanning packages for v{0}...").format(base_version))
        lbl_loading.setStyleSheet("color: #F59E0B; font-style: italic;")
        self.remote_list_layout.addWidget(lbl_loading)
        
        self.scraper_sub = SubversionScraper(base_version)
        self.scraper_sub.data_ready.connect(lambda data: self._renderizar_subversiones(base_version, data))
        self.scraper_sub.start()

    def _renderizar_subversiones(self, base_version: str, data: dict):
        self._limpiar_layout(self.remote_list_layout)
        btn_back = QPushButton(self.tr("← Back to Index"))
        btn_back.setObjectName("LinkButton")
        btn_back.clicked.connect(self._obtener_versiones_base)
        self.remote_list_layout.addWidget(btn_back, alignment=Qt.AlignLeft)
        
        for sub_v in sorted(data.keys(), reverse=True):
            row = QHBoxLayout()
            lbl = QLabel(f"v{sub_v}")
            lbl.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 12px;")
            row.addWidget(lbl)
            
            os_map = data[sub_v]
            os_visuals = []
            for os_type, url in os_map.items():
                file_name = url.split('/')[-1]
                if (self.boveda_blender / file_name).exists():
                    os_visuals.append(f"<span style='color: #10B981;'>{os_type} ✓</span>")
                else:
                    os_visuals.append(f"<span style='color: #64748B;'>{os_type}</span>")
                    
            lbl_av = QLabel(f"[{' | '.join(os_visuals)}]")
            lbl_av.setTextFormat(Qt.RichText)
            row.addWidget(lbl_av)
            row.addStretch()
            
            btn = QPushButton(self.tr("↓ Queue"))
            btn.setStyleSheet("background-color: #4F46E5; color: white; border-radius: 4px; font-size: 11px; padding: 4px 8px;")
            btn.clicked.connect(lambda _, v=sub_v, om=os_map: self._procesar_descarga(om))
            row.addWidget(btn)
            
            self.remote_list_layout.addWidget(self._wrap_in_frame(row))

    def _wrap_in_frame(self, layout):
        frame = QFrame()
        frame.setStyleSheet("background-color: #1E293B; border-radius: 6px; padding: 2px;")
        frame.setLayout(layout)
        return frame

    def _procesar_descarga(self, os_map: dict):
        urls = []
        if self.chk_win.isChecked() and "windows" in os_map: urls.append(os_map["windows"])
        if self.chk_lin.isChecked() and "linux" in os_map: urls.append(os_map["linux"])
        if self.chk_mac.isChecked() and "macos" in os_map: urls.append(os_map["macos"])
        
        if not urls:
            self.status_callback(self.tr("Warning: No packages for selected OS."), "yellow")
            return
            
        encolados, omitidos = 0, 0
        self.boveda_blender.mkdir(parents=True, exist_ok=True)
        
        for url in urls:
            dest = self.boveda_blender / url.split('/')[-1]
            if dest.exists(): omitidos += 1
            else:
                self.download_queue.append((url, dest))
                encolados += 1
                
        if encolados > 0:
            self.status_callback(self.tr("Queued {0} packages.").format(encolados), "green")
            self._procesar_siguiente_descarga()
        elif omitidos > 0:
            self.status_callback(self.tr("Skipped. Binaries already exist in Vault."), "green")

    def _procesar_siguiente_descarga(self):
        if self.current_downloader and self.current_downloader.isRunning(): return
            
        if not self.download_queue:
            self.progress_bar.hide()
            self._refresh_manifest_ui()
            self.status_callback(self.tr("All downloads completed."), "green")
            return
            
        url, dest = self.download_queue.pop(0)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        
        self.current_downloader = FileDownloaderWorker(url, dest)
        self.current_downloader.progress_updated.connect(self.progress_bar.setValue)
        self.current_downloader.status_update.connect(self.status_callback)
        self.current_downloader.download_completed.connect(self._descarga_finalizada)
        self.current_downloader.error_occurred.connect(self._descarga_fallida)
        self.current_downloader.start()

    def _descarga_finalizada(self, path: Path):
        self.current_downloader.deleteLater()
        self.current_downloader = None
        self._procesar_siguiente_descarga()

    def _descarga_fallida(self, error: str):
        self.status_callback(self.tr("Download failed: {0}").format(error), "red")
        self.current_downloader.deleteLater()
        self.current_downloader = None
        self._procesar_siguiente_descarga()

    # --- MANIFEST WIZARD LOGIC ---

    def _refresh_manifest_ui(self):
        self.combo_versions.blockSignals(True)
        self.combo_versions.clear()
        
        versions = self.manifest_manager.scan_local_blender_binaries()
        if versions:
            self.combo_versions.addItems(versions)
            self.btn_register_addon.setEnabled(True)
            self.btn_fetch_studio.setEnabled(True)
        else:
            self.combo_versions.addItem(self.tr("-- No Binaries Found --"))
            self.btn_register_addon.setEnabled(False)
            self.btn_fetch_studio.setEnabled(False)
            
        self.combo_versions.blockSignals(False)
        self._render_mapped_addons()

    def _render_mapped_addons(self):
        self._limpiar_layout(self.addons_layout)
        current_version = self.combo_versions.currentText()
        
        if not current_version or current_version.startswith("--"):
            return
            
        addons = self.manifest_manager.get_addons_for_version(current_version)
        if not addons:
            lbl = QLabel(self.tr("No add-ons registered for this version."))
            lbl.setStyleSheet("color: #64748B; font-style: italic;")
            self.addons_layout.addWidget(lbl)
            return
            
        for addon in addons:
            row = QHBoxLayout()
            lbl_n = QLabel(f"📦 {addon.get('name', 'Unknown')}")
            lbl_n.setStyleSheet("color: #10B981; font-weight: bold; font-size: 13px;")
            row.addWidget(lbl_n)
            
            lbl_v = QLabel(f"v{addon.get('version', '?.?')}")
            lbl_v.setStyleSheet("color: #94A3B8; font-size: 11px;")
            row.addWidget(lbl_v)
            row.addStretch()
            
            self.addons_layout.addWidget(self._wrap_in_frame(row))

    def _trigger_addon_registration(self):
        current_version = self.combo_versions.currentText()
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select Add-on Package"), "", self.tr("Zip Archives (*.zip)")
        )
        if not file_path: return
            
        zip_path = Path(file_path)
        self.status_callback(self.tr("Inspecting add-on metadata..."), "yellow")
        parsed_data = AddonParser.parse_zip(zip_path)
        
        if not parsed_data["is_valid"]:
            reply = QMessageBox.warning(
                self, 
                self.tr("Invalid or Missing Metadata"),
                self.tr("Could not find a valid blender_manifest.toml or bl_info in __init__.py.\n\nDo you want to force installation anyway?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                self.status_callback(self.tr("Add-on registration cancelled."), "gray")
                return

        addon_name = parsed_data["name"]
        addon_version = parsed_data["version"]
        min_blender = parsed_data["min_blender_version"]

        if not AddonParser.is_compatible(min_blender, current_version):
            reply = QMessageBox.warning(
                self,
                self.tr("Compatibility Warning"),
                self.tr(f"This add-on requires Blender {min_blender} or higher.\nYou are linking it to Blender {current_version}.\n\nProceed at your own risk. Force link?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                self.status_callback(self.tr("Add-on registration cancelled."), "gray")
                return

        exito, msg = self.manifest_manager.register_addon(
            blender_version=current_version,
            addon_name=addon_name,
            addon_version=addon_version,
            source_zip=zip_path
        )
        
        if exito:
            self.status_callback(self.tr("✓ Add-on successfully linked: {0} v{1}").format(addon_name, addon_version), "green")
            self._render_mapped_addons()
        else:
            self.status_callback(self.tr("✗ Registration failed: {0}").format(msg), "red")

    def _trigger_studio_tools_fetch(self):
        current_version = self.combo_versions.currentText()
        if not current_version or current_version.startswith("--"):
            self.status_callback(self.tr("Select a valid Blender version first."), "yellow")
            return
            
        self.btn_fetch_studio.setEnabled(False)
        self.btn_register_addon.setEnabled(False)
        
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        
        # Obtenemos la ruta absoluta de la bóveda de forma directa
        vault_root = self.config_factory.get_workspace_root() / "openstudio_vault"
        
        # Le entregamos al Worker puramente la ruta física
        self.studio_fetch_worker = StudioToolsFetchWorker(vault_root, current_version)
        self.studio_fetch_worker.progress_updated.connect(self.progress_bar.setValue)
        self.studio_fetch_worker.status_update.connect(self.status_callback)
        self.studio_fetch_worker.finished_packing.connect(self._on_studio_tools_packaged)
        self.studio_fetch_worker.error_occurred.connect(self._on_studio_tools_error)
        self.studio_fetch_worker.start()

    def _on_studio_tools_packaged(self):
        if hasattr(self, 'studio_fetch_worker') and self.studio_fetch_worker:
            self.studio_fetch_worker.deleteLater()
            self.studio_fetch_worker = None
        
        self.btn_fetch_studio.setEnabled(True)
        self.btn_register_addon.setEnabled(True)
        self.progress_bar.hide()
        self._refresh_manifest_ui()

    def _on_studio_tools_error(self, error: str):
        if hasattr(self, 'studio_fetch_worker') and self.studio_fetch_worker: 
            self.studio_fetch_worker.deleteLater()
            self.studio_fetch_worker = None
        
        self.btn_fetch_studio.setEnabled(True)
        self.btn_register_addon.setEnabled(True)
        self.progress_bar.hide()
        self.status_callback(self.tr("Studio Tools Fetch Failed: {0}").format(error), "red")
