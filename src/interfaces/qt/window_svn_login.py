# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/window_svn_login.py
# Rol Arquitectónico: UI View / Modal Dialog (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.6.1
# =========================================================================================

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QWidget
from PySide6.QtCore import Qt
from typing import Callable
from src.application.vault_manager import VaultManager

class SVNLoginWindow(QDialog):
    def __init__(self, parent: QWidget, vault_manager: VaultManager, on_success_callback: Callable[[], None]):
        """Ventana modal Just-In-Time para solicitar credenciales del Repositorio VCS."""
        super().__init__(parent)
        
        self.setWindowTitle("Autenticación de Repositorio (VCS)")
        self.setFixedSize(350, 250)
        
        # Modal constraints (Forzar foco para bloquear la UI principal)
        self.setModal(True)

        self.vault_manager = vault_manager
        self.on_success_callback = on_success_callback
        
        self.setObjectName("ViewLoginBase") # Reusar el fondo oscuro corporativo del QSS

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(15)

        self.lbl_info = QLabel("Se requieren credenciales del Repositorio\npara sincronizar el entorno.")
        self.lbl_info.setAlignment(Qt.AlignCenter)
        self.lbl_info.setStyleSheet("color: #F59E0B;") # Ámbar de advertencia
        layout.addWidget(self.lbl_info)

        self.entry_user = QLineEdit()
        self.entry_user.setObjectName("FormInput")
        self.entry_user.setPlaceholderText("Usuario (VCS)")
        self.entry_user.setFixedHeight(40)
        layout.addWidget(self.entry_user)

        self.entry_pwd = QLineEdit()
        self.entry_pwd.setObjectName("FormInput")
        self.entry_pwd.setPlaceholderText("Contraseña")
        self.entry_pwd.setEchoMode(QLineEdit.Password)
        self.entry_pwd.setFixedHeight(40)
        layout.addWidget(self.entry_pwd)

        self.btn_login = QPushButton("Continuar Sincronización")
        self.btn_login.setObjectName("PrimaryButton")
        self.btn_login.setFixedHeight(45)
        self.btn_login.setCursor(Qt.PointingHandCursor)
        self.btn_login.clicked.connect(self.ejecutar_login)
        layout.addWidget(self.btn_login)

    def ejecutar_login(self) -> None:
        """Valida los campos, guarda en la bóveda RAM y reanuda el proceso en pausa."""
        user = self.entry_user.text().strip()
        pwd = self.entry_pwd.text()

        if not user or not pwd:
            self.lbl_info.setText("Ambos campos son obligatorios.")
            self.lbl_info.setStyleSheet("color: #EF4444; font-weight: bold;")
            return

        # Zero-Disk Passwords: Guardar estrictamente en RAM
        self.vault_manager.save_svn_credentials(user, pwd)
        
        self.close()
        # Retomamos el hilo o la función que había invocado esta modal
        self.on_success_callback()
