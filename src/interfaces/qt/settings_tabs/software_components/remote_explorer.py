# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/settings_tabs/software_components/remote_explorer.py
# Rol Arquitectónico: Component / Blender.org Scraper & Downloader
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.5.0 (Visual Browser & Vault Integration)
# =========================================================================================

import re
from PySide6.QtGui import QIcon, QPixmap
import requests
from pathlib import Path

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QFrame, QProgressBar, QCheckBox,
                               QScrollArea)
from PySide6.QtCore import Qt, Signal, QThread

from src.infrastructure.provisioning_workers import BlenderDirectDownloadWorker

MACUARE_LTS_VERSIONS = ("2.83", "2.93", "3.3", "3.6", "4.2", "4.5", "5.2")

# ---------------------------------------------------------
# ASYNC SCRAPERS (Aislados para este componente)
# ---------------------------------------------------------
class BlenderBaseScraper(QThread):
    """Obtiene la lista de carpetas base de versiones desde download.blender.org/release/"""
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def run(self):
        url = "https://download.blender.org/release/"
        headers = {'User-Agent': 'OpenStudioHub/1.0'}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            matches = re.findall(r'href="Blender([0-9a-zA-Z.-]+)/"', response.text)
            versiones = sorted(list(set(matches)), reverse=True)
            self.data_ready.emit(versiones)
        except Exception as e:
            self.error_occurred.emit(f"Fallo de conexión base: {str(e)}")

class SubversionScraper(QThread):
    """Obtiene los archivos binarios dentro de una carpeta específica de Blender"""
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
                sub_versions[v_num][os_type] = f
                
            self.data_ready.emit(sub_versions)
        except Exception as e:
            self.error_occurred.emit(f"Fallo al escanear binarios: {str(e)}")


# ---------------------------------------------------------
# UI COMPONENT
# ---------------------------------------------------------
class RemoteExplorerWidget(QFrame):
    download_finished = Signal(bool, str)

    def __init__(self, parent, vault_manager, status_callback):
        super().__init__(parent)
        self.vault_manager = vault_manager
        self.status_callback = status_callback
        
        self.boveda_blender = self.vault_manager.manifest_path.parent / "blender_versions"
        self._scraper_base = None
        self._scraper_sub = None
        self._download_worker = None

        self.setObjectName("FloatingCard")
        self._build_ui()

    def _build_ui(self):
        browser_layout = QVBoxLayout(self)
        browser_layout.setContentsMargins(20, 20, 20, 20)
        browser_layout.setSpacing(15)

        # 1. Cabecera y Botón de Sincronización
        header_layout = QHBoxLayout()
        lbl_section_title = QLabel(self.tr("🌐 Official Remote Repository (download.blender.org)"))
        lbl_section_title.setObjectName("H2Title")
        header_layout.addWidget(lbl_section_title)
        header_layout.addStretch()

        self.btn_fetch = QPushButton(self.tr("🔄 Sync Index"))
        self.btn_fetch.setObjectName("SecondaryButton")
        self.btn_fetch.setFixedSize(110, 30)
        self.btn_fetch.clicked.connect(self._obtener_versiones_base)
        header_layout.addWidget(self.btn_fetch)
        browser_layout.addLayout(header_layout)

        # 2. Filtros de Sistema Operativo
        os_layout = QHBoxLayout()
        lbl_os = QLabel(self.tr("Filter Binaries by OS:"))
        lbl_os.setObjectName("InputLabel")
        os_layout.addWidget(lbl_os)
        
        self.chk_win = QCheckBox("Windows")
        self.chk_win.setChecked(True)
        self.chk_lin = QCheckBox("Linux")
        self.chk_lin.setChecked(True)
        self.chk_mac = QCheckBox("macOS")
        
        for chk in [self.chk_win, self.chk_lin, self.chk_mac]:
            chk.setStyleSheet("color: #F8FAFC; font-size: 13px; margin-left: 10px; spacing: 5px;")
            chk.stateChanged.connect(self._aplicar_filtros_os)
            os_layout.addWidget(chk)
            
        os_layout.addStretch()
        browser_layout.addLayout(os_layout)

        # 3. Área Gigante de Navegación (Scroll Area)
        self.remote_scroll = QScrollArea()
        self.remote_scroll.setWidgetResizable(True)
        self.remote_scroll.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 6px; background-color: #0F172A; }")
        
        self.remote_widget = QWidget()
        self.remote_widget.setStyleSheet("background: transparent;")
        self.remote_list_layout = QVBoxLayout(self.remote_widget)
        self.remote_list_layout.setAlignment(Qt.AlignTop)
        self.remote_list_layout.setSpacing(8)
        self.remote_scroll.setWidget(self.remote_widget)
        
        browser_layout.addWidget(self.remote_scroll, stretch=1)

        # 4. Barra de Progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { border: none; background: #1F2531; } QProgressBar::chunk { background-color: #10B981; }")
        self.progress_bar.hide()
        browser_layout.addWidget(self.progress_bar)
        
        # Mensaje inicial
        self._mostrar_mensaje_vacio("Haz clic en 'Sync Index' para conectar con Blender.org")

    def _limpiar_layout(self):
        while self.remote_list_layout.count():
            child = self.remote_list_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()

    def _mostrar_mensaje_vacio(self, mensaje: str, color: str = "#64748B"):
        self._limpiar_layout()
        lbl = QLabel(mensaje)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {color}; font-size: 13px; font-style: italic; margin-top: 30px;")
        self.remote_list_layout.addWidget(lbl)

    def _wrap_in_frame(self, layout):
        frame = QFrame()
        frame.setStyleSheet("background-color: #1E293B; border-radius: 6px; padding: 4px;")
        frame.setLayout(layout)
        return frame

    # ---------------------------------------------------------
    # EXPLORACIÓN: CARPETAS BASE
    # ---------------------------------------------------------
    def _obtener_versiones_base(self):
        self.btn_fetch.setEnabled(False)
        self._mostrar_mensaje_vacio("Scanning Blender.org repositories...", "#F59E0B")
        
        self._scraper_base = BlenderBaseScraper()
        self._scraper_base.data_ready.connect(self._renderizar_versiones_base)
        self._scraper_base.error_occurred.connect(lambda msg: self._mostrar_mensaje_vacio(msg, "#EF4444"))
        self._scraper_base.start()

    def _renderizar_versiones_base(self, versiones: list):
        self._limpiar_layout()
        self.btn_fetch.setEnabled(True)
        
        for v in versiones:
            row = QHBoxLayout()
            row.setContentsMargins(10, 5, 10, 5)
            
            lbl = QLabel(f" Blender {v}")
            lbl.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 14px;")
            row.addWidget(lbl)
            
            if v in MACUARE_LTS_VERSIONS:
                lts = QLabel("LTS")
                lts.setStyleSheet("background-color: #3B82F6; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold;")
                row.addWidget(lts)
            
            row.addStretch()
            
            # btn = QPushButton(self.tr("Open Folder"))
            btn = QPushButton()
            icon = self._crear_icono_coloreado(Path("assets/icons/folder.svg"), "#F97316")
            btn.setIcon(icon)

            btn.setObjectName("SecondaryButton")
            btn.setFixedSize(100, 30)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, version=v: self._obtener_subversiones(version))
            row.addWidget(btn)
            
            self.remote_list_layout.addWidget(self._wrap_in_frame(row))

    # ---------------------------------------------------------
    # EXPLORACIÓN: ARCHIVOS BINARIOS
    # ---------------------------------------------------------
    def _obtener_subversiones(self, base_version: str):
        self._mostrar_mensaje_vacio(f"Loading packages for Blender {base_version}...", "#06B6D4")
        self.current_base_version = base_version
        
        self._scraper_sub = SubversionScraper(base_version)
        self._scraper_sub.data_ready.connect(lambda data: self._renderizar_subversiones(base_version, data))
        self._scraper_sub.error_occurred.connect(lambda msg: self._mostrar_mensaje_vacio(msg, "#EF4444"))
        self._scraper_sub.start()

    def _renderizar_subversiones(self, base_version: str, data: dict):
        self.current_subversions_data = data
        self._aplicar_filtros_os()

    def _aplicar_filtros_os(self):
        """Redibuja la vista de archivos aplicando los filtros de OS seleccionados."""
        if not hasattr(self, 'current_subversions_data') or not self.current_subversions_data:
            return
            
        self._limpiar_layout()
        
        # Botón para volver atrás
        nav_row = QHBoxLayout()
        btn_back = QPushButton(self.tr("← Back to Folders"))
        btn_back.setObjectName("LinkButton")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.clicked.connect(self._obtener_versiones_base)
        nav_row.addWidget(btn_back)
        nav_row.addStretch()
        self.remote_list_layout.addLayout(nav_row)

        data = self.current_subversions_data
        base_version = self.current_base_version
        
        # Determinar qué sistemas mostrar
        os_activos = []
        if self.chk_win.isChecked(): os_activos.append("windows")
        if self.chk_lin.isChecked(): os_activos.append("linux")
        if self.chk_mac.isChecked(): os_activos.append("macos")

        elementos_mostrados = 0

        for sub_v in sorted(data.keys(), reverse=True):
            os_map = data[sub_v]
            
            for os_type in os_activos:
                if os_type in os_map:
                    filename = os_map[os_type]
                    self._crear_fila_archivo(base_version, sub_v, os_type, filename)
                    elementos_mostrados += 1
                    
        if elementos_mostrados == 0:
            lbl = QLabel(self.tr("No packages match the selected OS filters."))
            lbl.setStyleSheet("color: #94A3B8; font-style: italic; margin-top: 10px;")
            self.remote_list_layout.addWidget(lbl)

    def _crear_fila_archivo(self, base_version: str, version: str, os_type: str, filename: str):
        row = QHBoxLayout()
        row.setContentsMargins(10, 5, 10, 5)
        
        # Icono / OS Badge
        os_colors = {"windows": "#564256", "macos": "#5B5F97", "linux": "#F59E0B"}
        color = os_colors.get(os_type, "#64748B")
        
        lbl_os = QLabel(os_type.upper())
        lbl_os.setFixedWidth(65)
        lbl_os.setAlignment(Qt.AlignCenter)
        lbl_os.setStyleSheet(f"background-color: {color}; color: #0F172A; font-weight: bold; border-radius: 4px; font-size: 10px; padding: 3px;")
        row.addWidget(lbl_os)
        
        # Nombre del archivo
        lbl_file = QLabel(filename)
        lbl_file.setStyleSheet("color: #E2E8F0; font-size: 13px;")
        row.addWidget(lbl_file)
        row.addStretch()
        
        # Verificación en Disco (Bóveda NAS)
        self.boveda_blender.mkdir(parents=True, exist_ok=True)
        ruta_local = self.boveda_blender / filename
        
        if ruta_local.exists():
            lbl_ok = QLabel(self.tr("✓ In Vault"))
            lbl_ok.setStyleSheet("color: #10B981; font-weight: bold; font-size: 13px; padding-right: 10px;")
            row.addWidget(lbl_ok)
        else:
            btn_dl = QPushButton(self.tr("📥 Download"))
            btn_dl.setObjectName("PrimaryButton")
            btn_dl.setFixedSize(90, 30)
            btn_dl.setCursor(Qt.PointingHandCursor)
            # Enlazamos el nombre de la carpeta real y el nombre del archivo
            folder_name = f"Blender{base_version}/"
            btn_dl.clicked.connect(lambda _, f=folder_name, n=filename: self._disparar_descarga(f, n))
            row.addWidget(btn_dl)
            
        self.remote_list_layout.addWidget(self._wrap_in_frame(row))

    # ---------------------------------------------------------
    # DESCARGA
    # ---------------------------------------------------------
    def _disparar_descarga(self, folder_name: str, file_name: str):
        if self._download_worker and self._download_worker.isRunning():
            self.status_callback(self.tr("A download is already in progress."), "yellow")
            return

        self.progress_bar.setValue(0)
        self.progress_bar.show()
        
        self.status_callback(self.tr("Downloading {0}...").format(file_name), "yellow")

        # Pasamos el nombre de la carpeta (ej. 'Blender4.2/') y el nombre del archivo exacto
        self._download_worker = BlenderDirectDownloadWorker(folder_name, file_name, self.boveda_blender)
        self._download_worker.progress.connect(self.progress_bar.setValue)
        self._download_worker.status.connect(self.status_callback)
        self._download_worker.finished.connect(self._on_download_done)
        self._download_worker.start()

    def _on_download_done(self, exito: bool, filename: str):
        self.progress_bar.hide()
        
        if self._download_worker:
            self._download_worker.deleteLater()
            self._download_worker = None
            
        if exito:
            self.download_finished.emit(exito, filename)
            # Refrescar la vista actual para que el botón cambie a "✓ In Vault"
            self._aplicar_filtros_os()

    def _crear_icono_coloreado(self, icon_path: Path, color_hex: str) -> QIcon:
        if not icon_path.exists(): return QIcon()
        try:
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            svg_content = svg_content.replace('currentColor', color_hex)
            svg_content = svg_content.replace('#000000', color_hex)
            svg_content = svg_content.replace('#000"', f'{color_hex}"')
            svg_content = svg_content.replace("#000'", f"{color_hex}'")
            pixmap = QPixmap()
            pixmap.loadFromData(svg_content.encode('utf-8'), "SVG")
            return QIcon(pixmap)
        except Exception:
            return QIcon(str(icon_path))

