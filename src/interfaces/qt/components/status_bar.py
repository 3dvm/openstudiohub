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
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #334155; border-radius: 6px; background-color: #1F2531;"
            " color: #F8FAFC; font-size: 10px; text-align: center; }"
            "QProgressBar::chunk { background-color: #F97316; border-radius: 5px; }"
        )
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

    def update_status(self, message: str, color: str = "white") -> None:
        colors = {"green": "#10B981", "yellow": "#F59E0B", "red": "#EF4444", "gray": "#9CA3AF", "white": "#F8FAFC"}
        text_color = colors.get(color, color)
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet(f"color: {text_color};")

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
