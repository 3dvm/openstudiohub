# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/artist_view.py
# Architectural role: UI View / Artist Dashboard (PySide6)
# =========================================================================================

"""Artist dashboard View.

Renders the assigned-task grid and the project filter. All data and actions
are delegated to ``ArtistViewModel``.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.application.services.auth_service import AuthService
from src.interfaces.qt.components.task_card import TaskCard
from src.interfaces.qt.shell.base_dashboard_view import BaseDashboardView
from src.interfaces.qt.viewmodels.artist_viewmodel import ArtistViewModel
from src.interfaces.qt.viewmodels.base_viewmodel import StatusSink


class ViewArtist(BaseDashboardView):
    def __init__(
        self,
        parent,
        viewmodel: ArtistViewModel,
        auth_service: AuthService,
        config_factory,
        on_logout,
        status_sink: StatusSink | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent, auth_service, config_factory, on_logout, status_sink, **kwargs)

        self.vm = viewmodel
        self._token = auth_service.access_token()
        self._host = auth_service.host

        self._task_widgets = []
        self._cards = []
        self._current_cols = 0

        self.setObjectName("ViewArtistBase")

        self.add_sidebar_button("my_tasks", self.tr("My Tasks"), "📋", "list.svg", lambda: self._switch_panel("my_tasks"), active=True)

        self._build_content()
        self.vm.tasks_loaded.connect(self._on_tasks_loaded)
        self.vm.load_tasks()

    def _build_content(self) -> None:
        self.stacked_content = QStackedWidget()

        self.panel_tasks = QFrame()
        layout_tasks = QVBoxLayout(self.panel_tasks)
        layout_tasks.setContentsMargins(0, 0, 0, 0)
        layout_tasks.setSpacing(20)

        header_layout = QHBoxLayout()

        lbl_title = QLabel(self.tr("My Assigned Tasks"))
        lbl_title.setObjectName("PageTitle")

        self.combo_projects = QComboBox()
        self.combo_projects.setObjectName("StandardComboBox")
        self.combo_projects.setFixedSize(250, 35)
        self.combo_projects.currentIndexChanged.connect(self._apply_project_filter)

        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(QLabel(self.tr("Project:")))
        header_layout.addWidget(self.combo_projects)

        layout_tasks.addLayout(header_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("InvisibleScrollArea")

        self.grid_widget = QWidget()
        self.grid_widget.setObjectName("TransparentGridContainer")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.scroll_area.setWidget(self.grid_widget)
        layout_tasks.addWidget(self.scroll_area, stretch=1)

        self.stacked_content.addWidget(self.panel_tasks)

        self.content_layout.addWidget(self.stacked_content, stretch=1)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._rearrange_grid()

    def _rearrange_grid(self) -> None:
        if not self._task_widgets:
            return

        viewport_width = self.scroll_area.viewport().width()
        card_width = 280
        spacing = self.grid_layout.spacing()

        cols = max(1, (viewport_width + spacing) // (card_width + spacing))

        if getattr(self, "_current_cols", 0) == cols:
            return

        self._current_cols = cols
        row, col = 0, 0

        for widget in self._task_widgets:
            self.grid_layout.removeWidget(widget)
            self.grid_layout.addWidget(widget, row, col)

            col += 1
            if col >= cols:
                col = 0
                row += 1

    def _switch_panel(self, panel_id: str) -> None:
        self.set_active_sidebar_button(panel_id)
        indices = {"my_tasks": 0, "watchtower": 1}
        self.stacked_content.setCurrentIndex(indices.get(panel_id, 0))

    def _on_tasks_loaded(self, cards: list) -> None:
        self._cards = cards

        self.combo_projects.blockSignals(True)
        self.combo_projects.clear()
        self.combo_projects.addItem(self.tr("All Projects"), "ALL")

        unique_projects = {}
        for card in cards:
            if card.project_id and card.project_name and card.project_id not in unique_projects:
                unique_projects[card.project_id] = card.project_name

        for project_id, project_name in sorted(unique_projects.items(), key=lambda item: item[1]):
            self.combo_projects.addItem(project_name, project_id)

        self.combo_projects.blockSignals(False)
        self._apply_project_filter()

    def _apply_project_filter(self, index: int = 0) -> None:
        self._clear_grid()

        selected_project_id = self.combo_projects.currentData()

        if selected_project_id == "ALL":
            filtered_cards = self._cards
        else:
            filtered_cards = [c for c in self._cards if c.project_id == selected_project_id]

        for card in filtered_cards:
            task_card = TaskCard(
                parent=self.grid_widget,
                task_data=card.task_data,
                project_root=card.project_root,
                is_installed=card.is_installed,
                can_work=card.can_work,
                blocked_reason=card.blocked_reason,
                token=self._token,
                host=self._host,
                on_launch_callback=lambda c=card: self.vm.launch(c),
                on_install_callback=lambda c=card: self.vm.install(c),
            )
            self._task_widgets.append(task_card)

        self._current_cols = 0
        self._rearrange_grid()

    def _clear_grid(self) -> None:
        for widget in self._task_widgets:
            widget.hide()
            widget.deleteLater()
        self._task_widgets.clear()

        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
