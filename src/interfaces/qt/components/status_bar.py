# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/status_bar.py
# Architectural role: UI Component / Status Bar
# =========================================================================================

"""Bottom status bar of the Hub."""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar


class StatusBar(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusBar")
        self.setFixedHeight(35)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)

        self.lbl_status = QLabel(self.tr("🟢 Ready."))
        self.lbl_status.setObjectName("StatusText")
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("StatusProgress")
        self.progress_bar.setFixedSize(200, 14)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

    def update_status(self, message: str, color: str = "white") -> None:
        from src.interfaces.qt.ui_style import set_ui_state

        states = {
            "green": "success",
            "yellow": "warning",
            "red": "error",
            "gray": "",
            "white": "",
        }
        self.lbl_status.setText(message)
        set_ui_state(self.lbl_status, states.get(color, ""))

    def set_progress(self, percent: int) -> None:
        """Show ``percent`` (0..100). ``-1`` clears, ``-2`` shows an indeterminate bar."""
        if percent == -1:
            self.progress_bar.reset()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.hide()
            return

        if percent == -2:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.show()
            return

        if not self.progress_bar.isVisible():
            self.progress_bar.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, int(percent))))
