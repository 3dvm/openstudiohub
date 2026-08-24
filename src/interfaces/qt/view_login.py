# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/view_login.py
# Rol Arquitectónico: UI View / Authentication (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.7.1
# =========================================================================================

"""
Vista principal para el inicio de sesión del usuario.
Implementa la lógica del Día 0 (Importación de Studio Seed) y Día 1+ (Read-Only).
Oculta la destrucción de caché detrás de un QDialog modal accesible desde la Top Bar.
Utiliza internacionalización nativa de Qt (i18n) a través de self.tr().
"""

from _version import __version__

from pathlib import Path

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                               QLabel, QLineEdit, QPushButton, QFileDialog, 
                               QMessageBox, QDialog)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QPainter

class HeroImageWidget(QWidget):
    """
    Widget personalizado que dibuja una imagen de fondo comportándose como
    'object-fit: cover' en CSS. Mantiene la relación de aspecto y recorta el excedente.
    """
    def __init__(self, image_path: Path):
        super().__init__()
        self.pixmap = QPixmap(str(image_path))
        self.setObjectName("HeroPanel")

    def paintEvent(self, event):
        if self.pixmap.isNull():
            return super().paintEvent(event)
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        rect = self.rect()
        
        scaled_pixmap = self.pixmap.scaled(
            rect.size(), 
            Qt.KeepAspectRatioByExpanding, 
            Qt.SmoothTransformation
        )
        
        x_offset = (scaled_pixmap.width() - rect.width()) // 2
        y_offset = (scaled_pixmap.height() - rect.height()) // 2
        
        painter.drawPixmap(0, 0, scaled_pixmap, x_offset, y_offset, rect.width(), rect.height())


class LoginSettingsDialog(QDialog):
    """Modal de configuración avanzada para el manejo del Studio Seed local."""
    def __init__(self, parent, config_factory, on_clear_callback):
        super().__init__(parent)
        self.config_factory = config_factory
        self.on_clear_callback = on_clear_callback
        
        self.setWindowTitle(self.tr("Login Settings"))
        self.setFixedSize(320, 160)
        self.setStyleSheet("""
            QDialog { background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; }
            QLabel { color: #F8FAFC; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        lbl_title = QLabel(self.tr("Advanced Configuration"))
        lbl_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(lbl_title)
        
        lbl_desc = QLabel(self.tr("Delete the active Studio Seed to load a new one. This action reverts the application to Day 0."))
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 11px;")
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)
        
        layout.addStretch()
        
        btn_clear = QPushButton(self.tr("Clear Local Configuration"))
        btn_clear.setStyleSheet("background-color: #EF4444; color: white; font-weight: bold; border-radius: 4px; padding: 8px; border: none;")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.clicked.connect(self._confirm_clear)
        layout.addWidget(btn_clear)

    def _confirm_clear(self):
        reply = QMessageBox.question(
            self, 
            self.tr("Clear Configuration"), 
            self.tr("Are you sure you want to delete the local configuration?\nAll connection paths will be lost."),
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            exito = self.config_factory.purgar_configuracion_local()
            self.on_clear_callback(exito)
            self.accept()


class LoginWorker(QThread):
    success = Signal()
    error = Signal(str)

    def __init__(self, auth_manager, email, password, host):
        super().__init__()
        self.auth_manager = auth_manager
        self.email = email
        self.password = password
        self.host = host

    def run(self):
        exito, mensaje = self.auth_manager.login_with_credentials(self.email, self.password, self.host)
        if exito:
            self.success.emit()
        else:
            self.error.emit(mensaje)


class ViewLogin(QWidget):
    def __init__(self, parent, auth_manager, vault_manager, config_factory, on_login_success):
        super().__init__(parent)
        
        self.auth_manager = auth_manager
        self.vault_manager = vault_manager
        self.config_factory = config_factory
        self.on_login_success = on_login_success
        
        self.setObjectName("ViewLoginBase")

        self._build_ui()
        self._refresh_config_state()

    def _set_icon_or_fallback(self, label: QLabel, icon_name: str, color_hex: str, size: int, fallback_text: str):
        """Helper para teñir SVG al vuelo en memoria RAM. Evita emojis asincronizados."""
        icon_path = Path(f"assets/icons/{icon_name}")
        if not icon_path.exists():
            label.setText(fallback_text)
            label.setStyleSheet(f"color: {color_hex};")
            return
            
        try:
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            svg_content = svg_content.replace('currentColor', color_hex)
            svg_content = svg_content.replace('#000000', color_hex)
            svg_content = svg_content.replace('#000"', f'{color_hex}"')
            svg_content = svg_content.replace("#000'", f"{color_hex}'")
            
            pixmap = QPixmap()
            pixmap.loadFromData(svg_content.encode('utf-8'), "SVG")
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaledToHeight(size, Qt.SmoothTransformation))
                label.setText("") 
            else:
                label.setText(fallback_text)
        except Exception:
            label.setText(fallback_text)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---------------------------------------------------------
        # BARRA SUPERIOR (BRANDING & TOP BAR)
        # ---------------------------------------------------------
        self.top_bar = QFrame(self)
        self.top_bar.setObjectName("TopBar")
        self.top_bar.setFixedHeight(65)
        
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(30, 10, 30, 10)
        top_layout.setSpacing(15)
        
        self.logo_icon = QLabel()
        logo_path = Path("assets/logo_topbar.png")
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            self.logo_icon.setPixmap(pixmap.scaledToHeight(40, Qt.SmoothTransformation))
        top_layout.addWidget(self.logo_icon)
        
        self.top_separator = QFrame()
        self.top_separator.setObjectName("TopSeparator")
        self.top_separator.setFixedSize(2, 24)
        top_layout.addWidget(self.top_separator)
        
        self.lbl_title = QLabel("OpenStudioHub")
        self.lbl_title.setObjectName("H1Title")
        top_layout.addWidget(self.lbl_title)

        top_layout.addStretch()

        # self.avatar_icon = QLabel()
        # self._set_icon_or_fallback(self.avatar_icon, "user.svg", "#94A3B8", 20, "👤")
        # self.avatar_icon.setObjectName("AvatarIcon")
        # self.avatar_icon.setAlignment(Qt.AlignCenter)
        # self.avatar_icon.setFixedSize(35, 35)
        # top_layout.addWidget(self.avatar_icon)

        # Reemplazo de la campana por Configuración (Engranaje)
        self.settings_icon = QLabel()
        self._set_icon_or_fallback(self.settings_icon, "settings.svg", "#64748B", 22, "⚙️")
        self.settings_icon.setContentsMargins(10, 0, 15, 0)
        self.settings_icon.setCursor(Qt.PointingHandCursor)
        self.settings_icon.mousePressEvent = self._abrir_modal_settings
        top_layout.addWidget(self.settings_icon)

        # self.conn_icon = QLabel()
        # self._set_icon_or_fallback(self.conn_icon, "server.svg", "#3B82F6", 14, "🔵")
        # top_layout.addWidget(self.conn_icon)

        # self.lbl_connected = QLabel(self.tr("Connected"))
        # self.lbl_connected.setStyleSheet("color: #3B82F6; font-size: 13px; font-weight: bold;")
        # top_layout.addWidget(self.lbl_connected)

        main_layout.addWidget(self.top_bar)

        # ---------------------------------------------------------
        # ÁREA CENTRAL: SPLIT SCREEN
        # ---------------------------------------------------------
        self.split_area = QFrame(self)
        split_layout = QHBoxLayout(self.split_area)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(0)
        
        # --- PANEL IZQUIERDO (FORMULARIO DE LOGIN) ---
        self.left_panel = QFrame()
        self.left_panel.setObjectName("LoginPanel")
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setAlignment(Qt.AlignCenter)
        left_layout.setContentsMargins(40, 20, 40, 20)
        
        self.form_container = QFrame(self.left_panel)
        self.form_container.setMaximumWidth(400)
        form_layout = QVBoxLayout(self.form_container)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(8)
        
        self.lbl_card_title = QLabel(self.tr("Welcome to OpenStudioHub"))
        self.lbl_card_title.setObjectName("CardTitle")
        self.lbl_card_title.setStyleSheet("margin-bottom: 30px;")
        form_layout.addWidget(self.lbl_card_title)

        # Campos de entrada limpios (Sin el botón destructivo)
        lbl_host = QLabel(self.tr("Server URL"))
        lbl_host.setObjectName("InputLabel")
        form_layout.addWidget(lbl_host)
        
        self.entry_host = QLineEdit()
        self.entry_host.setPlaceholderText(self.tr("e.g., https://kitsu.studio.com"))
        self.entry_host.setObjectName("FormInput")
        self.entry_host.setFixedHeight(45)
        form_layout.addWidget(self.entry_host)
        
        form_layout.addSpacing(10)

        lbl_email = QLabel(self.tr("Email Address"))
        lbl_email.setObjectName("InputLabel")
        form_layout.addWidget(lbl_email)
        
        self.entry_email = QLineEdit()
        self.entry_email.setPlaceholderText(self.tr("Email Address"))
        self.entry_email.setObjectName("FormInput")
        self.entry_email.setFixedHeight(45)
        form_layout.addWidget(self.entry_email)

        form_layout.addSpacing(10)

        lbl_pwd = QLabel(self.tr("Password"))
        lbl_pwd.setObjectName("InputLabel")
        form_layout.addWidget(lbl_pwd)
        
        self.entry_password = QLineEdit()
        self.entry_password.setPlaceholderText(self.tr("Password"))
        self.entry_password.setObjectName("FormInput")
        self.entry_password.setEchoMode(QLineEdit.Password)
        self.entry_password.setFixedHeight(45)
        form_layout.addWidget(self.entry_password)

        self.lbl_error = QLabel("")
        self.lbl_error.setObjectName("ErrorLabel")
        self.lbl_error.hide()
        form_layout.addWidget(self.lbl_error)

        form_layout.addSpacing(20)

        # Botones de Acción
        self.btn_login = QPushButton(self.tr("Log In"))
        self.btn_login.setObjectName("PrimaryButton")
        self.btn_login.setFixedHeight(50)
        self.btn_login.setCursor(Qt.PointingHandCursor)
        self.btn_login.clicked.connect(self.ejecutar_login)
        form_layout.addWidget(self.btn_login)

        self.btn_import_seed = QPushButton(self.tr("Import Studio Seed (.seed)"))
        self.btn_import_seed.setObjectName("SecondaryButton")
        self.btn_import_seed.setFixedHeight(40)
        self.btn_import_seed.setCursor(Qt.PointingHandCursor)
        self.btn_import_seed.clicked.connect(self._importar_semilla)
        form_layout.addWidget(self.btn_import_seed)

        # Links secundarios
        links_layout = QHBoxLayout()
        links_layout.setContentsMargins(0, 15, 0, 0)
        
        self.btn_forgot = QPushButton(self.tr("Forgot Password?"))
        self.btn_forgot.setObjectName("LinkButton")
        self.btn_forgot.setCursor(Qt.PointingHandCursor)
        self.btn_forgot.setFlat(True)
        links_layout.addWidget(self.btn_forgot, alignment=Qt.AlignLeft)
        
        lbl_version = QLabel(f"Version {__version__}")
        lbl_version.setStyleSheet("color: #64748B; font-size: 11px;")
        links_layout.addWidget(lbl_version, alignment=Qt.AlignRight)
        
        form_layout.addLayout(links_layout)
        left_layout.addWidget(self.form_container)
        
        split_layout.addWidget(self.left_panel, stretch=1)

        # --- PANEL DERECHO ---
        hero_path = Path("assets/login_hero.png")
        if not hero_path.exists():
            hero_path = Path("assets/login_hero.jpg")
            
        self.right_panel = HeroImageWidget(hero_path)
        split_layout.addWidget(self.right_panel, stretch=1)

        main_layout.addWidget(self.split_area, stretch=1)

        # ---------------------------------------------------------
        # BARRA DE ESTADO
        # ---------------------------------------------------------
        self.status_bar = QFrame(self)
        self.status_bar.setObjectName("StatusBar")
        self.status_bar.setFixedHeight(25)
        
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(15, 0, 15, 0)

        self.status_icon = QLabel()
        self._set_icon_or_fallback(self.status_icon, "server.svg", "#10B981", 12, "🟢")
        status_layout.addWidget(self.status_icon)

        self.lbl_status = QLabel(self.tr("SYSTEM: ONLINE   |   WAITING FOR CREDENTIALS"))
        self.lbl_status.setObjectName("StatusText")
        status_layout.addWidget(self.lbl_status)
        
        status_layout.addStretch()

        main_layout.addWidget(self.status_bar)

    # ---------------------------------------------------------
    # STUDIO SEED LOGIC (DÍA 0 vs DÍA 1+)
    # ---------------------------------------------------------
    def _refresh_config_state(self):
        kitsu_url = self.config_factory.get_kitsu_api_url()
        has_config = bool(kitsu_url)

        if has_config:
            self.entry_host.setText(kitsu_url)
            self.entry_host.setReadOnly(True)
            self.entry_host.setStyleSheet("background-color: #0F172A; color: #64748B; border: 1px solid #1E293B;")
            self.btn_import_seed.hide()
            self.settings_icon.show()
        else:
            self.entry_host.clear()
            self.entry_host.setReadOnly(False)
            self.entry_host.setStyleSheet("")
            self.btn_import_seed.show()
            self.settings_icon.hide()

    def _abrir_modal_settings(self, event):
        dialog = LoginSettingsDialog(self, self.config_factory, self._on_config_cleared)
        dialog.exec()

    def _on_config_cleared(self, exito: bool):
        self._refresh_config_state()
        if exito:
            self._on_login_error(self.tr("✓ Local configuration cleared."))
            self.lbl_error.setStyleSheet("color: #10B981;")
        else:
            self._on_login_error(self.tr("✗ Could not delete configuration file."))
            self.lbl_error.setStyleSheet("color: #EF4444;")

    def _importar_semilla(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select Studio Seed File"), "", self.tr("Seed Files (*.seed);;All Files (*)")
        )
        if file_path:
            exito = self.config_factory.importar_semilla(Path(file_path))
            if exito:
                self._refresh_config_state()
                self._on_login_error(self.tr("✓ Configuration imported successfully. You can now log in."))
                self.lbl_error.setStyleSheet("color: #10B981;")
            else:
                self._on_login_error(self.tr("✗ Failed to load the Seed. The file might be corrupted."))
                self.lbl_error.setStyleSheet("color: #EF4444;")

    # ---------------------------------------------------------
    # AUTHENTICATION
    # ---------------------------------------------------------
    def ejecutar_login(self):
        email = self.entry_email.text().strip()
        password = self.entry_password.text().strip()
        host = self.entry_host.text().strip()

        self.lbl_error.hide()
        self.lbl_error.setStyleSheet("color: #EF4444;")
        
        if not email or not password or not host:
            self.lbl_error.setText(self.tr("Please fill all the required fields."))
            self.lbl_error.show()
            return

        self.btn_login.setEnabled(False)
        self.btn_login.setText(self.tr("Connecting to Server..."))
        
        self._set_icon_or_fallback(self.status_icon, "server.svg", "#F59E0B", 12, "🟠")
        self.lbl_status.setText(self.tr("SYSTEM: AUTHENTICATING... PLEASE WAIT."))

        self._temp_email = email
        self._temp_password = password

        self.worker = LoginWorker(self.auth_manager, email, password, host)
        self.worker.success.connect(self._on_login_success)
        self.worker.error.connect(self._on_login_error)
        self.worker.finished.connect(self.worker.deleteLater) 
        self.worker.start()

    def _on_login_success(self):
        self.vault_manager.save_kitsu_credentials(self._temp_email, self._temp_password)
        self.on_login_success()

    def _on_login_error(self, mensaje):
        self.lbl_error.setText(mensaje)
        self.lbl_error.show()
        
        self.btn_login.setEnabled(True)
        self.btn_login.setText(self.tr("Log In"))
        
        self._set_icon_or_fallback(self.status_icon, "server.svg", "#EF4444", 12, "🔴")
        self.lbl_status.setText(self.tr("SYSTEM: AUTHENTICATION FAILED."))
