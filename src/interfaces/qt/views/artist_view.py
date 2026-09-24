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
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.application.services.auth_service import AuthService
from src.interfaces.qt.components.task_card import TaskCard
from src.interfaces.qt.settings_tabs.tab_credentials import TabCredentials
from src.interfaces.qt.shell.base_dashboard_view import BaseDashboardView
from src.interfaces.qt.viewmodels.artist_viewmodel import ArtistViewModel
from src.interfaces.qt.viewmodels.base_viewmodel import StatusSink
from src.interfaces.qt.views.vcs_publish_dialog import VcsPublishDialog


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
        self._task_cards_by_id = {}
        self._vcs_dialogs = []
        self._cards = []
        self._current_cols = 0

        self.setObjectName("ViewArtistBase")

        self.add_sidebar_button("my_tasks", self.tr("My Tasks"), "📋", "list.svg", lambda: self._switch_panel("my_tasks"), active=True)
        self.add_sidebar_button("settings", self.tr("Settings"), "🔧", "settings.svg", lambda: self._switch_panel("settings"))

        self._build_content()
        self.vm.tasks_loaded.connect(self._on_tasks_loaded)
        self.vm.tasks_load_started.connect(self._on_tasks_load_started)
        self.vm.tasks_load_finished.connect(self._on_tasks_load_finished)
        self.vm.vcs_changes_ready.connect(self._on_vcs_changes_ready)
        self.vm.vcs_publish_finished.connect(self._on_vcs_publish_finished)
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

        self.btn_refresh = QPushButton(self.tr("⟳ Refresh"))
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.setFixedSize(110, 35)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setToolTip(self.tr("Fetch the latest updates for your assigned tasks."))
        self.btn_refresh.clicked.connect(self._refresh_tasks)

        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_refresh)
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

        self.panel_settings = self._build_settings_panel()
        self.stacked_content.addWidget(self.panel_settings)

        self.content_layout.addWidget(self.stacked_content, stretch=1)

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
        self.vm.save_vcs_settings(
            creds["server_id"], creds["username"], creds["password"], creds["enabled"]
        )

    def _load_credentials_for(self, server_id: str) -> None:
        if not server_id:
            self.tab_credentials.load_data("", False, False)
            return
        username, enabled = self.vm.vcs_settings(server_id)
        self.tab_credentials.load_data(username, enabled, self.vm.has_ssh_passphrase(server_id))

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
        indices = {"my_tasks": 0, "settings": 1}
        self.stacked_content.setCurrentIndex(indices.get(panel_id, 0))

        if panel_id == "settings":
            servers = self.vm.list_servers()
            default_id = next((s["id"] for s in servers if s.get("is_default")), "")
            self.tab_credentials.set_servers(servers, default_id)
            self._load_credentials_for(default_id)

    def _refresh_tasks(self) -> None:
        """Re-fetch the assigned task list from Kitsu."""
        self.vm.load_tasks()

    def _on_tasks_load_started(self) -> None:
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText(self.tr("⟳ Refreshing…"))

    def _on_tasks_load_finished(self, _success: bool) -> None:
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText(self.tr("⟳ Refresh"))

    def _on_tasks_loaded(self, cards: list) -> None:
        self._cards = cards
        previous_selection = self.combo_projects.currentData()

        self.combo_projects.blockSignals(True)
        self.combo_projects.clear()
        self.combo_projects.addItem(self.tr("All Projects"), "ALL")

        unique_projects = {}
        for card in cards:
            if card.project_id and card.project_name and card.project_id not in unique_projects:
                unique_projects[card.project_id] = card.project_name

        for project_id, project_name in sorted(unique_projects.items(), key=lambda item: item[1]):
            self.combo_projects.addItem(project_name, project_id)

        # Preserve the selected project filter across a refresh when it still exists.
        index = self.combo_projects.findData(previous_selection) if previous_selection else -1
        self.combo_projects.setCurrentIndex(index if index >= 0 else 0)
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
                pending_change_count=len(card.pending_changes),
                on_update_callback=lambda c=card: self.vm.check_vcs_changes(c),
            )
            self._task_widgets.append(task_card)
            self._task_cards_by_id[str(card.task_data.get("id", ""))] = task_card

        self._current_cols = 0
        self._rearrange_grid()

    # ------------------------------------------------------------------
    # VCS publish flow
    # ------------------------------------------------------------------
    def _on_vcs_changes_ready(self, task_id: str, changes: list) -> None:
        widget = self._task_cards_by_id.get(task_id)
        if widget is not None:
            widget.set_pending_change_count(len(changes))

        if not changes:
            return

        card = next((c for c in self._cards if str(c.task_data.get("id", "")) == task_id), None)
        if card is None:
            return

        if any(getattr(dialog, "task_id", None) == task_id for dialog in self._vcs_dialogs):
            return

        label = f"{card.project_name} • {card.task_data.get('entity_name', '')} - {card.task_data.get('task_type_name', '')}"
        dialog = VcsPublishDialog(self, self.vm, card, changes, task_label=label)
        self._vcs_dialogs.append(dialog)
        dialog.finished.connect(lambda _result, d=dialog: self._release_vcs_dialog(d))
        dialog.show()

    def _release_vcs_dialog(self, dialog) -> None:
        if dialog in self._vcs_dialogs:
            self._vcs_dialogs.remove(dialog)
        dialog.deleteLater()

    def _on_vcs_publish_finished(self, task_id: str, success: bool, message: str) -> None:
        if not success:
            return
        widget = self._task_cards_by_id.get(task_id)
        if widget is not None:
            widget.set_pending_change_count(0)

    def _clear_grid(self) -> None:
        for widget in self._task_widgets:
            widget.hide()
            widget.deleteLater()
        self._task_widgets.clear()
        self._task_cards_by_id.clear()

        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
