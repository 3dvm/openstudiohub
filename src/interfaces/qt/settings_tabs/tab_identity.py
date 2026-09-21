# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/settings_tabs/tab_identity.py
# Architectural role: UI Component / Settings Tab
# =========================================================================================

"""Studio identity and API settings tab.

Encapsulates the UI and the asynchronous Kitsu identity sync, exposing clean
hydration (load_data) and payload extraction (identity_payload) methods.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal

from src.infrastructure.qt_worker import ManagedWorker
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from src.application.services.auth_service import AuthService
from src.application.services.production_service import ProductionService


class SyncIdentityWorker(ManagedWorker):
    """Fetches the organisation metadata from Kitsu asynchronously."""

    finished_sync = Signal(dict)

    def __init__(self, production_service: ProductionService) -> None:
        super().__init__()
        self.production_service = production_service

    def run(self) -> None:
        identity_data = self.production_service.sync_studio_identity()
        self.finished_sync.emit(identity_data)


class TabIdentity(QWidget):
    # Notifies the parent orchestrator that there are unsaved changes.
    modified = Signal()

    def __init__(self, auth_service: AuthService, production_service: ProductionService, status_callback, parent=None) -> None:
        super().__init__(parent)
        self.auth_service = auth_service
        self.production_service = production_service
        self.status_callback = status_callback

        self._is_loading = True
        self.pending_hero_image_path = None

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        name_layout = QHBoxLayout()
        self.entry_studio_name = self._create_input(self.tr("e.g. Macuare Studio"))
        name_layout.addWidget(self.entry_studio_name)

        self.btn_sync_identity = QPushButton(self.tr("Sync from Kitsu"))
        self.btn_sync_identity.setObjectName("SecondaryButton")
        self.btn_sync_identity.setFixedSize(130, 35)
        self.btn_sync_identity.setCursor(Qt.PointingHandCursor)
        self.btn_sync_identity.clicked.connect(self._run_identity_sync)
        name_layout.addWidget(self.btn_sync_identity)

        self.entry_kitsu_url = self._create_input(self.tr("e.g. https://kitsu.mydomain.com/api"))

        hero_layout = QHBoxLayout()
        self.entry_hero_image = self._create_input(self.tr("Select a PNG/JPG for the login background"))
        self.entry_hero_image.setReadOnly(True)
        hero_layout.addWidget(self.entry_hero_image)

        btn_browse_hero = QPushButton(self.tr("Browse..."))
        btn_browse_hero.setObjectName("SecondaryButton")
        btn_browse_hero.setFixedSize(90, 35)
        btn_browse_hero.clicked.connect(self._select_hero_image)
        hero_layout.addWidget(btn_browse_hero)

        layout.addRow(self._styled_label(self.tr("Studio Name:")), name_layout)
        layout.addRow(self._styled_label(self.tr("Kitsu API URL:")), self.entry_kitsu_url)
        layout.addRow(self._styled_label(self.tr("Studio Hero Image:")), hero_layout)

    def _create_input(self, placeholder: str = "") -> QLineEdit:
        field = QLineEdit()
        field.setObjectName("FormInput")
        field.setFixedHeight(35)
        field.setPlaceholderText(placeholder)
        return field

    def _styled_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 13px;")
        return label

    def _connect_signals(self) -> None:
        self.entry_studio_name.textChanged.connect(self._on_field_modified)
        self.entry_kitsu_url.textChanged.connect(self._on_field_modified)

    def _on_field_modified(self) -> None:
        if not self._is_loading:
            self.modified.emit()

    def _select_hero_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select Studio Hero Image"), "", self.tr("Images (*.png *.jpg *.jpeg)")
        )
        if file_path:
            self.entry_hero_image.setText(file_path)
            self.pending_hero_image_path = Path(file_path)
            self._on_field_modified()

    def _run_identity_sync(self) -> None:
        self.btn_sync_identity.setEnabled(False)
        self.btn_sync_identity.setText(self.tr("Syncing..."))
        self.status_callback(self.tr("Connecting to Kitsu to pull production profile..."), "yellow")

        url = self.entry_kitsu_url.text().strip()
        if url:
            self.auth_service.set_host(url)

        self.sync_worker = SyncIdentityWorker(self.production_service)
        self.sync_worker.finished_sync.connect(self._on_sync_finished)
        self.sync_worker.finished.connect(self.sync_worker.deleteLater)
        self.sync_worker.start()

    def _on_sync_finished(self, identity_data: dict) -> None:
        self.btn_sync_identity.setEnabled(True)
        self.btn_sync_identity.setText(self.tr("Sync from Kitsu"))

        if identity_data and "name" in identity_data:
            self.entry_studio_name.setText(identity_data["name"])
            self.status_callback(self.tr("✓ Studio identity synchronized from Kitsu successfully."), "green")
        else:
            self.status_callback(self.tr("✗ Failed to sync identity. Verify API URL or network connection."), "red")

    # ------------------------------------------------------------------
    # PUBLIC API (Data-Down, Actions-Up)
    # ------------------------------------------------------------------
    def load_data(self, raw_config: dict) -> None:
        self._is_loading = True
        self.entry_studio_name.setText(raw_config.get("studio_profile", {}).get("name", ""))
        self.entry_kitsu_url.setText(raw_config.get("kitsu_production", {}).get("api_url", ""))
        self._is_loading = False

    def identity_payload(self) -> dict:
        return {
            "studio_profile": {
                "name": self.entry_studio_name.text().strip()
            },
            "kitsu_production": {
                "api_url": self.entry_kitsu_url.text().strip()
            },
        }
