# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/artist_view.py
# Architectural role: UI View / Artist Dashboard (PySide6)
# =========================================================================================

"""Artist dashboard View.

Renders the assigned-task grid and the project filter. All data and actions
are delegated to ``ArtistViewModel``.
"""

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.application.services.auth_service import AuthService
from src.domain.production.kitsu_links import kitsu_base_url, task_kitsu_url
from src.interfaces.qt.components.comment_panel import CommentPanel
from src.interfaces.qt.components.project_card import ProjectCard
from src.interfaces.qt.components.task_card import TaskCard, resolve_task_status
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

        self._project_widgets = []
        self._current_project_cols = 0
        self._comment_card = None
        self._comment_anim = None

        self.setObjectName("ViewArtistBase")

        self.add_sidebar_button("projects", self.tr("Projects"), "🗂️", "folder.svg", lambda: self._switch_panel("projects"), active=True)
        self.add_sidebar_button("my_tasks", self.tr("My Tasks"), "📋", "list.svg", lambda: self._switch_panel("my_tasks"))
        self.add_sidebar_button("settings", self.tr("Settings"), "🔧", "settings.svg", lambda: self._switch_panel("settings"))

        self._build_content()
        self.vm.tasks_loaded.connect(self._on_tasks_loaded)
        self.vm.projects_loaded.connect(self._on_projects_loaded)
        self.vm.comment_counts_ready.connect(self._on_comment_counts_ready)
        self.vm.tasks_load_started.connect(self._on_tasks_load_started)
        self.vm.tasks_load_finished.connect(self._on_tasks_load_finished)
        self.vm.vcs_changes_ready.connect(self._on_vcs_changes_ready)
        self.vm.vcs_publish_finished.connect(self._on_vcs_publish_finished)
        self.vm.vcs_update_finished.connect(self._on_vcs_update_finished)
        self.vm.task_locks_ready.connect(self._on_task_locks_ready)
        self.vm.task_statuses_loaded.connect(self._on_task_statuses_loaded)
        self._connect_comments()
        self.vm.load_tasks()

    def _build_content(self) -> None:
        self.stacked_content = QStackedWidget()

        self.panel_projects = self._build_projects_panel()
        self.stacked_content.addWidget(self.panel_projects)

        self.panel_tasks = self._build_tasks_panel()
        self.stacked_content.addWidget(self.panel_tasks)

        self.panel_settings = self._build_settings_panel()
        self.stacked_content.addWidget(self.panel_settings)

        self.content_layout.addWidget(self.stacked_content, stretch=1)

    def _build_projects_panel(self) -> QFrame:
        panel = QFrame()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        header = QHBoxLayout()
        title = QLabel(self.tr("My Projects"))
        title.setObjectName("PageTitle")
        self.btn_projects_refresh = QPushButton(self.tr("⟳ Refresh"))
        self.btn_projects_refresh.setObjectName("SecondaryButton")
        self.btn_projects_refresh.setFixedSize(110, 35)
        self.btn_projects_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_projects_refresh.clicked.connect(self._refresh_tasks)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.btn_projects_refresh)
        layout.addLayout(header)

        self.projects_scroll_area = QScrollArea()
        self.projects_scroll_area.setWidgetResizable(True)
        self.projects_scroll_area.setObjectName("InvisibleScrollArea")
        self.projects_grid_widget = QWidget()
        self.projects_grid_widget.setObjectName("TransparentGridContainer")
        self.projects_grid_layout = QGridLayout(self.projects_grid_widget)
        self.projects_grid_layout.setSpacing(15)
        self.projects_grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.projects_scroll_area.setWidget(self.projects_grid_widget)
        layout.addWidget(self.projects_scroll_area, stretch=1)
        return panel

    def _build_tasks_panel(self) -> QFrame:
        panel = QFrame()
        layout_tasks = QVBoxLayout(panel)
        layout_tasks.setContentsMargins(0, 0, 0, 0)
        layout_tasks.setSpacing(20)

        header_layout = QHBoxLayout()

        self.btn_back_projects = QPushButton(self.tr("← Projects"))
        self.btn_back_projects.setObjectName("SecondaryButton")
        self.btn_back_projects.setFixedHeight(35)
        self.btn_back_projects.setCursor(Qt.PointingHandCursor)
        self.btn_back_projects.clicked.connect(lambda: self._switch_panel("projects"))

        lbl_title = QLabel(self.tr("My Assigned Tasks"))
        lbl_title.setObjectName("PageTitle")

        self.combo_projects = QComboBox()
        self.combo_projects.setObjectName("StandardComboBox")
        self.combo_projects.setFixedSize(250, 35)
        self.combo_projects.currentIndexChanged.connect(self._on_project_changed)

        self.combo_status = QComboBox()
        self.combo_status.setObjectName("StandardComboBox")
        self.combo_status.setFixedSize(180, 35)
        self.combo_status.addItem(self.tr("All Statuses"), "ALL")
        self.combo_status.currentIndexChanged.connect(self._apply_filters)

        self.btn_refresh = QPushButton(self.tr("⟳ Refresh"))
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.setFixedSize(110, 35)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setToolTip(self.tr("Fetch the latest updates for your assigned tasks."))
        self.btn_refresh.clicked.connect(self._refresh_tasks)

        self.btn_update_vcs = QPushButton(self.tr("⟳ Update from VCS"))
        self.btn_update_vcs.setObjectName("SecondaryButton")
        self.btn_update_vcs.setFixedHeight(35)
        self.btn_update_vcs.setCursor(Qt.PointingHandCursor)
        self.btn_update_vcs.setEnabled(False)
        self.btn_update_vcs.setToolTip(
            self.tr("Pull the selected project's latest revisions from the VCS.")
        )
        self.btn_update_vcs.clicked.connect(self._on_update_vcs_clicked)

        header_layout.addWidget(self.btn_back_projects)
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_refresh)
        header_layout.addWidget(self.btn_update_vcs)
        header_layout.addWidget(QLabel(self.tr("Project:")))
        header_layout.addWidget(self.combo_projects)
        header_layout.addWidget(QLabel(self.tr("Status:")))
        header_layout.addWidget(self.combo_status)

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

        self.comment_panel = CommentPanel(panel)
        self.comment_panel.hide()
        self.comment_splitter = QSplitter(Qt.Horizontal)
        self.comment_splitter.setChildrenCollapsible(False)
        self.comment_splitter.setHandleWidth(6)
        self.comment_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #1E293B; }"
            "QSplitter::handle:hover { background-color: #3B82F6; }"
        )
        self.comment_splitter.addWidget(self.scroll_area)
        self.comment_splitter.addWidget(self.comment_panel)
        self.comment_splitter.setStretchFactor(0, 1)
        self.comment_splitter.setStretchFactor(1, 0)
        self.comment_splitter.splitterMoved.connect(self._on_comment_splitter_moved)
        layout_tasks.addWidget(self.comment_splitter, stretch=1)
        return panel

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
        self._rearrange_project_grid()

    def _rearrange_project_grid(self) -> None:
        if not self._project_widgets:
            return
        viewport_width = self.projects_scroll_area.viewport().width()
        card_width = 320
        spacing = self.projects_grid_layout.spacing()
        cols = max(1, (viewport_width + spacing) // (card_width + spacing))
        if getattr(self, "_current_project_cols", 0) == cols:
            return
        self._current_project_cols = cols
        row, col = 0, 0
        for widget in self._project_widgets:
            self.projects_grid_layout.removeWidget(widget)
            self.projects_grid_layout.addWidget(widget, row, col)
            col += 1
            if col >= cols:
                col = 0
                row += 1

    # ------------------------------------------------------------------
    # Project grid
    # ------------------------------------------------------------------
    def _on_projects_loaded(self, projects: list) -> None:
        self._clear_project_grid()
        for project in projects or []:
            card = self._build_project_card(project)
            self._project_widgets.append(card)
        self._current_project_cols = 0
        self._rearrange_project_grid()

    def _build_project_card(self, project: dict) -> ProjectCard:
        project_id = str(project.get("id", ""))
        task_count = int(project.get("task_count", 0) or 0)
        card = ProjectCard(
            parent=self.projects_grid_widget,
            project_data={
                "id": project_id,
                "name": project.get("name", "Project"),
                "project_status_name": self.tr(f"{task_count} task(s)"),
            },
            user_role="artist",
            status={
                "project_dir": None,
                "is_installed": False,
                "is_corrupted": False,
                "badge_text": self.tr(f"{task_count} task(s)"),
                "sync_text": self.tr(f"🗂️ {task_count} task(s)"),
            },
            token=self._token,
            host=self._host,
            thumbnail_fetcher=self.vm.thumbnail_fetcher,
            on_install=lambda *args, **kwargs: None,
            on_launch=lambda *args, **kwargs: None,
            on_delete=lambda *args, **kwargs: None,
            on_open_kitsu=lambda sub_path, pid=project_id: self._open_kitsu(pid, sub_path),
            on_watchtower=lambda *args, **kwargs: None,
            on_open_tasks=lambda pid=project_id: self._open_project_tasks(pid),
            tasks_only=True,
        )
        return card

    def _open_project_tasks(self, project_id: str) -> None:
        index = self.combo_projects.findData(project_id)
        if index >= 0:
            self.combo_projects.blockSignals(True)
            self.combo_projects.setCurrentIndex(index)
            self.combo_projects.blockSignals(False)
        self._switch_panel("my_tasks")
        self._apply_filters()
        self.vm.load_task_statuses(project_id)

    def _open_kitsu(self, project_id: str, sub_path: str = "") -> None:
        base = kitsu_base_url(self._host or "")
        if base:
            self.open_kitsu_in_hub(f"{base}/productions/{project_id}{sub_path or ''}")

    def _open_task_kitsu(self, task_data: dict) -> None:
        url = task_kitsu_url(self.config_factory.get_kitsu_api_url(), task_data)
        if url:
            self.open_kitsu_in_hub(url)

    def _clear_project_grid(self) -> None:
        self._project_widgets.clear()
        while self.projects_grid_layout.count():
            child = self.projects_grid_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

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
        self.show_dashboard_content()
        self.set_active_sidebar_button(panel_id)
        indices = {"projects": 0, "my_tasks": 1, "settings": 2}
        self.stacked_content.setCurrentIndex(indices.get(panel_id, 0))
        if panel_id != "my_tasks":
            self._close_comments(instant=True)

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
        self.btn_projects_refresh.setEnabled(False)
        self.btn_projects_refresh.setText(self.tr("⟳ Refreshing…"))

    def _on_tasks_load_finished(self, _success: bool) -> None:
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText(self.tr("⟳ Refresh"))
        self.btn_projects_refresh.setEnabled(True)
        self.btn_projects_refresh.setText(self.tr("⟳ Refresh"))

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
        self._apply_filters()
        self.vm.load_task_statuses(self.combo_projects.currentData() or "ALL")

    def _on_project_changed(self, _index: int = 0) -> None:
        self._apply_filters()
        self.vm.load_task_statuses(self.combo_projects.currentData() or "ALL")

    def _on_task_statuses_loaded(self, project_id: str, statuses: list) -> None:
        # Ignore responses for a project the artist has already navigated away from.
        if (self.combo_projects.currentData() or "ALL") != project_id:
            return

        previous_selection = self.combo_status.currentData()
        self.combo_status.blockSignals(True)
        self.combo_status.clear()
        self.combo_status.addItem(self.tr("All Statuses"), "ALL")
        for status in statuses:
            name = status.get("name")
            if name:
                self.combo_status.addItem(name, name)

        index = self.combo_status.findData(previous_selection) if previous_selection else -1
        self.combo_status.setCurrentIndex(index if index >= 0 else 0)
        self.combo_status.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self, index: int = 0) -> None:
        self._clear_grid()

        selected_project_id = self.combo_projects.currentData()
        selected_status = self.combo_status.currentData()

        filtered_cards = self._cards
        if selected_project_id != "ALL":
            filtered_cards = [c for c in filtered_cards if c.project_id == selected_project_id]
        if selected_status and selected_status != "ALL":
            filtered_cards = [
                c for c in filtered_cards if resolve_task_status(c.task_data)[0] == selected_status
            ]

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
                comment_count=card.comment_count,
                unread_count=card.unread_count,
                on_comments_callback=lambda c=card: self._open_comments(c),
                on_kitsu_callback=self._open_task_kitsu,
            )
            task_card.set_lock_state(card.lock_owner, card.lock_is_mine)
            self._task_widgets.append(task_card)
            self._task_cards_by_id[str(card.task_data.get("id", ""))] = task_card

        self._current_cols = 0
        self._rearrange_grid()
        self._sync_update_vcs_button()

    # ------------------------------------------------------------------
    # VCS update flow
    # ------------------------------------------------------------------
    def _selected_project_card(self):
        selected_project_id = self.combo_projects.currentData()
        if not selected_project_id or selected_project_id == "ALL":
            return None
        return next(
            (c for c in self._cards if c.project_id == selected_project_id), None
        )

    def _sync_update_vcs_button(self) -> None:
        card = self._selected_project_card()
        enabled = (
            card is not None
            and card.vcs_enabled
            and not self.vm.is_vcs_update_running()
        )
        self.btn_update_vcs.setEnabled(enabled)
        if card is None:
            self.btn_update_vcs.setToolTip(
                self.tr("Select a specific project to update from the VCS.")
            )
        elif not card.vcs_enabled:
            self.btn_update_vcs.setToolTip(
                self.tr("This project is not under version control (NAS only).")
            )
        else:
            self.btn_update_vcs.setToolTip(
                self.tr("Pull the selected project's latest revisions from the VCS.")
            )

    def _on_update_vcs_clicked(self) -> None:
        card = self._selected_project_card()
        if card is None:
            return
        if self.vm.update_vcs(card.project_id, card.project_root):
            self.btn_update_vcs.setEnabled(False)

    def _on_vcs_update_finished(self, _project_id: str, _success: bool, _message: str) -> None:
        self._sync_update_vcs_button()

    # ------------------------------------------------------------------
    # File lock badges
    # ------------------------------------------------------------------
    def _on_task_locks_ready(self, locks: dict) -> None:
        for task_id, state in locks.items():
            widget = self._task_cards_by_id.get(str(task_id))
            if widget is not None:
                widget.set_lock_state(state.get("owner", ""), state.get("is_mine", False))

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

    # ------------------------------------------------------------------
    # Task comments drawer
    # ------------------------------------------------------------------
    def _connect_comments(self) -> None:
        self.comment_panel.close_requested.connect(self._close_comments)
        self.comment_panel.send_requested.connect(self._send_comment)
        self.comment_panel.checklist_toggled.connect(self.vm.comments.toggle_checklist)
        self.vm.comments.comments_loaded.connect(self._on_comments_loaded)
        self.vm.comments.comments_failed.connect(lambda error: self.comment_panel.set_error(error))
        self.vm.comments.comment_posted.connect(self._on_comment_posted)
        self.vm.comments.checklist_updating.connect(self._on_checklist_updating)
        self.vm.comments.seen_updated.connect(self._on_seen_updated)

    def _open_comments(self, card) -> None:
        self._comment_card = card
        self.comment_panel.set_task(card.task_data)
        self.comment_panel.set_loading(True)
        self.comment_panel.show()
        self._animate_comment_width(self.vm.comment_panel_width())
        self.vm.comments.load(card.task_data, mark_seen=True)

    def _close_comments(self, instant: bool = False) -> None:
        if self._comment_anim is not None:
            self._comment_anim.stop()
        self.comment_panel.hide()
        self._comment_card = None
        self._apply_comment_width(0)

    def _animate_comment_width(self, target: int) -> None:
        if self._comment_anim is not None:
            self._comment_anim.stop()
            self._comment_anim.deleteLater()
        self._comment_anim = QVariantAnimation(self)
        self._comment_anim.setDuration(180)
        self._comment_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._comment_anim.setStartValue(0)
        self._comment_anim.setEndValue(int(target))
        self._comment_anim.valueChanged.connect(
            lambda value: self._apply_comment_width(int(value))
        )
        self._comment_anim.start()

    def _apply_comment_width(self, width: int) -> None:
        total = max(1, self.comment_splitter.width())
        if width <= 0:
            self.comment_splitter.setSizes([total, 0])
            return
        width = max(CommentPanel.MIN_WIDTH, min(int(width), int(total * 0.6)))
        self.comment_splitter.setSizes([max(1, total - width), width])
        self._current_cols = 0
        self._rearrange_grid()

    def _on_comment_splitter_moved(self, _pos: int, _index: int) -> None:
        sizes = self.comment_splitter.sizes()
        if len(sizes) == 2 and sizes[1] > 0:
            self.vm.set_comment_panel_width(sizes[1])
        self._current_cols = 0
        self._rearrange_grid()

    def _send_comment(self, text: str) -> None:
        self.comment_panel.set_posting(True)
        self.vm.comments.post(text)

    def _on_checklist_updating(self, busy: bool) -> None:
        self.comment_panel.set_checklist_enabled(not busy)

    def _on_comments_loaded(self, task_id: str, comments: list) -> None:
        if self._comment_card is None:
            return
        if str(self._comment_card.task_data.get("id", "")) != str(task_id):
            return
        self.comment_panel.set_comments(comments)
        self.comment_panel.set_posting(False)

    def _on_comment_posted(self, task_id: str, success: bool, message: str) -> None:
        self.comment_panel.set_posting(False)
        if success:
            self.comment_panel.clear_composer()
        else:
            self.comment_panel.set_error(message)

    def _on_comment_counts_ready(self, counts: dict) -> None:
        for task_id, payload in (counts or {}).items():
            widget = self._task_cards_by_id.get(str(task_id))
            if widget is not None:
                widget.set_comment_counts(
                    payload.get("total", 0), payload.get("unread", 0)
                )

    def _on_seen_updated(self, task_id: str) -> None:
        widget = self._task_cards_by_id.get(str(task_id))
        if widget is not None:
            widget.set_comment_counts(widget.comment_count, 0)
        for card in self._cards:
            if str(card.task_data.get("id", "")) == str(task_id):
                card.unread_count = 0
                break

    def _clear_grid(self) -> None:
        self._task_widgets.clear()
        self._task_cards_by_id.clear()

        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
