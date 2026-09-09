# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/settings_widget.py
# Architectural role: UI Widget / Global Settings Container
# =========================================================================================

"""Global settings widget.

Coordinates the molecular sub-tabs and delegates persistence to the
``SettingsViewModel``.
"""

import shutil
from pathlib import Path

from PySide6.QtCore import QDir, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from src.application.services.vault_service import VaultService
from src.interfaces.qt.settings_tabs.tab_credentials import TabCredentials
from src.interfaces.qt.settings_tabs.tab_identity import TabIdentity
from src.interfaces.qt.settings_tabs.tab_software import TabSoftware
from src.interfaces.qt.settings_tabs.tab_topography import TabTopography
from src.interfaces.qt.settings_tabs.tab_vault import TabVault
from src.interfaces.qt.settings_tabs.tab_vcs import TabVCS
from src.interfaces.qt.viewmodels.settings_viewmodel import SettingsViewModel


class SettingsWidget(QFrame):
    def __init__(self, parent, viewmodel: SettingsViewModel, auth_service, production_service, vault_service: VaultService, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.vm = viewmodel
        self.auth_service = auth_service
        self.production_service = production_service
        self.vault_service = vault_service
        self.status_callback = self.vm.report_status

        self.setObjectName("SettingsWidgetBase")
        self.nav_buttons = {}

        self._build_ui()
        self._connect_modified_signals()
        self._load_current_data()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.tab_bar_frame = QFrame()
        self.tab_bar_frame.setStyleSheet("background-color: #1F2531; border-bottom: 1px solid #141820;")
        self.tab_bar_frame.setFixedHeight(35)

        self.tab_bar_layout = QHBoxLayout(self.tab_bar_frame)
        self.tab_bar_layout.setContentsMargins(15, 0, 15, 0)
        self.tab_bar_layout.setSpacing(2)

        self.lbl_unsaved_warning = QLabel("")

        self.stack = QStackedWidget()

        self.tab_identity = TabIdentity(self.auth_service, self.production_service, self.status_callback, parent=self.stack)
        self.tab_vault = TabVault(parent=self.stack)
        self.tab_vcs = TabVCS(parent=self.stack)
        self.tab_topography = TabTopography(parent=self.stack)
        self.tab_software = TabSoftware(self.stack, self.vault_service, self.status_callback)
        self.tab_credentials = TabCredentials(parent=self.stack)

        self._add_nav_item(self.tr("Identity and API"), self.tab_identity, 0)
        self._add_nav_item(self.tr("Vault Storage"), self.tab_vault, 1)
        self._add_nav_item(self.tr("Pipeline and VCS"), self.tab_vcs, 2)
        self._add_nav_item(self.tr("Project Topography"), self.tab_topography, 3)
        self._add_nav_item(self.tr("Software and Manifest"), self.tab_software, 4)
        self._add_nav_item(self.tr("Session Credentials"), self.tab_credentials, 5)

        self.tab_bar_layout.addStretch()
        self.tab_bar_layout.addWidget(self.lbl_unsaved_warning)

        main_layout.addWidget(self.tab_bar_frame)
        main_layout.addWidget(self.stack, stretch=1)

        footer_frame = QFrame()
        footer_layout = QHBoxLayout(footer_frame)
        footer_layout.setContentsMargins(15, 10, 15, 15)

        self.btn_save = QPushButton(self.tr("Save Local Changes"))
        self.btn_save.setObjectName("SecondaryButton")
        self.btn_save.setFixedSize(180, 40)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._save_configuration)
        footer_layout.addWidget(self.btn_save)

        footer_layout.addStretch()

        self.btn_export_seed = QPushButton(self.tr("Export Studio Seed (.seed)"))
        self.btn_export_seed.setObjectName("PrimaryButton")
        self.btn_export_seed.setFixedSize(240, 40)
        self.btn_export_seed.setCursor(Qt.PointingHandCursor)
        self.btn_export_seed.clicked.connect(self._export_studio_seed)
        footer_layout.addWidget(self.btn_export_seed)

        main_layout.addWidget(footer_frame)

    def _add_nav_item(self, text: str, widget, index: int) -> None:
        self.stack.addWidget(widget)
        btn = QPushButton(text)
        btn.setObjectName("TopTabInactive")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(34)
        btn.clicked.connect(lambda _, idx=index: self._switch_view(idx))

        self.tab_bar_layout.addWidget(btn)
        self.nav_buttons[index] = btn

        if index == 0:
            self._switch_view(0)

    def _switch_view(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for idx, btn in self.nav_buttons.items():
            btn.setObjectName("TopTabActive" if idx == index else "TopTabInactive")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _connect_modified_signals(self) -> None:
        self.tab_identity.modified.connect(self._on_field_modified)
        self.tab_vault.modified.connect(self._on_field_modified)
        self.tab_vcs.modified.connect(self._on_field_modified)
        self.tab_topography.modified.connect(self._on_field_modified)
        self.tab_software.modified.connect(self._on_field_modified)
        self.tab_credentials.modified.connect(self._on_field_modified)

    def _on_field_modified(self) -> None:
        self.lbl_unsaved_warning.setText(self.tr("● Unsaved Changes"))
        self.lbl_unsaved_warning.setStyleSheet("color: #F59E0B; font-weight: bold; font-size: 13px; margin-left: 15px;")

    def _load_current_data(self) -> None:
        state = self.vm.load_state()
        raw = state["raw"]
        manifest = state["manifest"]

        vcs = raw.get("vcs_engine", {})
        topo = raw.get("project_topography", {})

        self.tab_identity.load_data(raw)

        projects_path = vcs.get("local_workspace_root", {}).get(self._current_os(), "")
        if not projects_path:
            projects_path = str(self._workspace_root())

        vault_path = str(self._vault_path())
        self.tab_vault.load_data(projects_path, vault_path)

        active_adapter = vcs.get("active_adapter", "svn")
        repo_url = vcs.get("repository_url", "")
        enable_sparse = vcs.get("enable_vendor_sparse_checkout", True)

        self.tab_vcs.load_data(active_adapter, repo_url, enable_sparse)
        self.tab_topography.load_data(topo)
        self.tab_software.load_data(manifest)

        vcs_username, vcs_enabled = self.vm.load_session_credentials()
        self.tab_credentials.load_data(vcs_username, vcs_enabled)

        self.lbl_unsaved_warning.setText("")

    def _collect_payload(self) -> dict:
        payload = {}
        payload.update(self.tab_identity.identity_payload())
        payload.update(self.tab_vcs.vcs_payload())
        payload.update(self.tab_topography.topography_payload())

        vault_data = self.tab_vault.vault_payload()
        projects_dir = vault_data.get("vcs_engine", {}).get("local_workspace_root", "")

        payload["infrastructure_topology"] = vault_data.get("infrastructure_topology", {})
        payload["vcs_engine"].update({
            "local_workspace_root": {
                "windows": projects_dir,
                "linux": projects_dir,
                "macos": projects_dir,
            }
        })
        return payload

    def _save_configuration(self) -> None:
        if getattr(self.tab_identity, "pending_hero_image_path", None) and self.tab_identity.pending_hero_image_path.exists():
            try:
                dest_path = Path("assets/login_hero.png")
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.tab_identity.pending_hero_image_path, dest_path)
                self.tab_identity.entry_hero_image.clear()
                self.tab_identity.pending_hero_image_path = None
            except Exception as error:  # noqa: BLE001
                self.status_callback(self.tr("⚠️ Failed to apply Hero Image: {0}").format(error), "yellow")

        payload = self._collect_payload()
        software_payload = self.tab_software.software_payload()

        config_ok, vault_ok = self.vm.save(payload, software_payload)

        creds = self.tab_credentials.credentials_payload()
        self.vm.save_session_credentials(creds["username"], creds["password"], creds["enabled"])

        if config_ok and vault_ok:
            self.lbl_unsaved_warning.setText("")
            self.status_callback(self.tr("✓ Local settings and Network Manifest saved successfully. VCS credentials kept in RAM for this session."), "green")
            self._load_current_data()
        else:
            if not config_ok:
                self.status_callback(self.tr("✗ Error writing settings.json"), "red")
            if not vault_ok:
                self.status_callback(self.tr("✗ Error writing vault_manifest.json"), "red")

    def _export_studio_seed(self) -> None:
        payload = self._collect_payload()
        dest_dir = QFileDialog.getExistingDirectory(self, self.tr("Select Destination Directory"), QDir.homePath())
        if dest_dir:
            self.status_callback(self.tr("Encrypting and exporting Studio Seed..."), "yellow")
            success, message = self.vm.export_seed(payload, Path(dest_dir))
            if success:
                self.status_callback(self.tr("✓ Seed exported: {0}").format(message), "green")
            else:
                self.status_callback(self.tr("✗ Export failed: {0}").format(message), "red")

    # Helpers to keep the config-factory reads localized to the widget.
    def _current_os(self) -> str:
        return self.vm.config_factory._get_current_os()

    def _workspace_root(self) -> Path:
        return self.vm.config_factory.get_workspace_root()

    def _vault_path(self) -> Path:
        return self.vm.config_factory.get_vault_path()
