# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/pm_view.py
# Architectural role: UI View / Production Manager Dashboard
# =========================================================================================

"""Production Manager dashboard View.

Switches between the project list and the batch entity builder.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QStackedWidget, QVBoxLayout

from src.interfaces.qt.settings_tabs.tab_credentials import TabCredentials
from src.interfaces.qt.shell.base_dashboard_view import BaseDashboardView
from src.interfaces.qt.viewmodels.base_viewmodel import StatusSink
from src.interfaces.qt.viewmodels.blend_builder_viewmodel import BlendBuilderViewModel
from src.interfaces.qt.viewmodels.project_audit_viewmodel import ProjectAuditViewModel
from src.interfaces.qt.viewmodels.project_list_viewmodel import ProjectListViewModel
from src.interfaces.qt.viewmodels.project_repair_viewmodel import ProjectRepairViewModel
from src.interfaces.qt.widgets.blend_builder_widget import BlendBuilderWidget
from src.interfaces.qt.widgets.project_list_widget import ProjectListWidget


class ViewPM(BaseDashboardView):
    def __init__(
        self,
        parent,
        project_list_vm: ProjectListViewModel,
        blend_builder_vm: BlendBuilderViewModel,
        audit_vm: ProjectAuditViewModel,
        repair_vm: ProjectRepairViewModel,
        auth_service,
        config_factory,
        on_logout,
        status_sink: StatusSink | None = None,
        credential_vault=None,
        **kwargs,
    ) -> None:
        super().__init__(parent, auth_service, config_factory, on_logout, status_sink, **kwargs)

        self.project_list_vm = project_list_vm
        self.blend_builder_vm = blend_builder_vm
        self.audit_vm = audit_vm
        self.repair_vm = repair_vm
        self.credential_vault = credential_vault

        self.setObjectName("ViewPMBase")

        self.add_sidebar_button("btn_projects", self.tr("Projects"), "📁", "folder.svg", lambda: self._switch_panel("btn_projects"), active=True)
        self.add_sidebar_button("btn_batch", self.tr("Batch Creation"), "📦", "box.svg", lambda: self._switch_panel("btn_batch"))
        self.add_sidebar_button("settings", self.tr("Settings"), "🔧", "settings.svg", lambda: self._switch_panel("settings"))

        self._build_pm_content()

    def _build_pm_content(self) -> None:
        self.stacked_content = QStackedWidget()

        self.project_list = ProjectListWidget(
            parent=self.stacked_content,
            viewmodel=self.project_list_vm,
            audit_vm=self.audit_vm,
            repair_vm=self.repair_vm,
            on_open_wizard_callback=self._open_wizard_for_project,
        )
        self.stacked_content.addWidget(self.project_list)

        self.blend_builder = BlendBuilderWidget(
            parent=self.stacked_content,
            viewmodel=self.blend_builder_vm,
        )
        self.stacked_content.addWidget(self.blend_builder)

        self.panel_settings = self._build_settings_panel()
        self.stacked_content.addWidget(self.panel_settings)

        self.content_layout.addWidget(self.stacked_content, stretch=1)
        self.project_list.refresh()

    def _build_settings_panel(self) -> QFrame:
        panel = QFrame()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        lbl_title = QLabel(self.tr("Session Settings"))
        lbl_title.setObjectName("PageTitle")
        layout.addWidget(lbl_title)

        self.tab_credentials = TabCredentials()
        self.tab_credentials.server_changed.connect(self._load_credentials_for)
        layout.addWidget(self.tab_credentials)

        btn_save = QPushButton(self.tr("Save Session Credentials"))
        btn_save.setObjectName("PrimaryButton")
        btn_save.setFixedSize(220, 40)
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.clicked.connect(self._save_credentials)
        layout.addWidget(btn_save, alignment=Qt.AlignLeft)

        layout.addStretch()
        return panel

    def _save_credentials(self) -> None:
        creds = self.tab_credentials.credentials_payload()
        server_id = creds["server_id"]
        if not server_id or self.credential_vault is None:
            return
        username = creds["username"]
        if not username:
            user = self.auth.current_user
            username = user.email if user else "pm"
        self.credential_vault.save_server_credentials(
            server_id, username, creds["password"], creds["enabled"], creds.get("ssh_passphrase") or None
        )
        self.update_status(self.tr("✓ VCS credentials stored in RAM for this session."), "green")

    def _load_credentials_for(self, server_id: str) -> None:
        if not server_id or self.credential_vault is None:
            self.tab_credentials.load_data("", False, False)
            return
        username, _ = self.credential_vault.get_server_credentials(server_id)
        self.tab_credentials.load_data(
            username or "",
            self.credential_vault.is_server_enabled(server_id),
            self.credential_vault.has_ssh_passphrase(server_id),
        )

    def _pm_servers(self) -> list:
        registry = self.config_factory.get_vcs_servers()
        return [
            {**server.to_dict(), "is_default": server.id == registry.default_server_id}
            for server in registry.servers
        ]

    def _switch_panel(self, panel_id: str) -> None:
        self.set_active_sidebar_button(panel_id)
        indices = {"btn_projects": 0, "btn_batch": 1, "settings": 2}
        self.stacked_content.setCurrentIndex(indices.get(panel_id, 0))

        if panel_id == "btn_projects":
            self.project_list.refresh()
        elif panel_id == "btn_batch":
            self.blend_builder.refresh_projects()
        elif panel_id == "settings" and self.credential_vault is not None:
            servers = self._pm_servers()
            default_id = next((s["id"] for s in servers if s.get("is_default")), "")
            self.tab_credentials.set_servers(servers, default_id)
            self._load_credentials_for(default_id)

    def _open_wizard_for_project(self, project_name: str) -> None:
        self._switch_panel("btn_batch")
        self.blend_builder.select_project(project_name)
