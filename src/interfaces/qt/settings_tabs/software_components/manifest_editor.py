# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/settings_tabs/software_components/manifest_editor.py
# Architectural role: UI Component / Manifest Tree & Addon Injector
# =========================================================================================

"""Manifest editor: renders the add-on tree and injects local .zip add-ons."""

import os
import platform
import shutil
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.domain.addon_inspector import AddonInspector
from src.domain.vault.integrity import base_version, register_disk_versions, remove_version, slugify
from src.application.services.vault_service import VaultService
from src.infrastructure.provisioning_workers import (
    BlenderDirectDownloadWorker,
    StudioToolsFetchWorker,
    VaultIntegrityWorker,
)
from src.interfaces.qt.settings_tabs.software_components.integrity_dialog import VaultIntegrityDialog
from src.interfaces.qt.settings_tabs.software_components.remote_explorer import SubversionScraper


class ManifestEditorWidget(QFrame):
    modified = Signal()

    def __init__(self, parent, vault_service: VaultService, status_callback) -> None:
        super().__init__(parent)
        self.vault_service = vault_service
        self.status_callback = status_callback
        self._is_loading = True
        self.manifest_data = {}
        self._fetch_worker = None
        self._integrity_worker = None
        self._last_integrity_report = None
        self._binary_scraper = None
        self._binary_download_worker = None

        self.setObjectName("FloatingCard")
        self._build_ui()

    def _build_ui(self) -> None:
        manifest_layout = QVBoxLayout(self)
        manifest_layout.setContentsMargins(20, 20, 20, 20)
        manifest_layout.setSpacing(15)

        control_layout = QHBoxLayout()
        lbl_active_v = QLabel(self.tr("Target Context (Blender Version):"))
        lbl_active_v.setObjectName("H2Title")
        control_layout.addWidget(lbl_active_v)

        self.combo_versions = QComboBox()
        self.combo_versions.setObjectName("FormInput")
        self.combo_versions.setFixedWidth(120)
        self.combo_versions.currentTextChanged.connect(self._redraw_tree)
        control_layout.addWidget(self.combo_versions)

        control_layout.addStretch()

        self.btn_verify_integrity = QPushButton(self.tr("🩺 Verify Manifest Integrity"))
        self.btn_verify_integrity.setObjectName("SecondaryButton")
        self.btn_verify_integrity.setFixedHeight(30)
        self.btn_verify_integrity.clicked.connect(self._verify_integrity)
        control_layout.addWidget(self.btn_verify_integrity)

        self.btn_addons_fetch_pack = QPushButton(self.tr("Fetch and Pack Pipeline addons"))
        self.btn_addons_fetch_pack.setObjectName("SecondaryButton")
        self.btn_addons_fetch_pack.setFixedHeight(30)
        self.btn_addons_fetch_pack.clicked.connect(self._fetch_pack_pipeline_addons)
        control_layout.addWidget(self.btn_addons_fetch_pack)

        manifest_layout.addLayout(control_layout)

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

        inject_layout = QHBoxLayout()
        self.btn_load_local_zip = QPushButton(self.tr("📂 Add / Load Local .zip Addon"))
        self.btn_load_local_zip.setObjectName("SecondaryButton")
        self.btn_load_local_zip.setFixedSize(220, 35)
        self.btn_load_local_zip.clicked.connect(self._inject_local_zip)
        inject_layout.addWidget(self.btn_load_local_zip)

        inject_layout.addStretch()
        manifest_layout.addLayout(inject_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: #1F2531; border: none; } QProgressBar::chunk { background-color: #06B6D4; }")
        self.progress_bar.hide()
        manifest_layout.addWidget(self.progress_bar)

    # ------------------------------------------------------------------
    # CORE LOGIC
    # ------------------------------------------------------------------
    def _on_field_modified(self) -> None:
        if not self._is_loading:
            self.modified.emit()

    def set_available_versions(self, versions: list, auto_select: str | None = None) -> None:
        self.combo_versions.blockSignals(True)
        self.combo_versions.clear()
        self.combo_versions.addItems(versions)
        if auto_select and auto_select in versions:
            self.combo_versions.setCurrentText(auto_select)
        self.combo_versions.blockSignals(False)
        self._redraw_tree()

    def _redraw_tree(self) -> None:
        self.tree_manifest.blockSignals(True)
        self.tree_manifest.clear()
        active_version = self.combo_versions.currentText()

        if not active_version or active_version not in self.manifest_data:
            self.tree_manifest.blockSignals(False)
            return

        categories_block = self.manifest_data[active_version]

        for cat_name, items in categories_block.items():
            if not isinstance(items, dict):
                continue
            cat_item = QTreeWidgetItem(self.tree_manifest)
            cat_item.setText(0, f"{cat_name.upper()}")
            cat_item.setForeground(0, Qt.lightGray)
            cat_item.setExpanded(True)

            for item_name, data in items.items():
                if not isinstance(data, dict):
                    continue
                child = QTreeWidgetItem(cat_item)
                child.setText(0, item_name)
                child.setText(1, str(data.get("version", "1.0")))
                child.setText(2, data.get("description", ""))

                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(3, Qt.Checked if data.get("mandatory", False) else Qt.Unchecked)

                child.setData(0, Qt.UserRole, cat_name)
                child.setData(1, Qt.UserRole, item_name)

        self.tree_manifest.blockSignals(False)

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 3:
            cat_name = item.data(0, Qt.UserRole)
            item_name = item.data(1, Qt.UserRole)
            active_version = self.combo_versions.currentText()

            if cat_name and item_name and active_version in self.manifest_data:
                is_checked = item.checkState(3) == Qt.Checked
                self.manifest_data[active_version][cat_name][item_name]["mandatory"] = is_checked
                self._on_field_modified()

    def _fetch_pack_pipeline_addons(self) -> None:
        self.btn_addons_fetch_pack.setEnabled(False)
        self._trigger_studio_tools_fetch()
        self._package_local_toolkit()

    # ------------------------------------------------------------------
    # INTEGRITY AUDIT & REPAIRS
    # ------------------------------------------------------------------
    def _verify_integrity(self) -> None:
        if self._integrity_worker and self._integrity_worker.isRunning():
            self.status_callback(self.tr("Integrity audit already running."), "yellow")
            return

        self.btn_verify_integrity.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_callback(self.tr("Auditing vault against the manifest..."), "yellow")

        self._integrity_worker = VaultIntegrityWorker(
            self.vault_service.vault_root, dict(self.manifest_data)
        )
        self._integrity_worker.report_ready.connect(self._on_integrity_report)
        self._integrity_worker.error_occurred.connect(self._on_integrity_error)
        self._integrity_worker.finished.connect(self._cleanup_integrity_worker)
        self._integrity_worker.start()

    def _cleanup_integrity_worker(self) -> None:
        if self._integrity_worker:
            self._integrity_worker.deleteLater()
            self._integrity_worker = None

    def _on_integrity_error(self, error: str) -> None:
        self.btn_verify_integrity.setEnabled(True)
        self.progress_bar.hide()
        self.status_callback(self.tr("Integrity audit failed: {0}").format(error), "red")

    def _on_integrity_report(self, report) -> None:
        self.btn_verify_integrity.setEnabled(True)
        self.progress_bar.hide()
        self._last_integrity_report = report

        if not report.has_issues:
            self.status_callback(self.tr("✓ Vault manifest is consistent."), "green")

        dialog = VaultIntegrityDialog(self, report, active_version=self.combo_versions.currentText())
        dialog.apply_safe_fixes_requested.connect(self._apply_integrity_fixes)
        dialog.redownload_binary_requested.connect(self._redownload_binary)
        dialog.delete_version_requested.connect(self._delete_version)
        dialog.redownload_addons_requested.connect(self._redownload_missing_addons)
        dialog.move_misplaced_requested.connect(self._move_misplaced_binaries)
        dialog.register_orphan_addons_requested.connect(self._register_orphan_addons)
        dialog.exec()

    def _apply_integrity_fixes(self) -> None:
        report = self._last_integrity_report
        if report is None:
            return

        added = register_disk_versions(self.manifest_data, report)

        for version, name, _manifest_v, disk_v in report.addon_version_mismatches:
            categories = self.manifest_data.get(version)
            if isinstance(categories, dict):
                entry = categories.get("addons", {}).get(name)
                if isinstance(entry, dict):
                    entry["version"] = disk_v

        if added:
            self.status_callback(
                self.tr("✓ Registered downloaded Blender version(s): {0}").format(", ".join(added)),
                "green",
            )
        else:
            self.status_callback(self.tr("✓ Applied manifest fixes."), "green")

        self._refresh_versions()
        self._on_field_modified()

    def _refresh_versions(self) -> None:
        active = self.combo_versions.currentText()
        versions = list(self.manifest_data.keys())
        self.set_available_versions(versions, auto_select=active if active in versions else None)

    def _delete_version(self, version: str) -> None:
        if remove_version(self.manifest_data, version):
            self.status_callback(self.tr("✓ Removed Blender {0} from the manifest.").format(version), "green")
            self._refresh_versions()
            self._on_field_modified()

    def _redownload_binary(self, version: str) -> None:
        self.status_callback(self.tr("Resolving Blender {0} packages...").format(version), "yellow")
        self._binary_scraper = SubversionScraper(base_version(version))
        self._binary_scraper.data_ready.connect(lambda data: self._start_binary_download(data, version))
        self._binary_scraper.error_occurred.connect(
            lambda msg: self.status_callback(msg, "red")
        )
        self._binary_scraper.start()

    def _start_binary_download(self, data: dict, version: str) -> None:
        os_type = self._current_os()
        os_map = data.get(version, {}) if isinstance(data, dict) else {}
        filename = os_map.get(os_type) or next(iter(os_map.values()), None)

        if not filename:
            self.status_callback(
                self.tr("✗ No downloadable package found for Blender {0}.").format(version), "red"
            )
            return

        dest_dir = self.vault_service.vault_root / "blender_versions"
        self.progress_bar.setValue(0)
        self.progress_bar.show()

        self._binary_download_worker = BlenderDirectDownloadWorker(
            f"Blender{base_version(version)}/", filename, dest_dir
        )
        self._binary_download_worker.progress.connect(self.progress_bar.setValue)
        self._binary_download_worker.status.connect(self.status_callback)
        self._binary_download_worker.finished.connect(self._on_binary_download_done)
        self._binary_download_worker.start()

    def _on_binary_download_done(self, success: bool, filename: str) -> None:
        self.progress_bar.hide()
        if self._binary_download_worker:
            self._binary_download_worker.deleteLater()
            self._binary_download_worker = None
        if success:
            self.status_callback(
                self.tr("✓ {0} downloaded. Re-run the integrity check to register it.").format(filename),
                "green",
            )

    def _move_misplaced_binaries(self) -> None:
        report = self._last_integrity_report
        if report is None:
            return
        dest_dir = self.vault_service.vault_root / "blender_versions"
        dest_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        for path in report.misplaced_binaries:
            try:
                shutil.move(str(path), str(dest_dir / path.name))
                moved += 1
            except Exception as error:  # noqa: BLE001
                self.status_callback(self.tr("✗ Could not move {0}: {1}").format(path.name, error), "red")
        if moved:
            self.status_callback(
                self.tr("✓ Moved {0} archive(s) into blender_versions/.").format(moved), "green"
            )
            self._verify_integrity()

    def _register_orphan_addons(self, names: list) -> None:
        report = self._last_integrity_report
        active_version = self.combo_versions.currentText()
        if report is None or not active_version or active_version not in self.manifest_data:
            self.status_callback(self.tr("✗ Select a target Blender version first."), "yellow")
            return

        by_slug = {slugify(asset.name): asset for asset in report.orphan_addons}
        addons = self.manifest_data[active_version].setdefault("addons", {})
        registered = 0
        for name in names:
            asset = by_slug.get(slugify(name))
            if asset is None:
                continue
            try:
                rel_path = asset.path.relative_to(self.vault_service.vault_root).as_posix()
            except ValueError:
                rel_path = str(asset.path)
            addons[asset.name] = {
                "version": asset.version,
                "description": asset.description or "Registered from vault scan",
                "mandatory": False,
                "requires": [],
                "path": rel_path,
            }
            registered += 1

        if registered:
            self._redraw_tree()
            self._on_field_modified()
            self.status_callback(
                self.tr("✓ Registered {0} add-on(s) to Blender {1}.").format(registered, active_version),
                "green",
            )

    def _redownload_missing_addons(self) -> None:
        self.status_callback(self.tr("Re-downloading pipeline add-ons..."), "yellow")
        self.btn_addons_fetch_pack.setEnabled(False)
        self._trigger_studio_tools_fetch()
        self._package_local_toolkit()

    def _current_os(self) -> str:
        system = platform.system().lower()
        if system == "windows":
            return "windows"
        if system == "darwin":
            return "macos"
        return "linux"

    # ------------------------------------------------------------------
    # OPERATIONS: FETCH, PACK & INJECT
    # ------------------------------------------------------------------
    def _trigger_studio_tools_fetch(self) -> None:
        version = self.combo_versions.currentText()
        if not version:
            return

        vault_root = self.vault_service.vault_root
        self.progress_bar.setValue(0)
        self.progress_bar.show()

        self._fetch_worker = StudioToolsFetchWorker(vault_root, version)
        self._fetch_worker.status_update.connect(self.status_callback)
        self._fetch_worker.progress_updated.connect(self.progress_bar.setValue)
        self._fetch_worker.finished_packing.connect(self._on_studio_tools_finished)
        self._fetch_worker.error_occurred.connect(self._on_studio_tools_error)
        self._fetch_worker.finished.connect(self._cleanup_fetch_worker)
        self._fetch_worker.start()

    def _on_studio_tools_finished(self, new_tools: dict) -> None:
        self.btn_addons_fetch_pack.setEnabled(True)
        self.progress_bar.hide()
        active_version = self.combo_versions.currentText()

        if active_version and active_version in self.manifest_data:
            if "addons" not in self.manifest_data[active_version]:
                self.manifest_data[active_version]["addons"] = {}
            self.manifest_data[active_version]["addons"].update(new_tools)

        self._redraw_tree()
        self._on_field_modified()

    def _on_studio_tools_error(self, error: str) -> None:
        self.btn_addons_fetch_pack.setEnabled(True)
        self.progress_bar.hide()
        self.status_callback(self.tr("Studio Tools Fetch Failed: {0}").format(error), "red")

    def _cleanup_fetch_worker(self) -> None:
        if self._fetch_worker:
            self._fetch_worker.deleteLater()
            self._fetch_worker = None

    def _inject_local_zip(self) -> None:
        active_version = self.combo_versions.currentText()
        if not active_version:
            self.status_callback(self.tr("✗ Select Target Context first."), "yellow")
            return

        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("Select Addon .zip"), "", "ZIP Files (*.zip)")
        if not file_path:
            return

        zip_path = Path(file_path)
        meta = AddonInspector.inspect_zip(zip_path)

        if not meta or meta["name"] == "unknown_addon":
            self.status_callback(self.tr("✗ Invalid Addon: No manifest found."), "red")
            return

        addon_name = meta["name"]
        addon_version = meta["version"]

        addons_dir = self.vault_service.vault_root / "addons"
        addons_dir.mkdir(parents=True, exist_ok=True)

        target_zip_name = f"{addon_name}-{addon_version}.zip"
        target_zip_path = addons_dir / target_zip_name

        if not target_zip_path.exists():
            shutil.copy2(zip_path, target_zip_path)
            self.status_callback(self.tr("✓ Addon '{0}' imported.").format(target_zip_name), "green")

        if "addons" not in self.manifest_data[active_version]:
            self.manifest_data[active_version]["addons"] = {}

        self.manifest_data[active_version]["addons"][addon_name] = {
            "version": addon_version,
            "description": meta["description"][:60] + "...",
            "mandatory": False,
            "requires": [],
        }

        self._redraw_tree()
        self._on_field_modified()

    def _package_local_toolkit(self) -> None:
        active_version = self.combo_versions.currentText()
        if not active_version:
            return

        source_toolkit = Path("addons/openstudio_toolkit")
        if not source_toolkit.exists() or not source_toolkit.is_dir():
            self.status_callback(self.tr("✗ Source folder 'openstudio_toolkit' not found."), "red")
            return

        self.status_callback(self.tr("Packaging OpenStudio Toolkit..."), "yellow")
        temp_dir = Path(tempfile.mkdtemp())
        zip_path = temp_dir / "openstudio_toolkit.zip"

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(source_toolkit):
                    for file in files:
                        if file.endswith(".pyc") or "__pycache__" in root:
                            continue
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(source_toolkit)
                        zipf.write(file_path, arcname)

            addon_name = "openstudio_toolkit"
            addon_version = "0.5.0"
            addons_dir = self.vault_service.vault_root / "addons"
            addons_dir.mkdir(parents=True, exist_ok=True)

            target_zip_name = f"{addon_name}-{addon_version}.zip"
            shutil.copy2(zip_path, addons_dir / target_zip_name)
            self.status_callback(self.tr("✓ Addon '{0}' packaged and injected.").format(target_zip_name), "green")

            if "addons" not in self.manifest_data[active_version]:
                self.manifest_data[active_version]["addons"] = {}

            self.manifest_data[active_version]["addons"][addon_name] = {
                "version": addon_version,
                "description": "OpenStudio Pipeline Gatekeeper & Kitsu Synergy",
                "mandatory": True,
                "requires": [],
            }

            self._redraw_tree()
            self._on_field_modified()

        except Exception as error:  # noqa: BLE001
            self.status_callback(f"✗ Failed to pack toolkit: {error}", "red")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
