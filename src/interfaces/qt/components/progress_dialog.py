# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/progress_dialog.py
# Architectural role: UI Component / Progress Dialog
# =========================================================================================

"""Floating modal that shows the real-time terminal log with reactive buttons."""

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit, QVBoxLayout


class SpawningProgressDialog(QDialog):
    def __init__(self, parent, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(650, 420)
        self.setModal(True)
        self.setObjectName("FloatingCard")

        layout = QVBoxLayout(self)
        self.lbl_status = QLabel(self.tr("Initializing..."))
        self.lbl_status.setObjectName("H2Title")
        layout.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(5)
        layout.addWidget(self.progress)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("TerminalView")
        self.log_output.setObjectName("TerminalView")
        layout.addWidget(self.log_output)

        self.btn_layout = QHBoxLayout()
        self.btn_layout.addStretch()

        self.btn_action = QPushButton("")
        self.btn_action.setObjectName("PrimaryButton")
        self.btn_action.setFixedHeight(35)
        self.btn_action.hide()

        self.btn_close = QPushButton(self.tr("Cancel"))
        self.btn_close.setObjectName("SecondaryButton")
        self.btn_close.setFixedHeight(35)
        self.btn_close.clicked.connect(self.accept)

        self.btn_layout.addWidget(self.btn_action)
        self.btn_layout.addWidget(self.btn_close)
        layout.addLayout(self.btn_layout)

    def update_progress(self, value: int, status_msg: str) -> None:
        if value > 0:
            self.progress.setValue(value)
        if status_msg:
            self.lbl_status.setText(status_msg)

    def append_log(self, text: str) -> None:
        self.log_output.append(text)
        self.log_output.moveCursor(QTextCursor.End)

    def finalize(self, success: bool, main_msg: str, action_text: str = "", action_callback=None) -> None:
        """Transform the modal at completion to audit the log."""
        self.lbl_status.setText(main_msg)
        from src.interfaces.qt.ui_style import set_ui_state
        set_ui_state(self.lbl_status, "success" if success else "error")

        self.btn_close.setText(self.tr("Close Window"))

        if success and action_callback and action_text:
            self.btn_action.setText(action_text)
            self.btn_action.show()
            self.btn_action.clicked.connect(action_callback)

        if success:
            if self.progress.value() < 100:
                self.progress.setValue(100)
        else:
            self.progress.setValue(100)
            self.progress.setObjectName("ErrorProgress")
            self.progress.style().unpolish(self.progress)
            self.progress.style().polish(self.progress)
            self.progress.setFormat(self.tr("Failed"))
            if main_msg:
                self.append_log(f"❌ {main_msg}")
