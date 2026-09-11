# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/vcs_credentials_dialog.py
# Architectural role: UI Component / VCS Credentials Gate (PySide6)
# =========================================================================================

"""Modal that requests VCS credentials just before a VCS-backed action.

The values collected here are handed back to the caller through
``credentials()`` and stored exclusively in the RAM-only ``CredentialVault``
(the same mechanism used by the Session Credentials settings tab). Nothing is
written to disk.
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
    """Blocking prompt for the session VCS username / password."""

    def __init__(self, parent=None, default_username: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("VCS Credentials Required"))
        self.setFixedSize(440, 280)
        self.setModal(True)
        self.setObjectName("FloatingCard")
        self._build_ui(default_username)

    def _build_ui(self, default_username: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(15)

        lbl_title = QLabel(self.tr("Version Control Credentials"))
        lbl_title.setObjectName("H2Title")
        layout.addWidget(lbl_title)

        lbl_notice = QLabel(
            self.tr(
                "This action requires access to the version control repository. "
                "Enter your VCS username and password to continue."
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
        layout.addLayout(form)

        lbl_session = QLabel(
            self.tr("The password is kept in RAM only for this session and is never written to disk.")
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
