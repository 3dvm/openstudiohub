# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/task_board_widget.py
# Architectural role: UI Widget / PM-TD project task board
# =========================================================================================

"""PM/TD task board with table/card views, comments drawer and assignment."""

from pathlib import Path

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtGui import QIcon, QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.interfaces.qt.components.assignee_dialog import AssigneeDialog
from src.interfaces.qt.components.comment_panel import CommentPanel
from src.interfaces.qt.components.pm_task_card import PmTaskCard, _comment_icon
from src.interfaces.qt.components.task_card import resolve_task_status
from src.interfaces.qt.workers.task_board_workers import FetchThumbnailsWorker


class TaskBoardWidget(QFrame):
    THUMB_SIZE = 56

    def __init__(self, parent, viewmodel, on_open_kitsu_callback=None) -> None:
        super().__init__(parent)
        self.vm = viewmodel
        self.on_open_kitsu_callback = on_open_kitsu_callback
        self._pending_project_id = ""
        self._thumbnails: dict = {}
        self._thumb_labels: dict = {}
        self._thumb_cards: dict = {}
        self._comment_buttons: dict = {}
        self._kitsu_buttons: dict = {}
        self._card_widgets: dict = {}
        self._current_cols = 0
        self._comment_task = None
        self._comment_anim = None

        self.setObjectName("TaskBoardWidgetBase")
        self._build_ui()
        self._connect()
        self.vm.load_projects()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel(self.tr("Tasks"))
        title.setObjectName("PageTitle")
        header.addWidget(title)

        self.combo_projects = QComboBox()
        self.combo_projects.setObjectName("StandardComboBox")
        self.combo_projects.setFixedSize(220, 34)
        self.combo_projects.currentIndexChanged.connect(self._on_project_changed)
        header.addWidget(self.combo_projects)

        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Search entity or type…"))
        self.search.setFixedWidth(190)
        self.search.setObjectName("FormInput")
        self.search.textChanged.connect(lambda *_: self._render_current_view())
        header.addWidget(self.search)

        self.combo_status = QComboBox()
        self.combo_status.setObjectName("StandardComboBox")
        self.combo_status.setFixedSize(160, 34)
        self.combo_status.addItem(self.tr("All Statuses"), "ALL")
        self.combo_status.currentIndexChanged.connect(lambda *_: self._render_current_view())
        header.addWidget(self.combo_status)

        self.btn_refresh = QPushButton(self.tr("⟳ Refresh"))
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.setFixedSize(110, 34)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh)
        header.addWidget(self.btn_refresh)

        header.addStretch()

        self.lbl_count = QLabel("0")
        self.lbl_count.setObjectName("MutedLabel")
        header.addWidget(self.lbl_count)

        self.btn_view_table = QToolButton()
        self.btn_view_table.setCheckable(True)
        self.btn_view_table.setToolTip(self.tr("Table view"))
        self.btn_view_table.setCursor(Qt.PointingHandCursor)
        self.btn_view_table.setIcon(self._colored_icon("list.svg", "#E2E8F0"))
        self.btn_view_table.clicked.connect(lambda: self.vm.set_view_mode("table"))

        self.btn_view_cards = QToolButton()
        self.btn_view_cards.setCheckable(True)
        self.btn_view_cards.setToolTip(self.tr("Card view"))
        self.btn_view_cards.setCursor(Qt.PointingHandCursor)
        self.btn_view_cards.setIcon(self._colored_icon("layout-grid.svg", "#E2E8F0"))
        self.btn_view_cards.clicked.connect(lambda: self.vm.set_view_mode("cards"))

        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._view_group.addButton(self.btn_view_table)
        self._view_group.addButton(self.btn_view_cards)
        for button in (self.btn_view_table, self.btn_view_cards):
            button.setObjectName("BoardToggleButton")
            header.addWidget(button)

        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Entity"),
                self.tr("Type"),
                self.tr("Status"),
                self.tr("Responsibles"),
                self.tr("Comments"),
                self.tr("Kitsu"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(False)
        self.table.setObjectName("BoardTable")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 120), (2, 120), (3, 220), (4, 100), (5, 90)):
            self.table.setColumnWidth(column, width)
        self.stack.addWidget(self.table)

        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setObjectName("InvisibleScrollArea")
        self.cards_container = QWidget()
        self.cards_container.setObjectName("TransparentGridContainer")
        self.cards_grid = QGridLayout(self.cards_container)
        self.cards_grid.setSpacing(15)
        self.cards_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.cards_scroll.setWidget(self.cards_container)
        self.stack.addWidget(self.cards_scroll)

        self.comment_panel = CommentPanel(self)
        self.comment_panel.hide()
        self.comment_splitter = QSplitter(Qt.Horizontal)
        self.comment_splitter.setChildrenCollapsible(False)
        self.comment_splitter.setHandleWidth(6)
        self.comment_splitter.addWidget(self.stack)
        self.comment_splitter.addWidget(self.comment_panel)
        self.comment_splitter.setStretchFactor(0, 1)
        self.comment_splitter.setStretchFactor(1, 0)
        self.comment_splitter.splitterMoved.connect(self._on_comment_splitter_moved)
        layout.addWidget(self.comment_splitter, stretch=1)

    def _connect(self) -> None:
        self.vm.projects_loaded.connect(self._on_projects_loaded)
        self.vm.tasks_loaded.connect(self._on_tasks_loaded)
        self.vm.comment_counts_ready.connect(self._on_comment_counts)
        self.vm.assignment_finished.connect(self._on_assignment_finished)
        self.vm.view_mode_changed.connect(self._apply_view_mode)
        self.vm.comments.comments_loaded.connect(self._on_comments_loaded)
        self.vm.comments.comments_failed.connect(lambda error: self.comment_panel.set_error(error))
        self.vm.comments.comment_posted.connect(self._on_comment_posted)
        self.vm.comments.checklist_updating.connect(self._on_checklist_updating)
        self.vm.comments.seen_updated.connect(self._on_seen_updated)
        self.comment_panel.close_requested.connect(self._close_comments)
        self.comment_panel.send_requested.connect(self._send_comment)
        self.comment_panel.checklist_toggled.connect(self.vm.comments.toggle_checklist)

    # ------------------------------------------------------------------
    # Projects / tasks
    # ------------------------------------------------------------------
    def select_project(self, project_id: str) -> None:
        project_id = str(project_id or "")
        index = self.combo_projects.findData(project_id)
        if index >= 0:
            self.combo_projects.blockSignals(True)
            self.combo_projects.setCurrentIndex(index)
            self.combo_projects.blockSignals(False)
        else:
            self._pending_project_id = project_id
        self.vm.select_project(project_id)

    def _on_projects_loaded(self, projects: list) -> None:
        self.combo_projects.blockSignals(True)
        self.combo_projects.clear()
        for project in projects or []:
            self.combo_projects.addItem(
                project.get("name", "Project"), str(project.get("id", ""))
            )
        self.combo_projects.blockSignals(False)

        target = self._pending_project_id or self.vm.current_project_id
        if not target and projects:
            target = str(projects[0].get("id", ""))
        if not target:
            return
        self._pending_project_id = ""
        index = self.combo_projects.findData(target)
        if index >= 0:
            self.combo_projects.blockSignals(True)
            self.combo_projects.setCurrentIndex(index)
            self.combo_projects.blockSignals(False)
        if target != self.vm.current_project_id:
            self.vm.select_project(target)

    def _on_project_changed(self, _index: int = 0) -> None:
        project_id = str(self.combo_projects.currentData() or "")
        if project_id:
            self.vm.select_project(project_id)

    def refresh(self) -> None:
        project_id = self.vm.current_project_id
        if project_id:
            self.vm.load_tasks(project_id)

    def _on_tasks_loaded(self, project_id: str, tasks: list) -> None:
        self._rebuild_status_filter(tasks)
        self._load_thumbnails(tasks)
        self._render_current_view()

    def _rebuild_status_filter(self, tasks: list) -> None:
        previous = self.combo_status.currentData()
        names = []
        for task in tasks or []:
            name = resolve_task_status(task)[0]
            if name and name not in names:
                names.append(name)
        self.combo_status.blockSignals(True)
        self.combo_status.clear()
        self.combo_status.addItem(self.tr("All Statuses"), "ALL")
        for name in sorted(names):
            self.combo_status.addItem(name, name)
        index = self.combo_status.findData(previous) if previous else -1
        self.combo_status.setCurrentIndex(index if index >= 0 else 0)
        self.combo_status.blockSignals(False)

    def _filtered_tasks(self) -> list:
        tasks = self.vm.tasks
        status = self.combo_status.currentData()
        if status and status != "ALL":
            tasks = [t for t in tasks if resolve_task_status(t)[0] == status]
        needle = self.search.text().strip().lower()
        if needle:
            tasks = [
                t
                for t in tasks
                if needle
                in " ".join(
                    str(t.get(key, ""))
                    for key in ("entity_name", "task_type_name", "project_name", "name")
                ).lower()
            ]
        return tasks

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render_current_view(self) -> None:
        self._comment_buttons.clear()
        self._kitsu_buttons.clear()
        self._card_widgets.clear()
        self._thumb_labels.clear()
        self._thumb_cards.clear()
        tasks = self._filtered_tasks()
        self.lbl_count.setText(str(len(tasks)))

        cards = self.vm.view_mode == "cards"
        self.btn_view_table.setChecked(not cards)
        self.btn_view_cards.setChecked(cards)
        if cards:
            self._render_cards(tasks)
            self.stack.setCurrentIndex(1)
        else:
            self._render_table(tasks)
            self.stack.setCurrentIndex(0)

    def _render_table(self, tasks: list) -> None:
        self.table.setRowCount(0)
        for row, task in enumerate(tasks):
            self.table.insertRow(row)
            self.table.setRowHeight(row, 64)

            self.table.setCellWidget(row, 0, self._entity_cell(task))
            self.table.setCellWidget(row, 1, self._text_cell(task.get("task_type_name", "")))
            self.table.setCellWidget(row, 2, self._status_cell(task))
            self.table.setCellWidget(row, 3, self._assignees_cell(task))

            task_id = str(task.get("id", ""))
            button = self._comment_button(task)
            self._comment_buttons[task_id] = button
            container = QWidget()
            cell_layout = QHBoxLayout(container)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.addWidget(button)
            self.table.setCellWidget(row, 4, container)

            kitsu = QToolButton()
            kitsu.setText(self.tr("Kitsu"))
            kitsu.setCursor(Qt.PointingHandCursor)
            kitsu.setObjectName("BoardKitsuButton")
            kitsu.clicked.connect(
                lambda _=False, t=task: self._open_task_kitsu(t)
            )
            self._kitsu_buttons[task_id] = kitsu
            kitsu_container = QWidget()
            kitsu_layout = QHBoxLayout(kitsu_container)
            kitsu_layout.setContentsMargins(0, 0, 0, 0)
            kitsu_layout.addWidget(kitsu)
            self.table.setCellWidget(row, 5, kitsu_container)

    def _open_task_kitsu(self, task: dict) -> None:
        if self.on_open_kitsu_callback is not None:
            self.on_open_kitsu_callback(task)

    def _entity_cell(self, task: dict) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(8)

        thumb = QLabel()
        thumb.setFixedSize(self.THUMB_SIZE, self.THUMB_SIZE)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setObjectName("ThumbnailPlaceholder")
        thumb.setText("—")
        entity_id = str(task.get("entity_id", "") or "")
        if entity_id:
            self._thumb_labels.setdefault(entity_id, []).append(thumb)
            self._apply_thumbnail_label(thumb, self._thumbnails.get(entity_id))
        row.addWidget(thumb)

        name = QLabel(task.get("entity_name") or task.get("name") or "—")
        name.setObjectName("BoardName")
        row.addWidget(name, stretch=1)
        return container

    def _text_cell(self, text: str) -> QLabel:
        label = QLabel(str(text or "—"))
        label.setObjectName("BoardCell")
        return label

    def _status_cell(self, task: dict) -> QWidget:
        name, color = resolve_task_status(task)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        badge = QLabel(name.upper())
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedHeight(20)
        badge.setStyleSheet(
            f"background-color: {color}; color: white; border-radius: 10px;"
            " font-size: 9px; font-weight: bold; padding: 0 8px;"
        )
        layout.addWidget(badge)
        layout.addStretch()
        return container

    def _assignees_cell(self, task: dict) -> QWidget:
        names = self._assignee_names(task)
        text = ", ".join(names) if names else self.tr("Unassigned")
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        if self.vm.assignment_allowed():
            button = QToolButton()
            button.setText(text)
            button.setToolTip(self.tr("Edit responsibles"))
            button.setCursor(Qt.PointingHandCursor)
            button.setObjectName("BoardActionButton")
            button.clicked.connect(lambda _=False, t=task: self._edit_assignees(t))
            layout.addWidget(button)
        else:
            label = QLabel(text)
            label.setObjectName("BoardCell")
            layout.addWidget(label)
        layout.addStretch()
        return container

    def _comment_button(self, task: dict) -> QToolButton:
        button = QToolButton()
        button.setCursor(Qt.PointingHandCursor)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._apply_comment_badge(button, task)
        button.clicked.connect(lambda _=False, t=task: self._open_comments(t))
        return button

    def _apply_comment_badge(self, button: QToolButton, task: dict) -> None:
        total = int(task.get("_comment_count", 0) or 0)
        unread = int(task.get("_unread_count", 0) or 0)
        color = "#FFFFFF" if unread else "#CBD5E1"
        button.setText(str(total))
        button.setIcon(_comment_icon(color))
        background, border = ("#F97316", "#FB923C") if unread else ("rgba(15,23,42,0.88)", "#334155")
        button.setStyleSheet(
            f"QToolButton {{ background-color: {background}; color: {color};"
            f" border: 1px solid {border}; border-radius: 10px; padding: 0 8px;"
            " font-size: 11px; font-weight: bold; }"
        )
        button.setToolTip(self.tr(f"{total} comment(s), {unread} new"))

    def _render_cards(self, tasks: list) -> None:
        self._clear_cards()
        for task in tasks:
            entity_id = str(task.get("entity_id", "") or "")
            card = PmTaskCard(
                self.cards_container,
                task,
                self._thumbnails.get(entity_id),
                self.vm.assignment_allowed(),
            )
            card.comments_requested.connect(lambda t=task: self._open_comments(t))
            card.assignees_requested.connect(lambda t=task: self._edit_assignees(t))
            card.kitsu_requested.connect(lambda t=task: self._open_task_kitsu(t))
            self._card_widgets[str(task.get("id", ""))] = card
            if entity_id:
                self._thumb_cards.setdefault(entity_id, []).append(card)
            self.cards_grid.addWidget(card)
        self._current_cols = 0
        self._rearrange_cards()

    def _clear_cards(self) -> None:
        self._card_widgets.clear()
        while self.cards_grid.count():
            child = self.cards_grid.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------
    def _load_thumbnails(self, tasks: list) -> None:
        entity_ids = sorted(
            {str(t.get("entity_id", "")) for t in tasks or [] if t.get("entity_id")}
        )
        if not entity_ids or self.vm.workers.is_running("thumbnails"):
            return
        worker = FetchThumbnailsWorker(self.vm.token, self.vm.host, entity_ids)
        worker.image_ready.connect(self._on_thumbnail)
        self.vm.workers.start("thumbnails", worker)

    def _on_thumbnail(self, entity_id: str, data: bytes) -> None:
        self._thumbnails[str(entity_id)] = data
        for label in self._thumb_labels.get(str(entity_id), []):
            self._apply_thumbnail_label(label, data)
        for card in self._thumb_cards.get(str(entity_id), []):
            card.set_thumbnail(data)

    def _apply_thumbnail_label(self, label: QLabel, data) -> None:
        if not data:
            return
        image = QImage.fromData(data)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image).scaled(
            self.THUMB_SIZE,
            self.THUMB_SIZE,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        label.setPixmap(pixmap)
        label.setText("")

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------
    @staticmethod
    def _assignee_names(task: dict) -> list:
        names = []
        for person in task.get("assignees") or []:
            if isinstance(person, dict):
                name = person.get("full_name") or person.get("email")
            else:
                name = str(person)
            if name:
                names.append(str(name))
        return names

    @staticmethod
    def _assignee_ids(task: dict) -> list:
        ids = []
        for person in task.get("assignees") or []:
            if isinstance(person, dict) and person.get("id"):
                ids.append(str(person["id"]))
            elif not isinstance(person, dict) and person:
                ids.append(str(person))
        return ids

    def _edit_assignees(self, task: dict) -> None:
        if not self.vm.assignment_allowed():
            return
        dialog = AssigneeDialog(self, self.vm.persons, self._assignee_ids(task))
        if dialog.exec() != QDialog.Accepted:
            return
        current = set(self._assignee_ids(task))
        chosen = set(dialog.selected_ids())
        self.vm.apply_assignees(task, sorted(chosen - current), sorted(current - chosen))

    def _on_assignment_finished(self, _task_id: str, success: bool, _message: str) -> None:
        if success:
            self._render_current_view()

    # ------------------------------------------------------------------
    # Comments drawer
    # ------------------------------------------------------------------
    def _open_comments(self, task: dict) -> None:
        self._comment_task = task
        self.comment_panel.set_task(task)
        self.comment_panel.set_loading(True)
        self.comment_panel.show()
        self._animate_comment_width(self.vm.comment_panel_width())
        self.vm.comments.load(task, mark_seen=True)

    def _close_comments(self, instant: bool = False) -> None:
        if self._comment_anim is not None:
            self._comment_anim.stop()
        self.comment_panel.hide()
        self._comment_task = None
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
        self._rearrange_cards()

    def _on_comment_splitter_moved(self, _pos: int, _index: int) -> None:
        sizes = self.comment_splitter.sizes()
        if len(sizes) == 2 and sizes[1] > 0:
            self.vm.set_comment_panel_width(sizes[1])
        self._current_cols = 0
        self._rearrange_cards()

    def _send_comment(self, text: str) -> None:
        self.comment_panel.set_posting(True)
        self.vm.comments.post(text)

    def _on_checklist_updating(self, busy: bool) -> None:
        self.comment_panel.set_checklist_enabled(not busy)

    def _on_comments_loaded(self, task_id: str, comments: list) -> None:
        if self._comment_task is None:
            return
        if str(self._comment_task.get("id", "")) != str(task_id):
            return
        self.comment_panel.set_comments(comments)
        self.comment_panel.set_posting(False)

    def _on_comment_posted(self, task_id: str, success: bool, message: str) -> None:
        self.comment_panel.set_posting(False)
        if success:
            self.comment_panel.clear_composer()
        else:
            self.comment_panel.set_error(message)

    def _on_comment_counts(self, counts: dict) -> None:
        tasks = {str(task.get("id", "")): task for task in self.vm.tasks}
        for task_id, button in self._comment_buttons.items():
            task = tasks.get(str(task_id))
            if task is not None:
                self._apply_comment_badge(button, task)
        for task_id, card in self._card_widgets.items():
            task = tasks.get(str(task_id))
            if task is not None:
                card.set_comment_counts(
                    task.get("_comment_count", 0), task.get("_unread_count", 0)
                )

    def _on_seen_updated(self, task_id: str) -> None:
        for task in self.vm.tasks:
            if str(task.get("id", "")) == str(task_id):
                task["_unread_count"] = 0
                button = self._comment_buttons.get(str(task_id))
                if button is not None:
                    self._apply_comment_badge(button, task)
                card = self._card_widgets.get(str(task_id))
                if card is not None:
                    card.set_comment_counts(task.get("_comment_count", 0), 0)
                break

    # ------------------------------------------------------------------
    # View mode / layout
    # ------------------------------------------------------------------
    def _apply_view_mode(self, mode: str) -> None:
        self._render_current_view()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._rearrange_cards()

    def _rearrange_cards(self) -> None:
        widgets = list(self._card_widgets.values())
        if not widgets:
            return
        viewport_width = self.cards_scroll.viewport().width()
        card_width = 320
        spacing = self.cards_grid.spacing()
        cols = max(1, (viewport_width + spacing) // (card_width + spacing))
        if self._current_cols == cols:
            return
        self._current_cols = cols
        row, col = 0, 0
        for widget in widgets:
            self.cards_grid.removeWidget(widget)
            self.cards_grid.addWidget(widget, row, col)
            col += 1
            if col >= cols:
                col = 0
                row += 1

    @staticmethod
    def _colored_icon(name: str, color: str) -> QIcon:
        path = Path("assets/icons") / name
        if not path.exists():
            return QIcon()
        try:
            svg = path.read_text(encoding="utf-8").replace("currentColor", color)
            pixmap = QPixmap()
            pixmap.loadFromData(svg.encode("utf-8"), "SVG")
            return QIcon(pixmap)
        except Exception:  # noqa: BLE001
            return QIcon(str(path))
