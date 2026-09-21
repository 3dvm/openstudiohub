# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/blend_builder_widget.py
# Architectural role: UI Widget / Batch Entity Genesis Tool
# =========================================================================================

"""Batch entity builder widget (PM wizard).

Coordinates the PipelineWizard stepper and the entity table, delegating all
data access and spawning to ``BlendBuilderViewModel``.
"""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.domain.production.entities import Task
from src.domain.production.naming import NamingPolicy
from src.domain.production.value_objects import EntityType
from src.interfaces.qt.components.pipeline_wizard import PipelineWizardWidget
from src.interfaces.qt.components.progress_dialog import SpawningProgressDialog
from src.interfaces.qt.viewmodels.blend_builder_viewmodel import BlendBuilderViewModel


class BlendBuilderWidget(QFrame):
    def __init__(self, parent, viewmodel: BlendBuilderViewModel, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.vm = viewmodel

        self.project_map = {}
        self.edit_action_mode = "SPAWN"
        self.task_checkboxes = {}
        self._table_mode = ""
        self._pending_project_name = ""

        self.setObjectName("TransparentGridContainer")
        self._build_ui()
        self._connect_signals()

        self.vm.load_projects()

    def _connect_signals(self) -> None:
        self.vm.projects_loaded.connect(self._on_projects_loaded)
        self.vm.editorial_status_loaded.connect(self._render_editorial_status)
        self.vm.assets_loaded.connect(self._render_assets)
        self.vm.shots_loaded.connect(self._render_shots)
        self.vm.sequences_loaded.connect(self._render_sequences)
        self.vm.install_progress.connect(self._on_install_progress)
        self.vm.install_finished.connect(self._on_install_finished)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(20)

        project_layout = QHBoxLayout()
        lbl_proj = QLabel(self.tr("Active Project:"))
        lbl_proj.setObjectName("InputLabel")

        self.combo_projects = QComboBox()
        self.combo_projects.setObjectName("StandardComboBox")
        self.combo_projects.setFixedSize(250, 35)
        self.combo_projects.currentIndexChanged.connect(self._on_project_changed)

        project_layout.addWidget(lbl_proj)
        project_layout.addWidget(self.combo_projects)
        project_layout.addStretch()
        main_layout.addLayout(project_layout)

        self.wizard = PipelineWizardWidget(self)
        self.wizard.action_requested.connect(self._execute_pipeline_step)
        self.wizard.step_changed.connect(self.change_step)
        main_layout.addWidget(self.wizard)

        self.stack = QStackedWidget()

        # PAGE 0: MANUAL STORYBOARD BREAKDOWN
        self.page_storyboard = QWidget()
        sb_layout = QVBoxLayout(self.page_storyboard)
        sb_layout.setContentsMargins(0, 0, 0, 0)

        lbl_sb_desc = QLabel(self.tr("Enter the sequences (e.g. SQ010) identified during the script breakdown. This will register them in Kitsu and spawn their physical .blend files."))
        lbl_sb_desc.setObjectName("PageDescription")
        lbl_sb_desc.setWordWrap(True)
        sb_layout.addWidget(lbl_sb_desc)

        input_layout = QHBoxLayout()
        self.input_seq = QLineEdit()
        self.input_seq.setObjectName("FormInput")
        self.input_seq.setPlaceholderText(self.tr("Enter Sequence Name (e.g. SQ010) and press Enter"))
        self.input_seq.setFixedSize(300, 35)
        self.input_seq.returnPressed.connect(self._add_sequence_to_list)

        self.btn_add_seq = QPushButton(self.tr("Add"))
        self.btn_add_seq.setObjectName("SecondaryButton")
        self.btn_add_seq.setFixedSize(80, 35)
        self.btn_add_seq.clicked.connect(self._add_sequence_to_list)

        input_layout.addWidget(self.input_seq)
        input_layout.addWidget(self.btn_add_seq)
        input_layout.addStretch()
        sb_layout.addLayout(input_layout)

        self.list_sequences = QListWidget()
        self.list_sequences.setObjectName("FormInput")
        sb_layout.addWidget(self.list_sequences)

        self.btn_clear_seq = QPushButton(self.tr("Clear List"))
        self.btn_clear_seq.setObjectName("LinkButton")
        self.btn_clear_seq.setCursor(Qt.PointingHandCursor)
        self.btn_clear_seq.clicked.connect(self.list_sequences.clear)
        sb_layout.addWidget(self.btn_clear_seq, alignment=Qt.AlignRight)

        self.stack.addWidget(self.page_storyboard)

        # PAGE 1: EDITORIAL RADIOGRAPHY
        self.page_editorial = QWidget()
        edit_layout = QVBoxLayout(self.page_editorial)
        edit_layout.setContentsMargins(0, 0, 0, 0)

        lbl_edit_desc = QLabel(self.tr("Editorial Master configuration and assignment."))
        lbl_edit_desc.setObjectName("PageDescription")
        edit_layout.addWidget(lbl_edit_desc)

        frame_edit = QFrame()
        frame_edit.setObjectName("CardFrame")
        flayout = QVBoxLayout(frame_edit)
        flayout.setSpacing(10)

        self.lbl_edit_filename = QLabel(self.tr("File: Scanning..."))
        self.lbl_edit_version = QLabel(self.tr("Version: --"))
        self.lbl_edit_editor = QLabel(self.tr("Assigned to: --"))
        self.lbl_edit_status = QLabel(self.tr("Status: --"))

        for lbl in [self.lbl_edit_filename, self.lbl_edit_version, self.lbl_edit_editor, self.lbl_edit_status]:
            lbl.setObjectName("FormInput")
            flayout.addWidget(lbl)

        edit_layout.addWidget(frame_edit)
        edit_layout.addStretch()

        self.stack.addWidget(self.page_editorial)

        # PAGE 2: KANBAN TABLE
        self.page_entities = QWidget()
        ent_layout = QVBoxLayout(self.page_entities)
        ent_layout.setContentsMargins(0, 0, 0, 0)

        controls_layout = QHBoxLayout()
        self.lbl_kpi_total = self._create_kpi_label(self.tr("Total Entries: 0"))
        self.lbl_kpi_shots = self._create_kpi_label(self.tr("Shots: 0"))
        self.lbl_kpi_assets = self._create_kpi_label(self.tr("Assets: 0"))

        controls_layout.addWidget(self.lbl_kpi_total)
        controls_layout.addWidget(self.lbl_kpi_shots)
        controls_layout.addWidget(self.lbl_kpi_assets)
        controls_layout.addStretch()

        self.btn_open_kitsu_assets = QPushButton(self.tr("Assign Artists in Kitsu"))
        self.btn_open_kitsu_assets.setObjectName("SecondaryButton")
        self.btn_open_kitsu_assets.setCursor(Qt.PointingHandCursor)
        self.btn_open_kitsu_assets.clicked.connect(self._open_kitsu_assets)
        self.btn_open_kitsu_assets.hide()
        controls_layout.addWidget(self.btn_open_kitsu_assets)

        ent_layout.addLayout(controls_layout)

        self.panel_tasks = QWidget()
        self.layout_tasks = QHBoxLayout(self.panel_tasks)
        self.layout_tasks.setContentsMargins(0, 10, 0, 10)

        lbl_tasks = QLabel(self.tr("Select Tasks to Spawn:"))
        lbl_tasks.setObjectName("InputLabel")
        self.layout_tasks.addWidget(lbl_tasks)

        self.layout_checkboxes = QHBoxLayout()
        self.layout_tasks.addLayout(self.layout_checkboxes)
        self.layout_tasks.addStretch()

        self.task_checkboxes = {}

        ent_layout.addWidget(self.panel_tasks)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("DataGrid")
        self.table.setHorizontalHeaderLabels(["", self.tr("Entity Name"), self.tr("Type"), self.tr("Parent Sequence"), self.tr("Frame Range"), self.tr("Kitsu Status")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        ent_layout.addWidget(self.table, stretch=1)
        self.stack.addWidget(self.page_entities)

        # PAGE 3: INSTALL REQUIRED (gates the whole generation interface)
        self.page_install = QWidget()
        install_layout = QVBoxLayout(self.page_install)
        install_layout.setContentsMargins(0, 0, 0, 0)
        install_layout.setAlignment(Qt.AlignCenter)

        install_card = QFrame()
        install_card.setObjectName("CardFrame")
        card_layout = QVBoxLayout(install_card)
        card_layout.setSpacing(18)
        card_layout.setAlignment(Qt.AlignCenter)

        lbl_install_title = QLabel(self.tr("Local Workspace Not Installed"))
        lbl_install_title.setObjectName("H2Title")
        lbl_install_title.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(lbl_install_title)

        self.lbl_install_status = QLabel(
            self.tr(
                "This project must be installed on your disk (VCS checkout + isolated Blender) "
                "before assets can be generated."
            )
        )
        self.lbl_install_status.setObjectName("PageDescription")
        self.lbl_install_status.setWordWrap(True)
        self.lbl_install_status.setAlignment(Qt.AlignCenter)
        self.lbl_install_status.setMaximumWidth(560)
        card_layout.addWidget(self.lbl_install_status, alignment=Qt.AlignCenter)

        self.btn_install_project = QPushButton(self.tr("Install Project"))
        self.btn_install_project.setObjectName("OrangeCTA")
        self.btn_install_project.setCursor(Qt.PointingHandCursor)
        self.btn_install_project.setFixedSize(220, 40)
        self.btn_install_project.clicked.connect(self._start_project_install)
        card_layout.addWidget(self.btn_install_project, alignment=Qt.AlignCenter)

        install_layout.addWidget(install_card)
        self.stack.addWidget(self.page_install)

        main_layout.addWidget(self.stack, stretch=1)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _create_kpi_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("KPILabel")
        return lbl

    def _create_colored_icon(self, icon_path: Path, color_hex: str) -> QIcon:
        """Tint a monochromatic SVG icon at runtime (folder marker)."""
        if not icon_path.exists():
            return QIcon()
        try:
            with open(icon_path, "r", encoding="utf-8") as handle:
                svg_content = handle.read()
            svg_content = svg_content.replace("currentColor", color_hex)
            svg_content = svg_content.replace("#000000", color_hex)
            pixmap = QPixmap()
            pixmap.loadFromData(svg_content.encode("utf-8"), "SVG")
            return QIcon(pixmap)
        except Exception:  # noqa: BLE001
            return QIcon(str(icon_path))

    def _status_dot(self, color_hex: str) -> QLabel:
        dot = QLabel()
        dot.setFixedSize(12, 12)
        dot.setStyleSheet(f"background-color: {color_hex}; border-radius: 6px;")
        return dot

    def _task_filepath(self, task_info: dict) -> str:
        """Resolve the linked file path across asset/shot audit shapes."""
        if not task_info:
            return ""
        raw = task_info.get("raw_task") or {}
        return task_info.get("filepath") or ((raw.get("data") or {}).get("filepath") or "")

    def _build_task_cell(self, entity: dict, task_info: dict | None, task_type_name: str) -> QWidget:
        """Status dot + folder link button for one entity/task-type intersection."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        if not task_info:
            layout.addWidget(self._status_dot("#4B5563"))
            return widget

        ready = bool(task_info.get("has_file"))
        layout.addWidget(self._status_dot("#10B981" if ready else "#F59E0B"))

        btn = QPushButton()
        btn.setObjectName("TaskLinkButton")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(24, 24)
        btn.setIconSize(QSize(16, 16))
        btn.setIcon(self._create_colored_icon(Path("assets/icons/folder.svg"), "#3B82F6"))
        btn.setToolTip(self._task_filepath(task_info) or self.tr("Link a physical file to this task"))
        btn.clicked.connect(
            lambda _=False, e=entity, ti=task_info, tt=task_type_name: self._open_task_file_dialog(e, ti, tt)
        )
        layout.addWidget(btn)
        return widget

    def _render_task_checkboxes(self, task_types: list) -> None:
        """Rebuild the spawn-task selector so it always matches the current step."""
        while self.layout_checkboxes.count():
            child = self.layout_checkboxes.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.task_checkboxes.clear()
        for tt_name in task_types:
            chk = QCheckBox(tt_name)
            chk.setChecked(True)
            self.task_checkboxes[tt_name] = chk
            self.layout_checkboxes.addWidget(chk)

        self.panel_tasks.setVisible(bool(task_types))

    def _prompt_missing_tasks(self, names: list) -> None:
        """Block batch creation when selected assets have no tasks in Kitsu."""
        preview = "\n".join(f"• {name}" for name in names[:10])
        if len(names) > 10:
            preview += self.tr("\n… and {count} more").format(count=len(names) - 10)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(self.tr("Missing Tasks"))
        box.setText(
            self.tr(
                "These assets have no tasks in Kitsu. Create their tasks before batch creating files."
            )
        )
        box.setInformativeText(preview)
        open_btn = box.addButton(self.tr("Open Assets in Kitsu"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()

        if box.clickedButton() is open_btn:
            self._open_kitsu_assets()

    def _open_kitsu_assets(self) -> None:
        if not self.vm.current_project_id:
            return
        QDesktopServices.openUrl(QUrl(self.vm.kitsu_assets_url()))

    def change_step(self, step_number: int) -> None:
        if not self.vm.current_project_id:
            return

        self.wizard.set_step(step_number)

        if not self.vm.is_current_project_installed():
            self._show_install_gate()
            return

        self.wizard.set_locked(False)

        if step_number == 1:
            self.stack.setCurrentIndex(0)
        elif step_number == 2:
            self.stack.setCurrentIndex(1)
            self.vm.load_editorial_status()
        elif step_number == 3:
            self.stack.setCurrentIndex(2)
            self.vm.load_assets()
        elif step_number == 4:
            self.stack.setCurrentIndex(2)
            self.vm.load_shots()

    # ------------------------------------------------------------------
    # Install gate
    # ------------------------------------------------------------------
    def _show_install_gate(self) -> None:
        self.wizard.set_locked(True)
        self.lbl_install_status.setText(
            self.tr(
                "This project must be installed on your disk (VCS checkout + isolated Blender) "
                "before assets can be generated."
            )
        )
        self.btn_install_project.setEnabled(True)
        self.stack.setCurrentWidget(self.page_install)

    def _start_project_install(self) -> None:
        self.btn_install_project.setEnabled(False)
        self.lbl_install_status.setText(self.tr("Installing workspace... this may take a few minutes."))
        if not self.vm.install_current_project():
            self.btn_install_project.setEnabled(True)

    def _on_install_progress(self, message: str, color: str) -> None:
        if message:
            self.lbl_install_status.setText(message)

    def _on_install_finished(self, success: bool, message: str) -> None:
        if success:
            self.lbl_install_status.setText(self.tr("✓ Workspace installed. Loading project..."))
            self.change_step(1)
            self.vm.load_shots()
            self.vm.load_sequences()
        else:
            self.lbl_install_status.setText(self.tr(f"Installation failed: {message}"))
            self.btn_install_project.setEnabled(True)

    def _add_sequence_to_list(self) -> None:
        raw_seq_name = self.input_seq.text().strip().upper()
        if not raw_seq_name:
            return

        seq_name = NamingPolicy.sanitize_name(raw_seq_name)

        for i in range(self.list_sequences.count()):
            item = self.list_sequences.item(i)
            if item.data(Qt.UserRole + 1) == seq_name:
                self.input_seq.clear()
                return

        item = QListWidgetItem(f"{seq_name} (New Entry)")
        item.setData(Qt.UserRole, False)
        item.setData(Qt.UserRole + 1, seq_name)
        item.setForeground(QColor("#3B82F6"))

        self.list_sequences.addItem(item)
        self.input_seq.clear()
        self.input_seq.setFocus()

    # ------------------------------------------------------------------
    # Project loading
    # ------------------------------------------------------------------
    def refresh_projects(self) -> None:
        """Reload the Kitsu project catalog so newly created projects appear."""
        self.vm.load_projects()

    def select_project(self, project_name: str) -> None:
        """Select a project by name, refreshing the catalog when it is missing."""
        self._pending_project_name = project_name
        index = self._find_project_index(project_name)
        if index >= 0:
            self._pending_project_name = ""
            self.combo_projects.setCurrentIndex(index)
            return
        self.refresh_projects()

    def _find_project_index(self, project_name: str) -> int:
        # ``MatchFixedString`` without ``MatchCaseSensitive`` is case-insensitive.
        index = self.combo_projects.findText(project_name, Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            return index
        target = (project_name or "").strip().lower()
        for i in range(self.combo_projects.count()):
            if self.combo_projects.itemText(i).strip().lower() == target:
                return i
        return -1

    def _on_projects_loaded(self, projects: list) -> None:
        # Preserve the current selection across a catalog refresh.
        previous = self._pending_project_name or self.combo_projects.currentText()

        self.combo_projects.blockSignals(True)
        self.combo_projects.clear()
        self.project_map.clear()

        if not projects:
            self.combo_projects.addItem(self.tr("No open projects found"))
        else:
            for p in projects:
                self.project_map[p.get("name", "Unknown")] = p.get("id")
                self.combo_projects.addItem(p.get("name", "Unknown"))

            if previous:
                index = self._find_project_index(previous)
                if index >= 0:
                    self.combo_projects.setCurrentIndex(index)

        self._pending_project_name = ""
        self.combo_projects.blockSignals(False)
        self._on_project_changed()

    def _on_project_changed(self) -> None:
        project_name = self.combo_projects.currentText()
        self.vm.select_project(project_name)
        if not self.vm.current_project_id:
            return
        self.change_step(1)
        if self.vm.is_current_project_installed():
            self.vm.load_shots()
            self.vm.load_sequences()

    # ------------------------------------------------------------------
    # Rendering callbacks
    # ------------------------------------------------------------------
    def _render_editorial_status(self, edit_data: dict) -> None:
        if not self.vm.is_current_project_installed():
            self._show_install_gate()
            return

        self.wizard.btn_batch_create.setEnabled(True)

        self.lbl_edit_filename.setText(self.tr(f"File Name: {edit_data['file_name']}"))
        self.lbl_edit_version.setText(self.tr(f"Version: {edit_data['version']}"))
        self.lbl_edit_editor.setText(self.tr(f"Assigned Editor: {edit_data['assignees']}"))
        self.lbl_edit_status.setText(self.tr(f"Task Status: {edit_data['status']}"))

        if edit_data["has_file"]:
            self.wizard.btn_batch_create.setText(self.tr("Assign Editor in Kitsu"))
            self.wizard.btn_batch_create.setObjectName("SecondaryButton")
            self.edit_action_mode = "ASSIGN"
        else:
            self.wizard.btn_batch_create.setText(self.tr("Spawn Edit Master"))
            self.wizard.btn_batch_create.setObjectName("OrangeCTA")
            self.edit_action_mode = "SPAWN"

        self.wizard.btn_batch_create.style().polish(self.wizard.btn_batch_create)

    def _render_assets(self, assets: list) -> None:
        self._table_mode = "assets"
        task_types = sorted({tt for asset in assets for tt in (asset.get("tasks") or {}).keys()})
        base_headers = ["", self.tr("Asset Name"), self.tr("Type")]
        all_headers = base_headers + task_types

        self.table.setColumnCount(len(all_headers))
        self.table.setHorizontalHeaderLabels(all_headers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for i in range(len(base_headers), len(all_headers)):
            header.setSectionResizeMode(i, QHeaderView.Stretch)

        self.table.setRowCount(len(assets))
        self._render_task_checkboxes(task_types)

        for row, asset in enumerate(assets):
            chk_item = QTableWidgetItem()

            if asset["has_file"]:
                chk_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Unchecked)
            else:
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Checked)

            chk_item.setData(Qt.UserRole, asset)
            self.table.setItem(row, 0, chk_item)

            name_item = QTableWidgetItem(asset["name"])
            if not (asset.get("tasks") or {}):
                name_item.setToolTip(self.tr("No Kitsu tasks: create them before batch creating."))
            self.table.setItem(row, 1, name_item)
            self.table.setItem(row, 2, QTableWidgetItem(asset.get("type", "")))

            tasks_data = asset.get("tasks") or {}
            for col_idx, tt_name in enumerate(task_types):
                table_col = len(base_headers) + col_idx
                task_info = tasks_data.get(tt_name)
                self.table.setCellWidget(
                    row, table_col, self._build_task_cell(asset, task_info, tt_name)
                )

        self.lbl_kpi_total.setText(self.tr(f"Total Entries: {len(assets)}"))
        self.lbl_kpi_shots.setText(self.tr("Shots: 0"))
        self.lbl_kpi_assets.setText(self.tr(f"Assets: {len(assets)}"))

    def _open_task_file_dialog(self, entity: dict, task_info: dict, task_type_name: str) -> None:
        from src.interfaces.qt.views.task_file_link_dialog import TaskFileLinkDialog

        raw_task = task_info.get("raw_task") or {}
        is_shot = self._table_mode == "shots"

        if is_shot:
            task = Task.from_kitsu_dict(
                raw_task,
                entity_type=EntityType.SHOT,
                entity_name=entity.get("name", ""),
                sequence_name=entity.get("parent", ""),
                task_type_name=task_type_name,
                project_name=self.vm.current_project_name,
            )
        else:
            task = Task.from_kitsu_dict(
                raw_task,
                entity_type=EntityType.ASSET,
                entity_name=entity.get("name", ""),
                asset_type_name=entity.get("type", ""),
                task_type_name=task_type_name,
                project_name=self.vm.current_project_name,
            )

        suggested_path = self._task_filepath(task_info) or self.vm.suggest_task_file_path(task)
        dialog = TaskFileLinkDialog(
            self,
            viewmodel=self.vm,
            task=task,
            project_root=self.vm.project_root(),
            entity_label=entity.get("name", "Shot" if is_shot else "Asset"),
            task_type_name=task_type_name,
            suggested_path=suggested_path,
        )
        if dialog.exec() == QDialog.Accepted:
            if is_shot:
                self.vm.load_shots()
            else:
                self.vm.load_assets()

    def _render_shots(self, shots: list, task_types: list) -> None:
        self._table_mode = "shots"
        base_headers = ["", self.tr("Shot Name"), self.tr("Sequence"), self.tr("Frames")]
        all_headers = base_headers + task_types

        self.table.setColumnCount(len(all_headers))
        self.table.setHorizontalHeaderLabels(all_headers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        for i in range(1, len(base_headers)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        for i in range(len(base_headers), len(all_headers)):
            header.setSectionResizeMode(i, QHeaderView.Stretch)

        self.table.setRowCount(len(shots))
        shots_count = len(shots)

        self._render_task_checkboxes(task_types)

        for row, entity in enumerate(shots):
            chk_item = QTableWidgetItem()
            has_all_files = entity.get("has_file", False)

            if has_all_files:
                chk_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Unchecked)
            else:
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Checked)

            chk_item.setData(Qt.UserRole, entity)
            self.table.setItem(row, 0, chk_item)

            self.table.setItem(row, 1, QTableWidgetItem(entity.get("name", "Unknown")))
            self.table.setItem(row, 2, QTableWidgetItem(entity.get("parent", "Unknown")))
            self.table.setItem(row, 3, QTableWidgetItem(str(entity.get("frame_in", 0))))

            tasks_data = entity.get("tasks", {})
            for col_idx, tt_name in enumerate(task_types):
                table_col = len(base_headers) + col_idx
                task_info = tasks_data.get(tt_name)
                self.table.setCellWidget(
                    row, table_col, self._build_task_cell(entity, task_info, tt_name)
                )

        self.lbl_kpi_total.setText(self.tr(f"Total Entries: {shots_count}"))
        self.lbl_kpi_shots.setText(self.tr(f"Shots: {shots_count}"))
        self.lbl_kpi_assets.setText(self.tr("Assets: 0"))

    def _render_sequences(self, sequences: list) -> None:
        self.list_sequences.clear()

        for seq in sequences:
            name = seq["name"]
            has_file = seq["has_file"]

            label = f"{name} (✓ File Exists)" if has_file else f"{name} (Pending Spawn)"
            item = QListWidgetItem(label)

            item.setData(Qt.UserRole, has_file)
            item.setData(Qt.UserRole + 1, name)

            if has_file:
                item.setForeground(QColor("#10B981"))
            else:
                item.setForeground(QColor("#F59E0B"))

            self.list_sequences.addItem(item)

    # ------------------------------------------------------------------
    # Pipeline execution
    # ------------------------------------------------------------------
    def _begin_spawn(self, title: str) -> SpawningProgressDialog:
        """Create the progress modal and wire it to the VM signals.

        Any handler still connected to ``spawn_finished`` from a previous run is
        dropped first, so a finished spawn can never fire twice or cross-fire
        into another step's callback.
        """
        try:
            self.vm.spawn_finished.disconnect()
        except (RuntimeError, TypeError):
            pass

        dialog = SpawningProgressDialog(self, title)
        dialog.show()
        self.progress_modal = dialog
        self.vm.spawn_progress.connect(dialog.update_progress)
        self.vm.spawn_log.connect(dialog.append_log)
        return dialog

    def _end_spawn(self, dialog: SpawningProgressDialog) -> None:
        """Detach the progress/log signals from a specific dialog (idempotent)."""
        for signal, slot in (
            (self.vm.spawn_progress, dialog.update_progress),
            (self.vm.spawn_log, dialog.append_log),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _execute_pipeline_step(self, step_id: int) -> None:
        if not self.vm.current_project_id:
            self.vm.report_status(self.tr("Please select a project first."), "yellow")
            return

        if not self.vm.is_current_project_installed():
            self._show_install_gate()
            self.vm.report_status(self.tr("Install the project workspace before generating files."), "yellow")
            return

        if step_id == 1:
            if self.input_seq.text().strip():
                self._add_sequence_to_list()

            pending_sequences = []
            for i in range(self.list_sequences.count()):
                item = self.list_sequences.item(i)
                has_file = item.data(Qt.UserRole)
                if not has_file:
                    pending_sequences.append(item.data(Qt.UserRole + 1))

            if not pending_sequences:
                QMessageBox.information(self, self.tr("System Checked"), self.tr("All listed sequences already have physical files. Nothing to spawn."))
                return

            dialog = self._begin_spawn(self.tr("Batch Spawning Storyboards"))

            def on_finished(success: bool, msg: str, dialog=dialog) -> None:
                try:
                    self.vm.spawn_finished.disconnect(on_finished)
                except (RuntimeError, TypeError):
                    pass
                self._end_spawn(dialog)
                if success:
                    dialog.finalize(True, self.tr("Success: Storyboards spawned."), "Assign Artists in Kitsu", self._open_kitsu_shots)
                    self.change_step(2)
                    self.vm.load_sequences()
                else:
                    dialog.finalize(False, msg or self.tr("Process completed with errors. Check logs."))
                    QMessageBox.critical(self, self.tr("Spawn Failed"), msg or self.tr("Unknown error."))

            self.vm.spawn_finished.connect(on_finished)
            self.vm.spawn_storyboard(pending_sequences)

        elif step_id == 2:
            if getattr(self, "edit_action_mode", "SPAWN") == "ASSIGN":
                kitsu_url = self.vm.config_factory.get_kitsu_api_url().replace("/api", "")
                url = f"{kitsu_url}/productions/{self.vm.current_project_id}/edits"
                QDesktopServices.openUrl(QUrl(url))
                self.vm.report_status(self.tr("Opened Kitsu for assignment."), "white")
                return

            dialog = self._begin_spawn(self.tr("Spawning EDIT Master"))

            def on_finished(success: bool, msg: str, dialog=dialog) -> None:
                try:
                    self.vm.spawn_finished.disconnect(on_finished)
                except (RuntimeError, TypeError):
                    pass
                self._end_spawn(dialog)
                if success:
                    self.change_step(3)
                    dialog.finalize(True, self.tr("Success: EDIT Master forged."))
                else:
                    dialog.finalize(False, msg or self.tr("Process completed with errors. Check logs."))
                    QMessageBox.critical(self, self.tr("Spawn Failed"), msg or self.tr("Unknown error."))

            self.vm.spawn_finished.connect(on_finished)
            self.vm.spawn_edit_master()

        elif step_id in [3, 4]:
            self._trigger_batch_creation(step_id)

    def _open_kitsu_shots(self) -> None:
        kitsu_url = self.vm.config_factory.get_kitsu_api_url().replace("/api", "")
        url = f"{kitsu_url}/productions/{self.vm.current_project_id}/shots"
        QDesktopServices.openUrl(QUrl(url))
        self.progress_modal.accept()

    def _trigger_batch_creation(self, step_id: int) -> None:
        selected_entities = [
            self.table.item(r, 0).data(Qt.UserRole)
            for r in range(self.table.rowCount())
            if self.table.item(r, 0).checkState() == Qt.Checked
        ]
        if not selected_entities:
            QMessageBox.information(self, self.tr("System Checked"), self.tr("No pending entities selected to spawn."))
            return

        if step_id == 3:
            # Never forge an asset that has no Kitsu tasks: the PM must create
            # them first (the Hub does not invent pipeline tasks).
            task_less = [e.get("name", "?") for e in selected_entities if not (e.get("tasks") or {})]
            if task_less:
                self._prompt_missing_tasks(task_less)
                return

        selected_tasks = [name for name, chk in self.task_checkboxes.items() if chk.isChecked()]
        if self.task_checkboxes and not selected_tasks:
            QMessageBox.warning(self, self.tr("Missing Tasks"), self.tr("Please select at least one task type to spawn."))
            return

        dialog = self._begin_spawn(self.tr("Batch Spawning Production Files"))

        def on_batch_finished(success: bool, message: str, dialog=dialog) -> None:
            try:
                self.vm.spawn_finished.disconnect(on_batch_finished)
            except (RuntimeError, TypeError):
                pass
            self._end_spawn(dialog)
            if success:
                dialog.update_progress(100, self.tr("Done!"))
                dialog.finalize(True, self.tr("Success: Files Spawned."), "Assign in Kitsu", self._open_kitsu_assets)
                if step_id == 3:
                    self.vm.load_assets()
                elif step_id == 4:
                    self.vm.load_shots()
            else:
                dialog.finalize(False, message or self.tr("Process completed with errors. Check logs."))
                QMessageBox.critical(self, self.tr("Batch Creation Failed"), message)

        self.vm.spawn_finished.connect(on_batch_finished)
        self.vm.spawn_batch(selected_entities, selected_tasks)
