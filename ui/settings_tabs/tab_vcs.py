# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/settings_tabs/tab_vcs.py
# Rol Arquitectónico: UI Component / Settings Tab
# =========================================================================================

#import subprocess
from PySide6.QtWidgets import (QWidget, QLineEdit, QComboBox, QCheckBox, 
                               QFormLayout, QLabel)
from PySide6.QtCore import Qt, Signal

class TabVCS(QWidget):
    modified = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_loading = True
        
        self._build_ui()
        self._conectar_senales()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # 1. MOTOR Y CONEXIÓN BASE
        lbl_section_1 = QLabel(self.tr("Engine & Target Repository"))
        lbl_section_1.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 14px; margin-bottom: 5px;")
        layout.addRow("", lbl_section_1)

        self.combo_vcs = QComboBox()
        self.combo_vcs.addItems(["svn", "git-lfs"])
        self.combo_vcs.setFixedHeight(35)
        self.combo_vcs.setStyleSheet("QComboBox { background-color: #0F172A; border: 1px solid #475569; color: #F8FAFC; border-radius: 6px; padding-left: 10px; }")

        self.entry_repo_url = self._crear_input(self.tr("e.g. svn://localhost"))

        layout.addRow(self._styled_label(self.tr("Active VCS Engine:")), self.combo_vcs)
        layout.addRow(self._styled_label(self.tr("Base Server URL:")), self.entry_repo_url)

        # 2. AUTENTICACIÓN (GUARDADO EN JSON)
        # lbl_section_2 = QLabel(self.tr("Network Auth (Persistent Demo Mode)"))
        # lbl_section_2.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 14px; margin-top: 15px; margin-bottom: 5px;")
        # layout.addRow("", lbl_section_2)
        #
        # self.entry_vcs_user = self._crear_input(self.tr("SVN Username"))
        # self.entry_vcs_pwd = self._crear_input(self.tr("SVN Password"))
        # self.entry_vcs_pwd.setEchoMode(QLineEdit.Password)
        #
        # layout.addRow(self._styled_label(self.tr("SVN/Git Username:")), self.entry_vcs_user)
        # layout.addRow(self._styled_label(self.tr("SVN/Git Password:")), self.entry_vcs_pwd)

        # 3. OPCIONES AVANZADAS Y TESTING
        lbl_section_4 = QLabel(self.tr("Advanced"))
        lbl_section_4.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 14px; margin-top: 15px; margin-bottom: 5px;")
        layout.addRow("", lbl_section_4)

        self.chk_sparse = QCheckBox(self.tr("Enable Jailing (Vendor Sparse Checkout)"))
        self.chk_sparse.setStyleSheet("color: #94A3B8; font-weight: bold;")
        self.chk_sparse.setCursor(Qt.PointingHandCursor)
        layout.addRow("", self.chk_sparse)

        # self.btn_local_docker = QPushButton(self.tr("🐳 Deploy Localhost SVN Server (Docker)"))
        # self.btn_local_docker.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold; border-radius: 6px; border: none;")
        # self.btn_local_docker.setFixedHeight(35)
        # self.btn_local_docker.setCursor(Qt.PointingHandCursor)
        # self.btn_local_docker.clicked.connect(self._desplegar_svn_local)
        # layout.addRow("", self.btn_local_docker)

    def _crear_input(self, placeholder: str = "") -> QLineEdit:
        campo = QLineEdit()
        campo.setObjectName("FormInput")
        campo.setFixedHeight(35)
        campo.setPlaceholderText(placeholder)
        return campo

    def _styled_label(self, texto: str) -> QLabel:
        lbl = QLabel(texto)
        lbl.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 12px;")
        return lbl

    def _conectar_senales(self):
        self.combo_vcs.currentIndexChanged.connect(self._on_field_modified)
        self.entry_repo_url.textChanged.connect(self._on_field_modified)
        # self.entry_vcs_user.textChanged.connect(self._on_field_modified)
        # self.entry_vcs_pwd.textChanged.connect(self._on_field_modified)
        self.chk_sparse.stateChanged.connect(self._on_field_modified)

    def _on_field_modified(self):
        if not self._is_loading:
            self.modified.emit()

    # def _desplegar_svn_local(self):
    #     """Lanza un contenedor Docker con SVN limpio, actuando como Servidor Global."""
    #     self.btn_local_docker.setEnabled(False)
    #     self.btn_local_docker.setText(self.tr("Encendiendo Servidor Docker..."))
    #     QApplication.processEvents()
    #
    #     try:
    #         # Limpieza y Despliegue puro del servidor (Sin repositorios aún)
    #         subprocess.run(["docker", "rm", "-f", "openstudio_local_svn"], capture_output=True)
    #         subprocess.run(["docker", "run", "-d", "--name", "openstudio_local_svn", "-p", "3690:3690", "elleflorio/svn-server"], check=True)
    #
    #         QMessageBox.information(
    #             self, "Servidor Activo", 
    #             "¡El servidor SVN global está corriendo en Docker!\n\n"
    #             "Haz clic en 'Save Local Changes' para guardar las credenciales en el sistema."
    #         )
    #
    #         # Auto-completar el formulario para el usuario
    #         self.entry_repo_url.setText("svn://localhost")
    #         self.entry_vcs_user.setText("admin")
    #         self.entry_vcs_pwd.setText("admin123")
    #         self._on_field_modified()
    #
    #     except FileNotFoundError:
    #         QMessageBox.critical(self, "Error Fatal", "Docker no está instalado.")
    #     except subprocess.CalledProcessError as e:
    #         QMessageBox.warning(self, "Error Docker", f"Fallo en ejecución:\n{e}")
    #     finally:
    #         self.btn_local_docker.setEnabled(True)
    #         self.btn_local_docker.setText(self.tr("🐳 Deploy Localhost SVN Server (Docker)"))
    #
    def cargar_datos(self, active_adapter: str, repo_url: str, enable_sparse: bool, user: str = "", pwd: str = "", ssh_key: str = "", ssh_pwd: str = ""):
         self._is_loading = True
         idx = self.combo_vcs.findText(active_adapter)
         if idx >= 0: self.combo_vcs.setCurrentIndex(idx)
         self.entry_repo_url.setText(repo_url)
         self.chk_sparse.setChecked(enable_sparse)
    #     self.entry_vcs_user.setText(user)
    #     self.entry_vcs_pwd.setText(pwd)
         self._is_loading = False
    #
    def get_vcs_payload(self) -> dict:
        return {
            "vcs_engine": {
                "active_adapter": self.combo_vcs.currentText(),
                "repository_url": self.entry_repo_url.text().strip(),
                "enable_vendor_sparse_checkout": self.chk_sparse.isChecked(),
    #             "vcs_username": self.entry_vcs_user.text().strip(),
    #             "vcs_password": self.entry_vcs_pwd.text().strip()
            }
        }
