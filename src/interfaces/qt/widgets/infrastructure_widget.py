# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/infrastructure_widget.py
# Architectural role: UI Widget / Infrastructure Controller
# =========================================================================================

"""Studio infrastructure panel.

Renders the service cards and forwards lifecycle commands to the
``InfrastructureViewModel``.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.interfaces.qt.viewmodels.infrastructure_viewmodel import InfrastructureViewModel


class InfrastructureWidget(QFrame):
    def __init__(self, parent, viewmodel: InfrastructureViewModel, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.vm = viewmodel

        self.setObjectName("InfrastructureBase")
        self._build_ui()
        self._load_remote_server_settings()
        self.vm.operation_finished.connect(self._on_operation_finished)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        header = QLabel(self.tr("Studio Infrastructure (Zero-Config Environments)"))
        header.setStyleSheet("color: #F8FAFC; font-size: 20px; font-weight: bold;")
        layout.addWidget(header)

        desc = QLabel(self.tr("Deploy local instances of Subversion and Kitsu for testing and development. Requires Docker installed and running."))
        desc.setStyleSheet("color: #94A3B8; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        grid = QGridLayout()
        grid.setSpacing(20)

        svn_card = self._build_service_card(
            title="Local VCS Server (SVN)",
            desc=self.tr("Centralized version control system for binary assets and scenes."),
            port="3690",
            start_callback=self.vm.deploy_svn,
            stop_callback=self.vm.stop_svn,
        )
        grid.addWidget(svn_card, 0, 0)

        kitsu_card = self._build_kitsu_service_card()
        grid.addWidget(kitsu_card, 0, 1)

        layout.addLayout(grid)
        layout.addWidget(self._build_remote_server_card())
        layout.addStretch()

    def _build_service_card(self, title: str, desc: str, port: str, start_callback, stop_callback) -> QFrame:
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background-color: #1E293B; border-radius: 12px; border: 1px solid #334155; }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 20, 20, 20)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #F8FAFC; font-size: 16px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_title)

        lbl_desc = QLabel(desc)
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px; border: none;")
        lbl_desc.setWordWrap(True)
        c_layout.addWidget(lbl_desc)

        lbl_port = QLabel(f"Port: {port}")
        lbl_port.setStyleSheet("color: #3B82F6; font-size: 11px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_port)

        c_layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_start = QPushButton(self.tr("Deploy & Start"))
        btn_start.setStyleSheet("""
            QPushButton { background-color: #10B981; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #059669; }
        """)
        btn_start.clicked.connect(start_callback)

        btn_stop = QPushButton(self.tr("Stop & Destroy"))
        btn_stop.setStyleSheet("""
            QPushButton { background-color: #EF4444; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #DC2626; }
        """)
        btn_stop.clicked.connect(stop_callback)

        btn_layout.addWidget(btn_start)
        btn_layout.addWidget(btn_stop)

        c_layout.addLayout(btn_layout)
        return card

    def _styled_input(self, placeholder: str = "") -> QLineEdit:
        field = QLineEdit()
        field.setFixedHeight(30)
        field.setPlaceholderText(placeholder)
        field.setStyleSheet(
            "QLineEdit { background-color: #0F172A; border: 1px solid #475569; color: #F8FAFC; "
            "border-radius: 6px; padding-left: 8px; }"
        )
        return field

    def _browse_into(self, line_edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Select File"))
        if path:
            line_edit.setText(path)

    def _build_remote_server_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet("QFrame { background-color: #1E293B; border-radius: 12px; border: 1px solid #334155; }")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 20, 20, 20)
        c_layout.setSpacing(10)

        title = QLabel(self.tr("Remote VCS Server (VPS over Tailscale)"))
        title.setStyleSheet("color: #F8FAFC; font-size: 16px; font-weight: bold; border: none;")
        c_layout.addWidget(title)

        desc = QLabel(self.tr(
            "Administer project repositories on a remote SVN server. Server commands run "
            "inside the configured Docker container through OpenSSH over the tailnet. "
            "Artist credentials stay in the Session Credentials tab; the SSH passphrase "
            "is only needed for provisioning and is kept in RAM."
        ))
        desc.setStyleSheet("color: #94A3B8; font-size: 12px; border: none;")
        desc.setWordWrap(True)
        c_layout.addWidget(desc)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.combo_server_mode = QComboBox()
        self.combo_server_mode.addItems(["local_docker", "remote_ssh"])
        self.entry_svn_url = self._styled_input("svn://svn-vps")
        self.entry_remote_host = self._styled_input("svn-vps (MagicDNS or 100.x)")
        self.entry_ssh_port = self._styled_input("22")
        self.entry_ssh_user = self._styled_input("openstudio")
        self.entry_ssh_key = self._styled_input("/home/user/.ssh/id_ed25519")
        self.entry_ssh_cert = self._styled_input("optional OpenSSH certificate")
        self.entry_known_hosts = self._styled_input("optional known_hosts file")
        self.entry_container = self._styled_input("estudio_svn")
        self.entry_container_user = self._styled_input("optional (default container user)")
        self.entry_repo_root = self._styled_input("/var/opt/svn")
        self.entry_password_db = self._styled_input("/var/opt/svn/passwd")
        self.entry_realm = self._styled_input("OpenStudio")

        form.addRow(self._styled_label(self.tr("Mode:")), self.combo_server_mode)
        form.addRow(self._styled_label(self.tr("SVN Base URL:")), self.entry_svn_url)
        form.addRow(self._styled_label(self.tr("SSH Host:")), self.entry_remote_host)
        form.addRow(self._styled_label(self.tr("SSH Port:")), self.entry_ssh_port)
        form.addRow(self._styled_label(self.tr("SSH User:")), self.entry_ssh_user)
        form.addRow(self._styled_label(self.tr("SSH Key:")), self._with_browse(self.entry_ssh_key))
        form.addRow(self._styled_label(self.tr("SSH Certificate:")), self._with_browse(self.entry_ssh_cert))
        form.addRow(self._styled_label(self.tr("Known Hosts:")), self._with_browse(self.entry_known_hosts))
        form.addRow(self._styled_label(self.tr("Docker Container:")), self.entry_container)
        form.addRow(self._styled_label(self.tr("Container User:")), self.entry_container_user)
        form.addRow(self._styled_label(self.tr("Remote Repo Root:")), self.entry_repo_root)
        form.addRow(self._styled_label(self.tr("Global passwd (in-container):")), self.entry_password_db)
        form.addRow(self._styled_label(self.tr("Realm:")), self.entry_realm)
        c_layout.addLayout(form)

        self.entry_remote_host.textChanged.connect(self._sync_svn_url_from_host)

        buttons = QHBoxLayout()
        btn_save = QPushButton(self.tr("Save Server Settings"))
        btn_save.setStyleSheet("QPushButton { background-color: #10B981; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }")
        btn_save.clicked.connect(self._save_remote_server_settings)
        buttons.addWidget(btn_save)

        btn_test_ssh = QPushButton(self.tr("Test SSH"))
        btn_test_ssh.setStyleSheet("QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }")
        btn_test_ssh.clicked.connect(lambda: self.vm.test_remote_connection("ssh"))
        buttons.addWidget(btn_test_ssh)

        btn_test_svn = QPushButton(self.tr("Test SVN"))
        btn_test_svn.setStyleSheet("QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }")
        btn_test_svn.clicked.connect(lambda: self.vm.test_remote_connection("svn"))
        buttons.addWidget(btn_test_svn)

        c_layout.addLayout(buttons)
        return card

    def _with_browse(self, line_edit: QLineEdit) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line_edit)
        btn = QPushButton(self.tr("..."))
        btn.setFixedWidth(32)
        btn.setStyleSheet("QPushButton { background-color: #334155; color: white; border-radius: 6px; }")
        btn.clicked.connect(lambda: self._browse_into(line_edit))
        row.addWidget(btn)
        return container

    def _sync_svn_url_from_host(self, host: str) -> None:
        current = self.entry_svn_url.text().strip()
        if not current or current.startswith("svn://"):
            self.entry_svn_url.setText(f"svn://{host.strip()}" if host.strip() else "")

    def _load_remote_server_settings(self) -> None:
        settings = self.vm.load_server_settings()
        profile = settings.get("profile", {})
        remote = profile.get("remote", {})

        self.combo_server_mode.setCurrentText(profile.get("mode", "local_docker"))
        self.entry_svn_url.setText(settings.get("repository_url", ""))
        self.entry_remote_host.setText(remote.get("host", ""))
        self.entry_ssh_port.setText(str(remote.get("ssh_port", 22)))
        self.entry_ssh_user.setText(remote.get("ssh_user", ""))
        self.entry_ssh_key.setText(remote.get("ssh_key_path", ""))
        self.entry_ssh_cert.setText(remote.get("ssh_cert_path", ""))
        self.entry_known_hosts.setText(remote.get("known_hosts_path", ""))
        self.entry_container.setText(remote.get("container", ""))
        self.entry_container_user.setText(remote.get("container_user", ""))
        self.entry_repo_root.setText(remote.get("repo_root", "/var/opt/svn"))
        self.entry_password_db.setText(remote.get("password_db", ""))
        self.entry_realm.setText(remote.get("realm", "OpenStudio"))

    def _save_remote_server_settings(self) -> None:
        try:
            port = int(self.entry_ssh_port.text().strip() or "22")
        except ValueError:
            port = 22
        payload = {
            "mode": self.combo_server_mode.currentText(),
            "remote": {
                "host": self.entry_remote_host.text().strip(),
                "ssh_port": port,
                "ssh_user": self.entry_ssh_user.text().strip(),
                "ssh_key_path": self.entry_ssh_key.text().strip(),
                "ssh_cert_path": self.entry_ssh_cert.text().strip(),
                "known_hosts_path": self.entry_known_hosts.text().strip(),
                "container": self.entry_container.text().strip(),
                "container_user": self.entry_container_user.text().strip(),
                "repo_root": self.entry_repo_root.text().strip(),
                "password_db": self.entry_password_db.text().strip(),
                "realm": self.entry_realm.text().strip(),
            },
        }
        self.vm.save_server_settings(payload, self.entry_svn_url.text().strip())

    def _build_kitsu_service_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background-color: #1E293B; border-radius: 12px; border: 1px solid #334155; }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 20, 20, 20)
        c_layout.setSpacing(10)

        lbl_title = QLabel("Production Tracker (Kitsu 1.0+)")
        lbl_title.setStyleSheet("color: #F8FAFC; font-size: 16px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_title)

        lbl_desc = QLabel(self.tr("Database, API, and Web Frontend for Shot and Asset management."))
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px; border: none;")
        lbl_desc.setWordWrap(True)
        c_layout.addWidget(lbl_desc)

        lbl_port = QLabel("Port: 8080")
        lbl_port.setStyleSheet("color: #3B82F6; font-size: 11px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_port)

        c_layout.addStretch()

        btn_layout1 = QHBoxLayout()
        btn_start = QPushButton(self.tr("Deploy & Start"))
        btn_start.setStyleSheet("""
            QPushButton { background-color: #10B981; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #059669; }
        """)
        btn_start.clicked.connect(self.vm.deploy_kitsu)

        btn_stop = QPushButton(self.tr("Stop & Destroy"))
        btn_stop.setStyleSheet("""
            QPushButton { background-color: #EF4444; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #DC2626; }
        """)
        btn_stop.clicked.connect(self.vm.stop_kitsu)
        btn_layout1.addWidget(btn_start)
        btn_layout1.addWidget(btn_stop)

        btn_layout2 = QHBoxLayout()
        btn_seed_admin = QPushButton(self.tr("1. Create Admin Account"))
        btn_seed_admin.setToolTip("Runs 'zou create-admin' inside the container.")
        btn_seed_admin.setStyleSheet("""
            QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 8px; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: #475569; }
        """)
        btn_seed_admin.clicked.connect(lambda: self.vm.run_seeder("admin"))

        btn_seed_dummy = QPushButton(self.tr("2. Seed Dummy Team"))
        btn_seed_dummy.setToolTip("Injects PM, TD and Artist via the Gazu API.")
        btn_seed_dummy.setStyleSheet("""
            QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 8px; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: #475569; }
        """)
        btn_seed_dummy.clicked.connect(lambda: self.vm.run_seeder("dummy"))
        btn_layout2.addWidget(btn_seed_admin)
        btn_layout2.addWidget(btn_seed_dummy)

        c_layout.addLayout(btn_layout1)
        c_layout.addLayout(btn_layout2)

        return card

    def _on_operation_finished(self, success: bool, message: str) -> None:
        if not success:
            QMessageBox.critical(self, self.tr("Infrastructure Error"), message)
