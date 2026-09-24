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
    QCheckBox,
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
    QScrollArea,
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
        self.vm.operation_finished.connect(self._on_operation_finished)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("InvisibleScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        container.setObjectName("TransparentGridContainer")
        layout = QVBoxLayout(container)
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

        scroll.setWidget(container)
        outer.addWidget(scroll)

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

    def _styled_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 12px; border: none;")
        return label

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

        title = QLabel(self.tr("VCS Servers"))
        title.setStyleSheet("color: #F8FAFC; font-size: 16px; font-weight: bold; border: none;")
        c_layout.addWidget(title)

        desc = QLabel(self.tr(
            "Manage the version-control servers the studio can use. Each project is bound to "
            "one server. Remote servers run SVN inside a Docker container reached through OpenSSH "
            "over the tailnet; artist credentials live in the Session Credentials tab and the SSH "
            "passphrase is only needed for provisioning (kept in RAM)."
        ))
        desc.setStyleSheet("color: #94A3B8; font-size: 12px; border: none;")
        desc.setWordWrap(True)
        c_layout.addWidget(desc)

        self._servers_by_id = {}
        self._loading_server = False
        self._current_server_id = ""

        selector = QHBoxLayout()
        self.combo_servers = QComboBox()
        self.combo_servers.setFixedHeight(30)
        self.combo_servers.setStyleSheet(
            "QComboBox { background-color: #0F172A; border: 1px solid #475569; color: #F8FAFC; border-radius: 6px; padding-left: 8px; }"
        )
        self.combo_servers.currentIndexChanged.connect(self._on_server_selected)
        selector.addWidget(self.combo_servers, stretch=1)

        btn_new = QPushButton(self.tr("New"))
        btn_new.setStyleSheet("QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 6px; font-weight: bold; }")
        btn_new.clicked.connect(self._on_new_server)
        selector.addWidget(btn_new)

        btn_remove = QPushButton(self.tr("Remove"))
        btn_remove.setStyleSheet("QPushButton { background-color: #7F1D1D; color: white; border-radius: 6px; padding: 6px; font-weight: bold; }")
        btn_remove.clicked.connect(self._on_remove_server)
        selector.addWidget(btn_remove)

        btn_default = QPushButton(self.tr("Set Default"))
        btn_default.setStyleSheet("QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 6px; font-weight: bold; }")
        btn_default.clicked.connect(self._on_set_default)
        selector.addWidget(btn_default)
        c_layout.addLayout(selector)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.entry_server_name = self._styled_input("VPS Production")
        self.combo_adapter = QComboBox()
        self.combo_adapter.addItems(["svn", "git-lfs", "none"])
        self.entry_svn_url = self._styled_input("svn://svn-vps")
        self.chk_sparse = QCheckBox(self.tr("Enable Jailing (Vendor Sparse Checkout)"))
        self.chk_sparse.setStyleSheet("color: #94A3B8; border: none;")
        self.combo_server_mode = QComboBox()
        self.combo_server_mode.addItems(["local_docker", "remote_ssh"])
        self.entry_local_container = self._styled_input("openstudio_local_svn")
        self.entry_local_root = self._styled_input("/home/svn")
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

        form.addRow(self._styled_label(self.tr("Name:")), self.entry_server_name)
        form.addRow(self._styled_label(self.tr("Adapter:")), self.combo_adapter)
        form.addRow(self._styled_label(self.tr("Repository URL:")), self.entry_svn_url)
        form.addRow("", self.chk_sparse)
        form.addRow(self._styled_label(self.tr("Mode:")), self.combo_server_mode)
        form.addRow(self._styled_label(self.tr("Local Container:")), self.entry_local_container)
        form.addRow(self._styled_label(self.tr("Local Repo Root:")), self.entry_local_root)
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
        btn_save = QPushButton(self.tr("Save Server"))
        btn_save.setStyleSheet("QPushButton { background-color: #10B981; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }")
        btn_save.clicked.connect(self._save_server)
        buttons.addWidget(btn_save)

        btn_test_ssh = QPushButton(self.tr("Test SSH"))
        btn_test_ssh.setStyleSheet("QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }")
        btn_test_ssh.clicked.connect(lambda: self._test_server("ssh"))
        buttons.addWidget(btn_test_ssh)

        btn_test_svn = QPushButton(self.tr("Test SVN"))
        btn_test_svn.setStyleSheet("QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }")
        btn_test_svn.clicked.connect(lambda: self._test_server("svn"))
        buttons.addWidget(btn_test_svn)

        c_layout.addLayout(buttons)

        self._reload_servers()
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
        if self.combo_server_mode.currentText() != "remote_ssh":
            return
        current = self.entry_svn_url.text().strip()
        if not current or current.startswith("svn://"):
            self.entry_svn_url.setText(f"svn://{host.strip()}" if host.strip() else "")

    # ------------------------------------------------------------------
    # VCS server manager
    # ------------------------------------------------------------------
    def _reload_servers(self, select_id: str = "") -> None:
        self._loading_server = True
        servers = self.vm.list_servers()
        self._servers_by_id = {server["id"]: server for server in servers}
        self.combo_servers.clear()
        for server in servers:
            label = server["name"] + ("  (default)" if server.get("is_default") else "")
            self.combo_servers.addItem(label, server["id"])
        self._loading_server = False

        target = select_id or self._current_server_id
        if target and target in self._servers_by_id:
            self._select_server(target)
        elif servers:
            self._select_server(servers[0]["id"])
        else:
            self._clear_server_fields()

    def _select_server(self, server_id: str) -> None:
        server = self._servers_by_id.get(server_id)
        if server is None:
            return
        index = self.combo_servers.findData(server_id)
        if index >= 0 and self.combo_servers.currentIndex() != index:
            self._loading_server = True
            self.combo_servers.setCurrentIndex(index)
            self._loading_server = False
        self._load_server_fields(server)

    def _on_server_selected(self, _index: int) -> None:
        if self._loading_server:
            return
        server_id = self.combo_servers.currentData()
        if server_id:
            self._load_server_fields(self._servers_by_id.get(server_id, {}))

    def _load_server_fields(self, server: dict) -> None:
        profile = server.get("profile", {})
        remote = profile.get("remote", {})
        self._loading_server = True
        self._current_server_id = server.get("id", "")
        self.entry_server_name.setText(server.get("name", ""))
        self.combo_adapter.setCurrentText(server.get("adapter", "svn"))
        self.entry_svn_url.setText(server.get("repository_url", ""))
        self.chk_sparse.setChecked(server.get("enable_vendor_sparse_checkout", True))
        self.combo_server_mode.setCurrentText(profile.get("mode", "local_docker"))
        self.entry_local_container.setText(profile.get("local_container", "openstudio_local_svn"))
        self.entry_local_root.setText(profile.get("local_repo_root", "/home/svn"))
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
        self._loading_server = False

    def _clear_server_fields(self) -> None:
        self._load_server_fields({
            "id": "",
            "name": "",
            "adapter": "svn",
            "repository_url": "",
            "enable_vendor_sparse_checkout": True,
            "profile": {"mode": "local_docker", "local_container": "openstudio_local_svn", "local_repo_root": "/home/svn", "remote": {}},
        })
        self.combo_servers.setCurrentIndex(-1)

    def _on_new_server(self) -> None:
        self._current_server_id = ""
        self.entry_server_name.clear()
        self.combo_adapter.setCurrentText("svn")
        self.entry_svn_url.clear()
        self.chk_sparse.setChecked(True)
        self.combo_server_mode.setCurrentText("remote_ssh")
        self.entry_local_container.setText("openstudio_local_svn")
        self.entry_local_root.setText("/home/svn")
        for field in (self.entry_remote_host, self.entry_ssh_user, self.entry_ssh_key,
                      self.entry_ssh_cert, self.entry_known_hosts, self.entry_container,
                      self.entry_container_user, self.entry_password_db):
            field.clear()
        self.entry_ssh_port.setText("22")
        self.entry_repo_root.setText("/var/opt/svn")
        self.entry_realm.setText("OpenStudio")
        self.entry_server_name.setFocus()

    def _on_remove_server(self) -> None:
        server_id = self._current_server_id or self.combo_servers.currentData()
        if not server_id:
            return
        server = self._servers_by_id.get(server_id, {})
        confirm = QMessageBox.question(
            self,
            self.tr("Remove VCS Server"),
            self.tr(f"Remove the server configuration '{server.get('name', server_id)}'? "
                    "Repositories on the server are not deleted."),
        )
        if confirm == QMessageBox.Yes:
            self.vm.remove_server(server_id)
            self._current_server_id = ""
            self._reload_servers()

    def _on_set_default(self) -> None:
        server_id = self._current_server_id or self.combo_servers.currentData()
        if server_id:
            self.vm.set_default_server(server_id)
            self._reload_servers(select_id=server_id)

    def _save_server(self) -> None:
        name = self.entry_server_name.text().strip() or "Server"
        server_id = self._current_server_id
        if not server_id:
            server_id = self.vm.make_server_id(name)

        try:
            port = int(self.entry_ssh_port.text().strip() or "22")
        except ValueError:
            port = 22

        payload = {
            "id": server_id,
            "name": name,
            "adapter": self.combo_adapter.currentText(),
            "repository_url": self.entry_svn_url.text().strip(),
            "enable_vendor_sparse_checkout": self.chk_sparse.isChecked(),
            "profile": {
                "mode": self.combo_server_mode.currentText(),
                "local_container": self.entry_local_container.text().strip() or "openstudio_local_svn",
                "local_repo_root": self.entry_local_root.text().strip() or "/home/svn",
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
            },
        }
        if self.vm.save_server(payload):
            self._current_server_id = server_id
            self._reload_servers(select_id=server_id)

    def _test_server(self, target: str) -> None:
        server_id = self._current_server_id or self.combo_servers.currentData()
        if not server_id:
            QMessageBox.information(self, self.tr("Test Server"), self.tr("Save the server before testing it."))
            return
        self.vm.test_server(server_id, target)


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
