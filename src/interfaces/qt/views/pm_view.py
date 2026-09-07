# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/pm_view.py
# Architectural role: UI View / Production Manager Dashboard
# =========================================================================================

"""Production Manager dashboard View.

Switches between the project list and the batch entity builder.
"""

from PySide6.QtWidgets import QStackedWidget

from src.interfaces.qt.shell.base_dashboard_view import BaseDashboardView
from src.interfaces.qt.viewmodels.base_viewmodel import StatusSink
from src.interfaces.qt.viewmodels.blend_builder_viewmodel import BlendBuilderViewModel
from src.interfaces.qt.viewmodels.project_list_viewmodel import ProjectListViewModel
from src.interfaces.qt.widgets.blend_builder_widget import BlendBuilderWidget
from src.interfaces.qt.widgets.project_list_widget import ProjectListWidget


class ViewPM(BaseDashboardView):
    def __init__(
        self,
        parent,
        project_list_vm: ProjectListViewModel,
        blend_builder_vm: BlendBuilderViewModel,
        auth_service,
        config_factory,
        on_logout,
        status_sink: StatusSink | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent, auth_service, config_factory, on_logout, status_sink, **kwargs)

        self.project_list_vm = project_list_vm
        self.blend_builder_vm = blend_builder_vm

        self.setObjectName("ViewPMBase")

        self.add_sidebar_button("btn_projects", self.tr("Projects"), "📁", "folder.svg", lambda: self._switch_panel("btn_projects"), active=True)
        self.add_sidebar_button("btn_batch", self.tr("Batch Creation"), "📦", "box.svg", lambda: self._switch_panel("btn_batch"))

        self._build_pm_content()

    def _build_pm_content(self) -> None:
        self.stacked_content = QStackedWidget()

        self.project_list = ProjectListWidget(
            parent=self.stacked_content,
            viewmodel=self.project_list_vm,
            on_open_wizard_callback=self._open_wizard_for_project,
        )
        self.stacked_content.addWidget(self.project_list)

        self.blend_builder = BlendBuilderWidget(
            parent=self.stacked_content,
            viewmodel=self.blend_builder_vm,
        )
        self.stacked_content.addWidget(self.blend_builder)

        self.content_layout.addWidget(self.stacked_content, stretch=1)
        self.project_list.refresh()

    def _switch_panel(self, panel_id: str) -> None:
        self.set_active_sidebar_button(panel_id)
        indices = {"btn_projects": 0, "btn_batch": 1}
        self.stacked_content.setCurrentIndex(indices.get(panel_id, 0))

        if panel_id == "btn_projects":
            self.project_list.refresh()

    def _open_wizard_for_project(self, project_name: str) -> None:
        self._switch_panel("btn_batch")
        index = self.blend_builder.combo_projects.findText(project_name)
        if index >= 0:
            self.blend_builder.combo_projects.setCurrentIndex(index)
