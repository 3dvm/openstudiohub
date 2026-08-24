from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QTextEdit, QPushButton
from PySide6.QtGui import QTextCursor

class SpawningProgressDialog(QDialog):
    """Modal flotante que muestra el log de terminal en tiempo real con botones reactivos."""
    def __init__(self, parent, title: str):
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
        self.log_output.setObjectName("FormInput")
        self.log_output.setStyleSheet("font-family: monospace; font-size: 12px; color: #94A3B8; background-color: #0F172A;")
        layout.addWidget(self.log_output)
        
        # --- Botonera Dinámica Inferior ---
        self.btn_layout = QHBoxLayout()
        self.btn_layout.addStretch()
        
        self.btn_action = QPushButton("")
        self.btn_action.setObjectName("PrimaryButton")
        self.btn_action.setFixedHeight(35)
        self.btn_action.hide() # Oculto por defecto
        
        self.btn_close = QPushButton(self.tr("Cancel"))
        self.btn_close.setObjectName("SecondaryButton")
        self.btn_close.setFixedHeight(35)
        self.btn_close.clicked.connect(self.accept)
        
        self.btn_layout.addWidget(self.btn_action)
        self.btn_layout.addWidget(self.btn_close)
        layout.addLayout(self.btn_layout)
        
    def update_progress(self, value: int, status_msg: str):
        if value > 0: self.progress.setValue(value)
        if status_msg: self.lbl_status.setText(status_msg)
        
    def append_log(self, text: str):
        self.log_output.append(text)
        self.log_output.moveCursor(QTextCursor.End)
        
    def finalize(self, success: bool, main_msg: str, action_text: str = "", action_callback = None):
        """Transforma el modal al terminar el proceso para auditar el log."""
        self.lbl_status.setText(main_msg)
        self.lbl_status.setStyleSheet("color: #10B981;" if success else "color: #EF4444;")
        
        self.btn_close.setText(self.tr("Close Window"))
        self.btn_close.setStyleSheet("background-color: #334155;")
        
        if success and action_callback and action_text:
            self.btn_action.setText(action_text)
            self.btn_action.show()
            self.btn_action.clicked.connect(action_callback)
            
        # Si falló, la barra se pone roja
        if not success:
            self.progress.setStyleSheet("QProgressBar::chunk { background-color: #EF4444; }")
