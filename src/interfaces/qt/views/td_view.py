# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/td_view.py
# Architectural role: UI View / Command Center Dashboard (PySide6)
# =========================================================================================

"""Technical Director dashboard View.

Switches between the project list, infrastructure and settings widgets.
"""

from PySide6.QtWidgets import QStackedWidget

from src.application.services.project_audit_service import ProjectAuditService
from src.application.services.vault_service import VaultService
from src.interfaces.qt.shell.base_dashboard_view import BaseDashboardView
from src.interfaces.qt.viewmodels.base_viewmodel import StatusSink
from src.interfaces.qt.viewmodels.infrastructure_viewmodel import InfrastructureViewModel
from src.interfaces.qt.viewmodels.project_audit_viewmodel import ProjectAuditViewModel
from src.interfaces.qt.viewmodels.project_list_viewmodel import ProjectListViewModel
from src.interfaces.qt.viewmodels.project_repair_viewmodel import ProjectRepairViewModel
from src.interfaces.qt.viewmodels.settings_viewmodel import SettingsViewModel
from src.interfaces.qt.widgets.infrastructure_widget import InfrastructureWidget
from src.interfaces.qt.widgets.project_list_widget import ProjectListWidget
from src.interfaces.qt.widgets.settings_widget import SettingsWidget


class ViewTD(BaseDashboardView):
    def __init__(
        self,
        parent,
        project_list_vm: ProjectListViewModel,
        infrastructure_vm: InfrastructureViewModel,
        settings_vm: SettingsViewModel,
        audit_vm: ProjectAuditViewModel,
        repair_vm: ProjectRepairViewModel,
        auth_service,
        config_factory,
        production_service,
        vault_service: VaultService,
        on_logout,
        on_new_project_callback=None,
        on_repair_callback=None,
        status_sink: StatusSink | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent, auth_service, config_factory, on_logout, status_sink, **kwargs)

        self.project_list_vm = project_list_vm
        self.infrastructure_vm = infrastructure_vm
        self.settings_vm = settings_vm
        self.audit_vm = audit_vm
        self.repair_vm = repair_vm
        self.production_service = production_service
        self.vault_service = vault_service
        self.on_new_project_callback = on_new_project_callback
        self.on_repair_callback = on_repair_callback

        self.setObjectName("ViewTDBase")

        self.add_sidebar_button("proyectos", self.tr("Projects"), "🗂️", "folder.svg", lambda: self._switch_panel("proyectos"), active=True)
        self.add_sidebar_button("infra", self.tr("Infrastructure"), "⚙️", "server.svg", lambda: self._switch_panel("infra"))
        self.add_sidebar_button("settings", self.tr("Settings"), "🔧", "settings.svg", lambda: self._switch_panel("settings"))

        self._build_td_content()
        self.projects_view.refresh()

    def _build_td_content(self) -> None:
        self.stacked_content = QStackedWidget()

        self.projects_view = ProjectListWidget(
            parent=self.stacked_content,
            viewmodel=self.project_list_vm,
            audit_vm=self.audit_vm,
            repair_vm=self.repair_vm,
            on_new_project_callback=self.on_new_project_callback,
            on_repair_callback=self.on_repair_callback,
        )
        self.stacked_content.addWidget(self.projects_view)

        self.vista_infra = InfrastructureWidget(
            parent=self.stacked_content,
            viewmodel=self.infrastructure_vm,
        )
        self.stacked_content.addWidget(self.vista_infra)

        self.vista_configuraciones = SettingsWidget(
            parent=self.stacked_content,
            viewmodel=self.settings_vm,
            auth_service=self.auth,
            production_service=self.production_service,
            vault_service=self.vault_service,
        )
        self.stacked_content.addWidget(self.vista_configuraciones)

        self.content_layout.addWidget(self.stacked_content, stretch=1)

    def _switch_panel(self, panel_id: str) -> None:
        self.set_active_sidebar_button(panel_id)
        indices = {"proyectos": 0, "infra": 1, "settings": 2}
        self.stacked_content.setCurrentIndex(indices.get(panel_id, 0))
