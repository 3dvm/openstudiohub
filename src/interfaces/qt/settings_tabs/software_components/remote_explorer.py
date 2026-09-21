# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/settings_tabs/software_components/remote_explorer.py
# Architectural role: Component / Blender.org Scraper & Downloader
# =========================================================================================

"""Official Blender.org repository browser and downloader."""

import re
from pathlib import Path

import requests
from PySide6.QtCore import Qt, Signal

from src.infrastructure.qt_worker import ManagedWorker
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.application.services.vault_service import VaultService
from src.infrastructure.provisioning_workers import BlenderDirectDownloadWorker

MACUARE_LTS_VERSIONS = ("2.83", "2.93", "3.3", "3.6", "4.2", "4.5", "5.2")


class BlenderBaseScraper(ManagedWorker):
    """Fetches the base version folders from download.blender.org/release/."""

    data_ready = Signal(list)
    error_occurred = Signal(str)

    def run(self) -> None:
        url = "https://download.blender.org/release/"
        headers = {"User-Agent": "OpenStudioHub/1.0"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            matches = re.findall(r'href="Blender([0-9a-zA-Z.-]+)/"', response.text)
            versions = sorted(list(set(matches)), reverse=True)
            self.data_ready.emit(versions)
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(f"Base connection failure: {str(error)}")


class SubversionScraper(ManagedWorker):
    """Fetches the binary files inside a specific Blender folder."""

    data_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, base_version: str) -> None:
        super().__init__()
        self.base_version = base_version

    def run(self) -> None:
        url = f"https://download.blender.org/release/Blender{self.base_version}/"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()

            files = re.findall(r'href="([^"]+\.(?:zip|tar\.xz|dmg|tar\.bz2))"', response.text)
            sub_versions = {}

            for file in files:
                fl = file.lower()
                if "linux" in fl:
                    os_type = "linux"
                elif "win" in fl:
                    os_type = "windows"
                elif "mac" in fl or "darwin" in fl:
                    os_type = "macos"
                else:
                    continue

                v_match = re.search(r"blender-([0-9]+\.[0-9]+\.[0-9a-zA-Z.-]+)-", fl)
                if not v_match:
                    continue

                v_num = v_match.group(1)
                if v_num not in sub_versions:
                    sub_versions[v_num] = {}
                sub_versions[v_num][os_type] = file

            self.data_ready.emit(sub_versions)
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(f"Failed to scan binaries: {str(error)}")


class RemoteExplorerWidget(QFrame):
    download_finished = Signal(bool, str)

    def __init__(self, parent, vault_service: VaultService, status_callback) -> None:
        super().__init__(parent)
        self.vault_service = vault_service
        self.status_callback = status_callback

        self.vault_blender = self.vault_service.vault_root / "blender_versions"
        self._scraper_base = None
        self._scraper_sub = None
        self._download_worker = None

        self.setObjectName("FloatingCard")
        self._build_ui()

    def _build_ui(self) -> None:
        browser_layout = QVBoxLayout(self)
        browser_layout.setContentsMargins(20, 20, 20, 20)
        browser_layout.setSpacing(15)

        header_layout = QHBoxLayout()
        lbl_section_title = QLabel(self.tr("🌐 Official Remote Repository (download.blender.org)"))
        lbl_section_title.setObjectName("H2Title")
        header_layout.addWidget(lbl_section_title)
        header_layout.addStretch()

        self.btn_fetch = QPushButton(self.tr("🔄 Sync Index"))
        self.btn_fetch.setObjectName("SecondaryButton")
        self.btn_fetch.setFixedSize(110, 30)
        self.btn_fetch.clicked.connect(self._fetch_base_versions)
        header_layout.addWidget(self.btn_fetch)
        browser_layout.addLayout(header_layout)

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
            chk.stateChanged.connect(self._apply_os_filters)
            os_layout.addWidget(chk)

        os_layout.addStretch()
        browser_layout.addLayout(os_layout)

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

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { border: none; background: #1F2531; } QProgressBar::chunk { background-color: #10B981; }")
        self.progress_bar.hide()
        browser_layout.addWidget(self.progress_bar)

        self._show_empty_message("Click 'Sync Index' to connect to Blender.org")

    def _clear_layout(self) -> None:
        while self.remote_list_layout.count():
            child = self.remote_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _show_empty_message(self, message: str, color: str = "#64748B") -> None:
        self._clear_layout()
        lbl = QLabel(message)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {color}; font-size: 13px; font-style: italic; margin-top: 30px;")
        self.remote_list_layout.addWidget(lbl)

    def _wrap_in_frame(self, layout) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("background-color: #1E293B; border-radius: 6px; padding: 4px;")
        frame.setLayout(layout)
        return frame

    # ------------------------------------------------------------------
    # EXPLORATION
    # ------------------------------------------------------------------
    def _fetch_base_versions(self) -> None:
        self.btn_fetch.setEnabled(False)
        self._show_empty_message("Scanning Blender.org repositories...", "#F59E0B")

        self._scraper_base = BlenderBaseScraper()
        self._scraper_base.data_ready.connect(self._render_base_versions)
        self._scraper_base.error_occurred.connect(lambda msg: self._show_empty_message(msg, "#EF4444"))
        self._scraper_base.start()

    def _render_base_versions(self, versions: list) -> None:
        self._clear_layout()
        self.btn_fetch.setEnabled(True)

        for version in versions:
            row = QHBoxLayout()
            row.setContentsMargins(10, 5, 10, 5)

            lbl = QLabel(f" Blender {version}")
            lbl.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 14px;")
            row.addWidget(lbl)

            if version in MACUARE_LTS_VERSIONS:
                lts = QLabel("LTS")
                lts.setStyleSheet("background-color: #3B82F6; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold;")
                row.addWidget(lts)

            row.addStretch()

            btn = QPushButton()
            icon = self._create_colored_icon(Path("assets/icons/folder.svg"), "#F97316")
            btn.setIcon(icon)
            btn.setObjectName("SecondaryButton")
            btn.setFixedSize(100, 30)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, v=version: self._fetch_subversions(v))
            row.addWidget(btn)

            self.remote_list_layout.addWidget(self._wrap_in_frame(row))

    def _fetch_subversions(self, base_version: str) -> None:
        self._show_empty_message(f"Loading packages for Blender {base_version}...", "#06B6D4")
        self.current_base_version = base_version

        self._scraper_sub = SubversionScraper(base_version)
        self._scraper_sub.data_ready.connect(lambda data: self._render_subversions(base_version, data))
        self._scraper_sub.error_occurred.connect(lambda msg: self._show_empty_message(msg, "#EF4444"))
        self._scraper_sub.start()

    def _render_subversions(self, base_version: str, data: dict) -> None:
        self.current_subversions_data = data
        self._apply_os_filters()

    def _apply_os_filters(self) -> None:
        if not hasattr(self, "current_subversions_data") or not self.current_subversions_data:
            return

        self._clear_layout()

        nav_row = QHBoxLayout()
        btn_back = QPushButton(self.tr("← Back to Folders"))
        btn_back.setObjectName("LinkButton")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.clicked.connect(self._fetch_base_versions)
        nav_row.addWidget(btn_back)
        nav_row.addStretch()
        self.remote_list_layout.addLayout(nav_row)

        data = self.current_subversions_data
        base_version = self.current_base_version

        active_os = []
        if self.chk_win.isChecked():
            active_os.append("windows")
        if self.chk_lin.isChecked():
            active_os.append("linux")
        if self.chk_mac.isChecked():
            active_os.append("macos")

        shown = 0

        for sub_v in sorted(data.keys(), reverse=True):
            os_map = data[sub_v]

            for os_type in active_os:
                if os_type in os_map:
                    filename = os_map[os_type]
                    self._create_file_row(base_version, sub_v, os_type, filename)
                    shown += 1

        if shown == 0:
            lbl = QLabel(self.tr("No packages match the selected OS filters."))
            lbl.setStyleSheet("color: #94A3B8; font-style: italic; margin-top: 10px;")
            self.remote_list_layout.addWidget(lbl)

    def _create_file_row(self, base_version: str, version: str, os_type: str, filename: str) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(10, 5, 10, 5)

        os_colors = {"windows": "#564256", "macos": "#5B5F97", "linux": "#F59E0B"}
        color = os_colors.get(os_type, "#64748B")

        lbl_os = QLabel(os_type.upper())
        lbl_os.setFixedWidth(65)
        lbl_os.setAlignment(Qt.AlignCenter)
        lbl_os.setStyleSheet(f"background-color: {color}; color: #0F172A; font-weight: bold; border-radius: 4px; font-size: 10px; padding: 3px;")
        row.addWidget(lbl_os)

        lbl_file = QLabel(filename)
        lbl_file.setStyleSheet("color: #E2E8F0; font-size: 13px;")
        row.addWidget(lbl_file)
        row.addStretch()

        self.vault_blender.mkdir(parents=True, exist_ok=True)
        local_path = self.vault_blender / filename

        if local_path.exists():
            lbl_ok = QLabel(self.tr("✓ In Vault"))
            lbl_ok.setStyleSheet("color: #10B981; font-weight: bold; font-size: 13px; padding-right: 10px;")
            row.addWidget(lbl_ok)
        else:
            btn_dl = QPushButton(self.tr("📥 Download"))
            btn_dl.setObjectName("PrimaryButton")
            btn_dl.setFixedSize(90, 30)
            btn_dl.setCursor(Qt.PointingHandCursor)
            folder_name = f"Blender{base_version}/"
            btn_dl.clicked.connect(lambda _, f=folder_name, n=filename: self._trigger_download(f, n))
            row.addWidget(btn_dl)

        self.remote_list_layout.addWidget(self._wrap_in_frame(row))

    # ------------------------------------------------------------------
    # DOWNLOAD
    # ------------------------------------------------------------------
    def _trigger_download(self, folder_name: str, file_name: str) -> None:
        if self._download_worker and self._download_worker.isRunning():
            self.status_callback(self.tr("A download is already in progress."), "yellow")
            return

        self.progress_bar.setValue(0)
        self.progress_bar.show()

        self.status_callback(self.tr("Downloading {0}...").format(file_name), "yellow")

        self._download_worker = BlenderDirectDownloadWorker(folder_name, file_name, self.vault_blender)
        self._download_worker.progress.connect(self.progress_bar.setValue)
        self._download_worker.status.connect(self.status_callback)
        self._download_worker.finished.connect(self._on_download_done)
        self._download_worker.start()

    def _on_download_done(self, success: bool, filename: str) -> None:
        self.progress_bar.hide()

        if self._download_worker:
            self._download_worker.deleteLater()
            self._download_worker = None

        if success:
            self.download_finished.emit(success, filename)
            self._apply_os_filters()

    def _create_colored_icon(self, icon_path: Path, color_hex: str) -> QIcon:
        if not icon_path.exists():
            return QIcon()
        try:
            with open(icon_path, "r", encoding="utf-8") as handle:
                svg_content = handle.read()
            svg_content = svg_content.replace("currentColor", color_hex)
            svg_content = svg_content.replace("#000000", color_hex)
            svg_content = svg_content.replace('#000"', f'{color_hex}"')
            svg_content = svg_content.replace("#000'", f"{color_hex}'")
            pixmap = QPixmap()
            pixmap.loadFromData(svg_content.encode("utf-8"), "SVG")
            return QIcon(pixmap)
        except Exception:  # noqa: BLE001
            return QIcon(str(icon_path))
