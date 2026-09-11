# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/blend_builder_widget.py
# Architectural role: UI Widget / Batch Entity Genesis Tool
# =========================================================================================

"""Batch entity builder widget (PM wizard).

Coordinates the PipelineWizard stepper and the entity table, delegating all
data access and spawning to ``BlendBuilderViewModel``.
"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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

from src.domain.production.naming import NamingPolicy
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

        main_layout.addWidget(self.stack, stretch=1)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _create_kpi_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("KPILabel")
        return lbl

    def _create_pill_label(self, text: str, color_hex: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 2, 5, 2)
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setObjectName("PillLabel")
        lbl.setStyleSheet(f"background-color: {color_hex};")
        layout.addWidget(lbl)
        return widget

    def _open_kitsu_assets(self) -> None:
        if not self.vm.current_project_id:
            return
        QDesktopServices.openUrl(QUrl(self.vm.kitsu_assets_url()))

    def change_step(self, step_number: int) -> None:
        if not self.vm.current_project_id:
            return

        self.wizard.set_step(step_number)

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
    def _on_projects_loaded(self, projects: list) -> None:
        self.combo_projects.blockSignals(True)
        self.combo_projects.clear()
        self.project_map.clear()

        if not projects:
            self.combo_projects.addItem(self.tr("No open projects found"))
            self.combo_projects.blockSignals(False)
            return

        for p in projects:
            self.project_map[p.get("name", "Unknown")] = p.get("id")
            self.combo_projects.addItem(p.get("name", "Unknown"))

        self.combo_projects.blockSignals(False)
        self._on_project_changed()

    def _on_project_changed(self) -> None:
        project_name = self.combo_projects.currentText()
        if project_name in self.project_map:
            self.vm.select_project(project_name)
            self.change_step(1)
            self.vm.load_shots()
            self.vm.load_sequences()

    # ------------------------------------------------------------------
    # Rendering callbacks
    # ------------------------------------------------------------------
    def _render_editorial_status(self, edit_data: dict) -> None:
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
        self.table.setRowCount(len(assets))

        for row, asset in enumerate(assets):
            chk_item = QTableWidgetItem()

            if asset["has_file"]:
                chk_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Unchecked)
            else:
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Checked)

            chk_item.setData(Qt.UserRole, asset["raw_data"])
            self.table.setItem(row, 0, chk_item)

            self.table.setItem(row, 1, QTableWidgetItem(asset["name"]))
            self.table.setCellWidget(row, 2, self._create_pill_label("Asset", "#8B5CF6"))
            self.table.setItem(row, 3, QTableWidgetItem("N/A"))
            self.table.setItem(row, 4, QTableWidgetItem("N/A"))

            status_text = "✓ File Exists" if asset["has_file"] else "Pending Spawn"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor("#10B981") if asset["has_file"] else QColor("#F59E0B"))
            self.table.setItem(row, 5, status_item)

        self.lbl_kpi_total.setText(self.tr(f"Total Entries: {len(assets)}"))
        self.lbl_kpi_shots.setText(self.tr("Shots: 0"))
        self.lbl_kpi_assets.setText(self.tr(f"Assets: {len(assets)}"))

    def _render_shots(self, shots: list, task_types: list) -> None:
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

        self.panel_tasks.show()
        while self.layout_checkboxes.count():
            child = self.layout_checkboxes.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.task_checkboxes.clear()
        for tt_name in task_types:
            from PySide6.QtWidgets import QCheckBox

            chk = QCheckBox(tt_name)
            chk.setChecked(True)
            self.task_checkboxes[tt_name] = chk
            self.layout_checkboxes.addWidget(chk)

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

                if tt_name in tasks_data:
                    task_info = tasks_data[tt_name]
                    if task_info["has_file"]:
                        self.table.setCellWidget(row, table_col, self._create_pill_label("✓ Ready", "#10B981"))
                    else:
                        self.table.setCellWidget(row, table_col, self._create_pill_label("Pending", "#F59E0B"))
                else:
                    self.table.setCellWidget(row, table_col, self._create_pill_label("N/A", "#4B5563"))

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
    def _execute_pipeline_step(self, step_id: int) -> None:
        if not self.vm.current_project_id:
            self.vm.report_status(self.tr("Please select a project first."), "yellow")
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

            self.progress_modal = SpawningProgressDialog(self, self.tr("Batch Spawning Storyboards"))
            self.progress_modal.show()

            self.vm.spawn_progress.connect(self.progress_modal.update_progress)
            self.vm.spawn_log.connect(self.progress_modal.append_log)

            def on_finished(success: bool, msg: str) -> None:
                self.vm.spawn_progress.disconnect(self.progress_modal.update_progress)
                self.vm.spawn_log.disconnect(self.progress_modal.append_log)
                if success:
                    self.progress_modal.finalize(True, self.tr("Success: Storyboards spawned."), "Assign Artists in Kitsu", self._open_kitsu_shots)
                    self.change_step(2)
                    self.vm.load_sequences()
                else:
                    self.progress_modal.finalize(False, self.tr("Process completed with errors. Check logs."))

            self.vm.spawn_finished.connect(on_finished)
            self.vm.spawn_storyboard(pending_sequences)

        elif step_id == 2:
            if getattr(self, "edit_action_mode", "SPAWN") == "ASSIGN":
                kitsu_url = self.vm.config_factory.get_kitsu_api_url().replace("/api", "")
                url = f"{kitsu_url}/productions/{self.vm.current_project_id}/edits"
                QDesktopServices.openUrl(QUrl(url))
                self.vm.report_status(self.tr("Opened Kitsu for assignment."), "white")
                return

            self.progress_modal = SpawningProgressDialog(self, self.tr("Spawning EDIT Master"))
            self.progress_modal.show()

            self.vm.spawn_progress.connect(self.progress_modal.update_progress)
            self.vm.spawn_log.connect(self.progress_modal.append_log)

            def on_finished(success: bool, msg: str) -> None:
                self.vm.spawn_progress.disconnect(self.progress_modal.update_progress)
                self.vm.spawn_log.disconnect(self.progress_modal.append_log)
                if success:
                    self.change_step(3)
                    self.progress_modal.finalize(True, self.tr("Success: EDIT Master forged."))
                else:
                    self.progress_modal.finalize(False, self.tr("Process completed with errors. Check logs."))

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

        selected_tasks = []
        if step_id == 4:
            selected_tasks = [name for name, chk in self.task_checkboxes.items() if chk.isChecked()]
            if not selected_tasks:
                QMessageBox.warning(self, self.tr("Missing Tasks"), self.tr("Please select at least one task type to spawn."))
                return
        else:
            selected_tasks = ["Modeling", "Rigging", "Shading", "Concept"]

        self.progress_modal = SpawningProgressDialog(self, self.tr("Batch Spawning Production Files"))
        self.progress_modal.show()

        self.vm.spawn_progress.connect(self.progress_modal.update_progress)
        self.vm.spawn_log.connect(self.progress_modal.append_log)

        def on_batch_finished(success: bool, message: str) -> None:
            self.vm.spawn_progress.disconnect(self.progress_modal.update_progress)
            self.vm.spawn_log.disconnect(self.progress_modal.append_log)
            if success:
                self.progress_modal.update_progress(100, self.tr("Done!"))
                self.progress_modal.finalize(True, self.tr("Success: Files Spawned."), "Assign in Kitsu", self._open_kitsu_assets)
                if step_id == 3:
                    self.vm.load_assets()
                elif step_id == 4:
                    self.vm.load_shots()
            else:
                self.progress_modal.finalize(False, self.tr("Process completed with errors. Check logs."))
                QMessageBox.critical(self, self.tr("Batch Creation Failed"), message)

        self.vm.spawn_finished.connect(on_batch_finished)
        self.vm.spawn_batch(selected_entities, selected_tasks)
