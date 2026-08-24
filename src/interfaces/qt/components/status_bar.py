# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/components/status_bar.py
# =========================================================================================

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

class StatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusBar")
        self.setFixedHeight(35)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        
        self.lbl_status = QLabel(self.tr("🟢 Ready."))
        self.lbl_status.setObjectName("StatusText")
        layout.addWidget(self.lbl_status)

    def actualizar_status(self, mensaje: str, color: str = "white"):
        colores = {"green": "#10B981", "yellow": "#F59E0B", "red": "#EF4444", "gray": "#9CA3AF", "white": "#F8FAFC"}
        texto_color = colores.get(color, color)
        self.lbl_status.setText(mensaje)
        self.lbl_status.setStyleSheet(f"color: {texto_color};")
