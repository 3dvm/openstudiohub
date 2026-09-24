# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/settings_tabs/tab_credentials.py
# Architectural role: UI Component / Session Credentials (RAM-only, per server)
# =========================================================================================

"""Session-scoped, per-server VCS credentials widget.

Unlike the other settings tabs, this widget never persists anything to
``settings.json``. The values it collects are handed back via
``credentials_payload()`` and stored exclusively in the RAM-only
``CredentialVault``, keyed by the selected server. Passwords are therefore valid
for a single session only.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)


class TabCredentials(QWidget):
    modified = Signal()
    server_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._is_loading = True

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        lbl_section = QLabel(self.tr("Session VCS Credentials"))
        lbl_section.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 14px; margin-bottom: 5px;")
        layout.addRow("", lbl_section)

        self.combo_server = QComboBox()
        self.combo_server.setObjectName("FormInput")
        self.combo_server.setFixedHeight(35)

        self.entry_vcs_user = self._create_input(self.tr("e.g. artist@studio.com"))
        self.entry_vcs_pwd = self._create_input(self.tr("VCS password"))
        self.entry_vcs_pwd.setEchoMode(QLineEdit.Password)
        self.entry_ssh_pass = self._create_input(self.tr("optional SSH key passphrase"))
        self.entry_ssh_pass.setEchoMode(QLineEdit.Password)

        layout.addRow(self._styled_label(self.tr("Server:")), self.combo_server)
        layout.addRow(self._styled_label(self.tr("VCS Username:")), self.entry_vcs_user)
        layout.addRow(self._styled_label(self.tr("VCS Password:")), self.entry_vcs_pwd)
        layout.addRow(self._styled_label(self.tr("SSH Passphrase:")), self.entry_ssh_pass)

        self.chk_vcs_enabled = QCheckBox(self.tr("Enable VCS for this session"))
        self.chk_vcs_enabled.setStyleSheet("color: #94A3B8; font-weight: bold;")
        self.chk_vcs_enabled.setCursor(Qt.PointingHandCursor)
        layout.addRow("", self.chk_vcs_enabled)

        self.lbl_notice = QLabel(
            self.tr("Credentials are kept in RAM only for this session and are never written to disk.")
        )
        self.lbl_notice.setStyleSheet("color: #F59E0B; font-size: 12px;")
        self.lbl_notice.setWordWrap(True)
        layout.addRow("", self.lbl_notice)

    def _create_input(self, placeholder: str = "") -> QLineEdit:
        field = QLineEdit()
        field.setObjectName("FormInput")
        field.setFixedHeight(35)
        field.setPlaceholderText(placeholder)
        return field

    def _styled_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 12px;")
        return label

    def _connect_signals(self) -> None:
        self.combo_server.currentIndexChanged.connect(self._on_server_changed)
        self.entry_vcs_user.textChanged.connect(self._on_field_modified)
        self.entry_vcs_pwd.textChanged.connect(self._on_field_modified)
        self.entry_ssh_pass.textChanged.connect(self._on_field_modified)
        self.chk_vcs_enabled.stateChanged.connect(self._on_field_modified)

    def _on_server_changed(self, _index: int) -> None:
        if not self._is_loading:
            self.server_changed.emit(self.current_server_id())

    def _on_field_modified(self) -> None:
        if not self._is_loading:
            self.modified.emit()

    # ------------------------------------------------------------------
    # PUBLIC API (Data-Down, Actions-Up)
    # ------------------------------------------------------------------
    def set_servers(self, servers: list, selected_id: str = "") -> None:
        """Populate the server dropdown. ``servers`` is a list of server dicts."""
        self._is_loading = True
        self.combo_server.blockSignals(True)
        self.combo_server.clear()
        for server in servers:
            label = server.get("name", server.get("id", "Server"))
            if server.get("is_default"):
                label += self.tr("  (default)")
            self.combo_server.addItem(label, server.get("id", ""))
        index = self.combo_server.findData(selected_id)
        if index >= 0:
            self.combo_server.setCurrentIndex(index)
        elif self.combo_server.count():
            self.combo_server.setCurrentIndex(0)
        self.combo_server.blockSignals(False)
        self._is_loading = False

    def current_server_id(self) -> str:
        return self.combo_server.currentData() or ""

    def load_data(self, username: str = "", enabled: bool = False, ssh_passphrase_present: bool = False) -> None:
        self._is_loading = True
        self.entry_vcs_user.setText(username)
        self.entry_vcs_pwd.clear()
        self.entry_ssh_pass.clear()
        self.entry_ssh_pass.setPlaceholderText(
            self.tr("SSH passphrase already set for this session")
            if ssh_passphrase_present
            else self.tr("optional SSH key passphrase")
        )
        self.chk_vcs_enabled.setChecked(enabled)
        self._is_loading = False

    def credentials_payload(self) -> dict:
        return {
            "server_id": self.current_server_id(),
            "username": self.entry_vcs_user.text().strip(),
            "password": self.entry_vcs_pwd.text(),
            "enabled": self.chk_vcs_enabled.isChecked(),
            "ssh_passphrase": self.entry_ssh_pass.text(),
        }
