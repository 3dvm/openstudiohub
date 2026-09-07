# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/status_bar.py
# Architectural role: UI Component / Status Bar
# =========================================================================================

"""Bottom status bar of the Hub."""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel


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

    def update_status(self, message: str, color: str = "white") -> None:
        colors = {"green": "#10B981", "yellow": "#F59E0B", "red": "#EF4444", "gray": "#9CA3AF", "white": "#F8FAFC"}
        text_color = colors.get(color, color)
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet(f"color: {text_color};")
