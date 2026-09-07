# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/login_view.py
# Architectural role: UI View / Authentication (PySide6)
# =========================================================================================

"""Login view.

Pure presentation: it renders the form and forwards the user's actions to the
``LoginViewModel``. All authentication state and Studio Seed logic live in the
ViewModel.
"""

from pathlib import Path

from _version import __version__

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.interfaces.qt.viewmodels.login_viewmodel import LoginViewModel


class HeroImageWidget(QWidget):
    """Widget that paints a background image with 'object-fit: cover' semantics."""

    def __init__(self, image_path: Path) -> None:
        super().__init__()
        self.pixmap = QPixmap(str(image_path))
        self.setObjectName("HeroPanel")

    def paintEvent(self, event) -> None:
        if self.pixmap.isNull():
            return super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        rect = self.rect()
        scaled_pixmap = self.pixmap.scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

        x_offset = (scaled_pixmap.width() - rect.width()) // 2
        y_offset = (scaled_pixmap.height() - rect.height()) // 2

        painter.drawPixmap(0, 0, scaled_pixmap, x_offset, y_offset, rect.width(), rect.height())


class LoginSettingsDialog(QDialog):
    """Modal for advanced Studio Seed configuration."""

    def __init__(self, parent, clear_callback) -> None:
        super().__init__(parent)
        self.clear_callback = clear_callback

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

    def _confirm_clear(self) -> None:
        reply = QMessageBox.question(
            self,
            self.tr("Clear Configuration"),
            self.tr("Are you sure you want to delete the local configuration?\nAll connection paths will be lost."),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.clear_callback()
            self.accept()


class ViewLogin(QWidget):
    def __init__(self, parent, viewmodel: LoginViewModel) -> None:
        super().__init__(parent)

        self.vm = viewmodel
        self.setObjectName("ViewLoginBase")

        self._build_ui()
        self._connect_signals()
        self.vm.load_config_state()

    def _set_icon_or_fallback(self, label: QLabel, icon_name: str, color_hex: str, size: int, fallback_text: str) -> None:
        """Tint an SVG in-memory to avoid desynchronized emoji."""
        icon_path = Path(f"assets/icons/{icon_name}")
        if not icon_path.exists():
            label.setText(fallback_text)
            label.setStyleSheet(f"color: {color_hex};")
            return

        try:
            with open(icon_path, "r", encoding="utf-8") as handle:
                svg_content = handle.read()

            svg_content = svg_content.replace("currentColor", color_hex)
            svg_content = svg_content.replace("#000000", color_hex)
            svg_content = svg_content.replace('#000"', f'{color_hex}"')
            svg_content = svg_content.replace("#000'", f"{color_hex}'")

            pixmap = QPixmap()
            pixmap.loadFromData(svg_content.encode("utf-8"), "SVG")
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaledToHeight(size, Qt.SmoothTransformation))
                label.setText("")
            else:
                label.setText(fallback_text)
        except Exception:  # noqa: BLE001
            label.setText(fallback_text)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # TOP BAR
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

        self.settings_icon = QLabel()
        self._set_icon_or_fallback(self.settings_icon, "settings.svg", "#64748B", 22, "⚙️")
        self.settings_icon.setContentsMargins(10, 0, 15, 0)
        self.settings_icon.setCursor(Qt.PointingHandCursor)
        self.settings_icon.mousePressEvent = self._open_settings_modal
        top_layout.addWidget(self.settings_icon)

        main_layout.addWidget(self.top_bar)

        # SPLIT SCREEN
        self.split_area = QFrame(self)
        split_layout = QHBoxLayout(self.split_area)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(0)

        # LEFT PANEL (LOGIN FORM)
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

        self.btn_login = QPushButton(self.tr("Log In"))
        self.btn_login.setObjectName("PrimaryButton")
        self.btn_login.setFixedHeight(50)
        self.btn_login.setCursor(Qt.PointingHandCursor)
        self.btn_login.clicked.connect(self._on_login_clicked)
        form_layout.addWidget(self.btn_login)

        self.btn_import_seed = QPushButton(self.tr("Import Studio Seed (.seed)"))
        self.btn_import_seed.setObjectName("SecondaryButton")
        self.btn_import_seed.setFixedHeight(40)
        self.btn_import_seed.setCursor(Qt.PointingHandCursor)
        self.btn_import_seed.clicked.connect(self._import_seed)
        form_layout.addWidget(self.btn_import_seed)

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

        # RIGHT PANEL (HERO)
        hero_path = Path("assets/login_hero.png")
        if not hero_path.exists():
            hero_path = Path("assets/login_hero.jpg")

        self.right_panel = HeroImageWidget(hero_path)
        split_layout.addWidget(self.right_panel, stretch=1)

        main_layout.addWidget(self.split_area, stretch=1)

        # STATUS BAR
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

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        self.vm.error_message.connect(self._show_error)
        self.vm.config_state_changed.connect(self._on_config_state_changed)
        self.vm.host_set.connect(self.entry_host.setText)
        self.vm.busy_changed.connect(self._on_busy_changed)
        self.vm.status_message.connect(self._on_status_message)

    def _on_config_state_changed(self, has_config: bool) -> None:
        if has_config:
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

    def _on_busy_changed(self, busy: bool) -> None:
        self.btn_login.setEnabled(not busy)
        self.btn_login.setText(self.tr("Connecting to Server...") if busy else self.tr("Log In"))
        if busy:
            self._set_icon_or_fallback(self.status_icon, "server.svg", "#F59E0B", 12, "🟠")

    def _on_status_message(self, message: str, color: str) -> None:
        self.lbl_status.setText(message)
        if color == "red":
            self._set_icon_or_fallback(self.status_icon, "server.svg", "#EF4444", 12, "🔴")

    def _show_error(self, message: str) -> None:
        self.lbl_error.setText(message)
        self.lbl_error.setStyleSheet("color: #EF4444;")
        self.lbl_error.show()

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------
    def _on_login_clicked(self) -> None:
        email = self.entry_email.text().strip()
        password = self.entry_password.text().strip()
        host = self.entry_host.text().strip()

        self.lbl_error.hide()
        self.lbl_error.setStyleSheet("color: #EF4444;")

        if not email or not password or not host:
            self._show_error(self.tr("Please fill all the required fields."))
            return

        self.vm.login(email, password, host)

    def _import_seed(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select Studio Seed File"), "", self.tr("Seed Files (*.seed);;All Files (*)")
        )
        if file_path:
            self.vm.import_seed(Path(file_path))

    def _open_settings_modal(self, event) -> None:
        dialog = LoginSettingsDialog(self, self.vm.clear_local_config)
        dialog.exec()
