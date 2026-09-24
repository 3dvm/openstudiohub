# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/vcs_credentials_dialog.py
# Architectural role: UI Component / VCS Credentials Gate (PySide6)
# =========================================================================================

"""Modal that requests VCS credentials just before a VCS-backed action.

The values collected here are handed back to the caller and stored exclusively
in the RAM-only ``CredentialVault`` for the target server. Nothing is written to
disk. When the target server is reached over SSH, the dialog also asks for the
key passphrase so provisioning can run unattended.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class VcsCredentialsDialog(QDialog):
    """Blocking prompt for a server's VCS username / password (and passphrase)."""

    def __init__(
        self,
        parent=None,
        default_username: str = "",
        server_label: str = "",
        include_passphrase: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("VCS Credentials Required"))
        self.setFixedSize(460, 300 if not include_passphrase else 380)
        self.setModal(True)
        self.setObjectName("FloatingCard")
        self._include_passphrase = include_passphrase
        self._build_ui(default_username, server_label)

    def _build_ui(self, default_username: str, server_label: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(15)

        lbl_title = QLabel(self.tr("Version Control Credentials"))
        lbl_title.setObjectName("H2Title")
        layout.addWidget(lbl_title)

        if server_label:
            lbl_server = QLabel(self.tr(f"Server: {server_label}"))
            lbl_server.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 13px;")
            layout.addWidget(lbl_server)

        lbl_notice = QLabel(
            self.tr(
                "This action requires access to the version control repository. "
                "Enter the VCS username and password to continue."
            )
        )
        lbl_notice.setWordWrap(True)
        lbl_notice.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(lbl_notice)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.entry_user = QLineEdit(default_username)
        self.entry_user.setObjectName("FormInput")
        self.entry_user.setFixedHeight(35)
        self.entry_user.setPlaceholderText(self.tr("e.g. artist@studio.com"))

        self.entry_pwd = QLineEdit()
        self.entry_pwd.setObjectName("FormInput")
        self.entry_pwd.setFixedHeight(35)
        self.entry_pwd.setEchoMode(QLineEdit.Password)
        self.entry_pwd.setPlaceholderText(self.tr("VCS password"))

        lbl_user = QLabel(self.tr("Username:"))
        lbl_user.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 12px;")
        lbl_pwd = QLabel(self.tr("Password:"))
        lbl_pwd.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 12px;")
        form.addRow(lbl_user, self.entry_user)
        form.addRow(lbl_pwd, self.entry_pwd)

        self.entry_passphrase = None
        if self._include_passphrase:
            self.entry_passphrase = QLineEdit()
            self.entry_passphrase.setObjectName("FormInput")
            self.entry_passphrase.setFixedHeight(35)
            self.entry_passphrase.setEchoMode(QLineEdit.Password)
            self.entry_passphrase.setPlaceholderText(self.tr("optional SSH key passphrase"))
            lbl_pass = QLabel(self.tr("SSH Passphrase:"))
            lbl_pass.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 12px;")
            form.addRow(lbl_pass, self.entry_passphrase)

        layout.addLayout(form)

        lbl_session = QLabel(
            self.tr("Values are kept in RAM only for this session and are never written to disk.")
        )
        lbl_session.setWordWrap(True)
        lbl_session.setStyleSheet("color: #F59E0B; font-size: 11px;")
        layout.addWidget(lbl_session)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton(self.tr("Cancel"))
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.setFixedHeight(35)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_continue = QPushButton(self.tr("Continue"))
        self.btn_continue.setObjectName("PrimaryButton")
        self.btn_continue.setFixedHeight(35)
        self.btn_continue.setCursor(Qt.PointingHandCursor)
        self.btn_continue.setEnabled(False)
        self.btn_continue.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_continue)
        layout.addLayout(btn_layout)

        self.entry_user.textChanged.connect(self._validate)
        self.entry_pwd.textChanged.connect(self._validate)
        self._validate()

    def _validate(self) -> None:
        self.btn_continue.setEnabled(
            bool(self.entry_user.text().strip() and self.entry_pwd.text())
        )

    def credentials(self) -> tuple[str, str]:
        return self.entry_user.text().strip(), self.entry_pwd.text()

    def ssh_passphrase(self) -> str:
        if self.entry_passphrase is None:
            return ""
        return self.entry_passphrase.text()
