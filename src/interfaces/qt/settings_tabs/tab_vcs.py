# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/settings_tabs/tab_vcs.py
# Architectural role: UI Component / Settings Tab
# =========================================================================================

"""Pipeline and VCS settings tab."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit, QWidget


class TabVCS(QWidget):
    modified = Signal()

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

        lbl_section_1 = QLabel(self.tr("Engine & Target Repository"))
        lbl_section_1.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 14px; margin-bottom: 5px;")
        layout.addRow("", lbl_section_1)

        self.combo_vcs = QComboBox()
        self.combo_vcs.addItems(["svn", "git-lfs"])
        self.combo_vcs.setFixedHeight(35)
        self.combo_vcs.setStyleSheet("QComboBox { background-color: #0F172A; border: 1px solid #475569; color: #F8FAFC; border-radius: 6px; padding-left: 10px; }")

        self.entry_repo_url = self._create_input(self.tr("e.g. svn://localhost"))

        layout.addRow(self._styled_label(self.tr("Active VCS Engine:")), self.combo_vcs)
        layout.addRow(self._styled_label(self.tr("Base Server URL:")), self.entry_repo_url)

        lbl_section_4 = QLabel(self.tr("Advanced"))
        lbl_section_4.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 14px; margin-top: 15px; margin-bottom: 5px;")
        layout.addRow("", lbl_section_4)

        self.chk_sparse = QCheckBox(self.tr("Enable Jailing (Vendor Sparse Checkout)"))
        self.chk_sparse.setStyleSheet("color: #94A3B8; font-weight: bold;")
        self.chk_sparse.setCursor(Qt.PointingHandCursor)
        layout.addRow("", self.chk_sparse)

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
        self.combo_vcs.currentIndexChanged.connect(self._on_field_modified)
        self.entry_repo_url.textChanged.connect(self._on_field_modified)
        self.chk_sparse.stateChanged.connect(self._on_field_modified)

    def _on_field_modified(self) -> None:
        if not self._is_loading:
            self.modified.emit()

    def load_data(self, active_adapter: str, repo_url: str, enable_sparse: bool, user: str = "", pwd: str = "", ssh_key: str = "", ssh_pwd: str = "") -> None:
        self._is_loading = True
        idx = self.combo_vcs.findText(active_adapter)
        if idx >= 0:
            self.combo_vcs.setCurrentIndex(idx)
        self.entry_repo_url.setText(repo_url)
        self.chk_sparse.setChecked(enable_sparse)
        self._is_loading = False

    def vcs_payload(self) -> dict:
        return {
            "vcs_engine": {
                "active_adapter": self.combo_vcs.currentText(),
                "repository_url": self.entry_repo_url.text().strip(),
                "enable_vendor_sparse_checkout": self.chk_sparse.isChecked(),
            }
        }
