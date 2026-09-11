# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/settings_tabs/tab_software.py
# Architectural role: UI Component / Software Provisioning Coordinator
# =========================================================================================

"""Software provisioning tab (remote explorer + manifest editor)."""

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from src.application.services.vault_service import VaultService
from src.interfaces.qt.settings_tabs.software_components.manifest_editor import ManifestEditorWidget
from src.interfaces.qt.settings_tabs.software_components.remote_explorer import RemoteExplorerWidget


class TabSoftware(QWidget):
    modified = Signal()

    def __init__(self, parent, vault_service: VaultService, status_callback) -> None:
        super().__init__(parent)
        self.vault_service = vault_service
        self.status_callback = status_callback

        self._build_ui()
        self._connect_modules()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(20)

        split_layout = QHBoxLayout()
        split_layout.setSpacing(20)

        self.remote_explorer = RemoteExplorerWidget(self, self.vault_service, self.status_callback)
        split_layout.addWidget(self.remote_explorer, stretch=1)

        self.manifest_editor = ManifestEditorWidget(self, self.vault_service, self.status_callback)
        split_layout.addWidget(self.manifest_editor, stretch=1)

        main_layout.addLayout(split_layout)

    def _connect_modules(self) -> None:
        self.remote_explorer.download_finished.connect(self._on_blender_downloaded)
        self.manifest_editor.modified.connect(self.modified.emit)

    def _on_blender_downloaded(self, success: bool, filename: str) -> None:
        if success and filename:
            match = re.search(r"blender-(\d+\.\d+\.\d+)", filename.lower())
            detected_version = match.group(1) if match else "4.2.0"

            if detected_version not in self.manifest_editor.manifest_data:
                self.manifest_editor.manifest_data[detected_version] = {"addons": {}, "templates": {}}
                self.modified.emit()

            versions = list(self.manifest_editor.manifest_data.keys())
            self.manifest_editor.set_available_versions(versions, auto_select=detected_version)

    # ------------------------------------------------------------------
    # PUBLIC API (required by SettingsWidget)
    # ------------------------------------------------------------------
    def load_data(self, manifest_config: dict) -> None:
        self.manifest_editor._is_loading = True
        self.manifest_editor.manifest_data = {}

        for key, val in manifest_config.items():
            if isinstance(val, dict):
                raw_version = val.get("blender_version") or key
                clean_version = str(raw_version).lstrip("vV ")

                categories_block = val.get("categories") if "categories" in val else val
                if isinstance(categories_block, dict):
                    self.manifest_editor.manifest_data[clean_version] = categories_block

        versions = list(self.manifest_editor.manifest_data.keys())
        self.manifest_editor.set_available_versions(versions)
        self.manifest_editor._is_loading = False

    def software_payload(self) -> dict:
        full_payload = {}
        for version, categories in self.manifest_editor.manifest_data.items():
            full_payload[version] = {
                "blender_version": version,
                "categories": categories,
            }
        return full_payload
