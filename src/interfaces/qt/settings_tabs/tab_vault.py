# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/settings_tabs/tab_vault.py
# Architectural role: UI Component / Settings Tab
# =========================================================================================

"""Physical storage settings tab (NAS projects directory + immutable vault)."""

from pathlib import Path

from PySide6.QtCore import QDir, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class TabVault(QWidget):
    modified = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._is_loading = True

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        proj_layout = QHBoxLayout()
        self.entry_projects_path = self._create_input(self.tr("e.g. Z:/studio_projects"))
        self.entry_projects_path.setReadOnly(True)
        proj_layout.addWidget(self.entry_projects_path)

        btn_browse_proj = QPushButton(self.tr("Browse..."))
        btn_browse_proj.setObjectName("SecondaryButton")
        btn_browse_proj.setFixedSize(90, 35)
        btn_browse_proj.clicked.connect(self._select_projects)
        proj_layout.addWidget(btn_browse_proj)

        layout.addRow(self._styled_label(self.tr("Projects Directory:")), proj_layout)

        path_layout = QHBoxLayout()
        self.entry_vault_path = self._create_input(self.tr("e.g. Z:/studio_projects/openstudio_vault"))
        self.entry_vault_path.setReadOnly(True)
        path_layout.addWidget(self.entry_vault_path)

        btn_browse_vault = QPushButton(self.tr("Browse..."))
        btn_browse_vault.setObjectName("SecondaryButton")
        btn_browse_vault.setFixedSize(90, 35)
        btn_browse_vault.clicked.connect(self._select_vault)
        path_layout.addWidget(btn_browse_vault)

        layout.addRow(self._styled_label(self.tr("Vault Directory:")), path_layout)

        lbl_desc = QLabel(self.tr("Physical storage paths on the NAS.\nThe Projects Directory holds live production assets, while the Vault contains immutable software components and engine templates."))
        lbl_desc.setStyleSheet("color: #64748B; font-size: 12px;")
        layout.addRow("", lbl_desc)

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
        self.entry_projects_path.textChanged.connect(self._on_field_modified)
        self.entry_vault_path.textChanged.connect(self._on_field_modified)

    def _on_field_modified(self) -> None:
        if not self._is_loading:
            self.modified.emit()

    def _select_projects(self) -> None:
        start_dir = QDir.homePath()
        actual = self.entry_projects_path.text()
        if actual and Path(actual).exists():
            start_dir = actual

        dir_path = QFileDialog.getExistingDirectory(self, self.tr("Select Projects Root Directory"), start_dir)
        if dir_path:
            self.entry_projects_path.setText(dir_path)
            if not self.entry_vault_path.text():
                self.entry_vault_path.setText(str(Path(dir_path) / "openstudio_vault"))

    def _select_vault(self) -> None:
        start_dir = QDir.homePath()
        actual = self.entry_vault_path.text()
        proj_dir = self.entry_projects_path.text()

        if actual and Path(actual).exists():
            start_dir = str(Path(actual).parent)
        elif proj_dir and Path(proj_dir).exists():
            start_dir = proj_dir

        dir_path = QFileDialog.getExistingDirectory(self, self.tr("Select NAS Root (Vault)"), start_dir)
        if dir_path:
            chosen_path = Path(dir_path)
            if chosen_path.name != "openstudio_vault":
                chosen_path = chosen_path / "openstudio_vault"
            self.entry_vault_path.setText(str(chosen_path))

    # ------------------------------------------------------------------
    # PUBLIC API (Data-Down, Actions-Up)
    # ------------------------------------------------------------------
    def load_data(self, projects_path: str, vault_path: str) -> None:
        self._is_loading = True
        self.entry_projects_path.setText(projects_path)
        self.entry_vault_path.setText(vault_path)
        self._is_loading = False

    def vault_payload(self) -> dict:
        return {
            "infrastructure_topology": {
                "vault_path": self.entry_vault_path.text().strip()
            },
            "vcs_engine": {
                "local_workspace_root": self.entry_projects_path.text().strip()
            },
        }
