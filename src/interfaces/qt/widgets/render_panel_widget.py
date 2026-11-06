# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/render_panel_widget.py
# Architectural role: UI Widget / dedicated render panel
# =========================================================================================

"""Dedicated render panel: shot selection, setup audit, preview, burst and video."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.domain.render.capacity import default_seconds_per_frame
from src.domain.render.models import RenderPlan, RenderQuality, RenderSettings, RenderShot
from src.interfaces.qt.components.collapsible_section import CollapsibleSection
from src.interfaces.qt.components.frame_sequence_player import FrameSequencePlayer
from src.interfaces.qt.viewmodels.render_panel_viewmodel import RenderPanelViewModel


class RenderPanelWidget(QFrame):
    def __init__(
        self,
        parent,
        viewmodel: RenderPanelViewModel,
        project_list_vm,
        *,
        read_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self.vm = viewmodel
        self.project_list_vm = project_list_vm
        self.read_only = read_only
        self._projects: list[dict] = []
        self._shots: list[RenderShot] = []
        self._plan: RenderPlan | None = None
        self._selected_shot: RenderShot | None = None
        self._populating = False
        self._current_preview = ""

        self.setObjectName("RenderPanelBase")
        self._build_ui()
        self._connect()
        self._load_projects()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
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
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel(self.tr("Render"))
        title.setObjectName("PageTitle")
        header.addWidget(title)
        self.combo_projects = QComboBox()
        self.combo_projects.setObjectName("StandardComboBox")
        self.combo_projects.setFixedSize(260, 34)
        self.combo_projects.currentIndexChanged.connect(self._on_project_changed)
        header.addWidget(self.combo_projects)
        header.addStretch()
        self.lbl_balance = QLabel(self.tr("Vast.ai balance: -"))
        self.lbl_balance.setObjectName("InfoLabel")
        header.addWidget(self.lbl_balance)
        self.btn_refresh = QPushButton(self.tr("⟳ Scan"))
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.setFixedSize(100, 34)
        self.btn_refresh.clicked.connect(self._scan)
        header.addWidget(self.btn_refresh)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(8)
        left_label = QLabel(self.tr("Shots"))
        left_label.setObjectName("SectionTitle")
        left_layout.addWidget(left_label)

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setChildrenCollapsible(False)
        left_splitter.setHandleWidth(8)
        shots_panel = QWidget()
        shots_layout = QVBoxLayout(shots_panel)
        shots_layout.setContentsMargins(0, 0, 0, 0)
        shots_layout.setSpacing(8)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "",
                self.tr("Shot"),
                self.tr("Frames"),
                self.tr("Status"),
                self.tr("Engine"),
                self.tr("Layers"),
                self.tr("s/frame"),
                self.tr("Cost"),
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.Stretch)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(260)
        self.table.itemSelectionChanged.connect(self._on_shot_selected)
        self.table.itemChanged.connect(self._on_check_changed)
        shots_layout.addWidget(self.table, 1)
        left_splitter.addWidget(shots_panel)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(600)
        self.log.setMinimumHeight(120)
        self.log_section = CollapsibleSection(self.tr("Log"))
        self.log_section.add_widget(self.log)
        left_splitter.addWidget(self.log_section)
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 2)
        left_layout.addWidget(left_splitter, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(10)

        preview_frame = CollapsibleSection(self.tr("Preview (composite)"))
        self.preview_section = preview_frame
        self.preview_label = QLabel(self.tr("Select a shot to see its preview."))
        self.preview_label.setObjectName("MutedLabel")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(220)
        self.preview_label.setWordWrap(True)
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.preview_label)
        self.player = FrameSequencePlayer()
        self.preview_stack.addWidget(self.player)
        preview_frame.add_widget(self.preview_stack)
        preview_buttons = QHBoxLayout()
        self.btn_preview_selected = QPushButton(self.tr("Preview selected"))
        self.btn_preview_selected.setObjectName("SecondaryButton")
        self.btn_preview_selected.clicked.connect(self._preview_selected)
        self.btn_preview_all = QPushButton(self.tr("Preview all selected"))
        self.btn_preview_all.setObjectName("SecondaryButton")
        self.btn_preview_all.clicked.connect(self._preview_all)
        self.btn_benchmark = QPushButton(self.tr("Benchmark selected"))
        self.btn_benchmark.setObjectName("SecondaryButton")
        self.btn_benchmark.clicked.connect(self._benchmark_selected)
        self.btn_play_final = QPushButton(self.tr("Play final sequence"))
        self.btn_play_final.setObjectName("SecondaryButton")
        self.btn_play_final.clicked.connect(self._play_final_sequence)
        preview_buttons.addWidget(self.btn_preview_selected)
        preview_buttons.addWidget(self.btn_preview_all)
        preview_buttons.addWidget(self.btn_play_final)
        preview_buttons.addWidget(self.btn_benchmark)
        preview_buttons.addStretch()
        preview_frame.add_layout(preview_buttons)
        right_layout.addWidget(preview_frame)

        self.setup_section = CollapsibleSection(self.tr("Shot setup"), expanded=False)
        self.lbl_setup = QLabel(self.tr("Render setup: select a shot."))
        self.lbl_setup.setObjectName("InfoLabel")
        self.lbl_setup.setWordWrap(True)
        self.setup_section.add_widget(self.lbl_setup)

        self.lbl_warnings = QLabel("")
        self.lbl_warnings.setObjectName("MutedLabel")
        self.lbl_warnings.setWordWrap(True)
        self.setup_section.add_widget(self.lbl_warnings)
        right_layout.addWidget(self.setup_section)

        self._build_settings(right_layout)
        right_layout.addWidget(self._build_summary_frame())
        right_layout.addWidget(self._build_video_frame())
        right_layout.addLayout(self._build_actions())

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        right_layout.addWidget(self.progress)
        right_layout.addStretch()
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        if self.read_only:
            for widget in (
                self.btn_refresh,
                self.btn_preview_selected,
                self.btn_preview_all,
                self.btn_benchmark,
                self.btn_play_final,
                self.btn_start,
                self.btn_cancel,
                self.btn_video,
                self.btn_preview_video,
                self.btn_retry_render,
                self.btn_upload_kitsu,
            ):
                widget.setVisible(False)
            for widget in (
                self.settings_frame,
                self.video_frame,
            ):
                widget.setVisible(False)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _build_settings(self, layout: QVBoxLayout) -> None:
        self.settings_frame = CollapsibleSection(self.tr("Render settings"))
        self.final_settings_section = CollapsibleSection(self.tr("Final render"))
        self.preview_settings_section = CollapsibleSection(self.tr("Preview render"))
        self.vast_section = CollapsibleSection(self.tr("Vast.ai plan"))

        final_widget = QWidget()
        final_form = QFormLayout(final_widget)
        final_form.setContentsMargins(0, 0, 0, 0)
        final_form.setHorizontalSpacing(12)
        final_form.setVerticalSpacing(6)

        self.combo_backend = QComboBox()
        self.combo_backend.addItem(self.tr("Vast.ai (on-demand)"), "vast")
        self.combo_backend.addItem(self.tr("Local headless"), "local")
        final_form.addRow(self.tr("Backend"), self.combo_backend)

        self.combo_samples = QComboBox()
        self.combo_samples.addItems(["128", "256"])
        final_form.addRow(self.tr("Samples"), self.combo_samples)
        self.final_settings_section.add_widget(final_widget)

        preview_widget = QWidget()
        preview_form = QFormLayout(preview_widget)
        preview_form.setContentsMargins(0, 0, 0, 0)
        preview_form.setHorizontalSpacing(12)
        preview_form.setVerticalSpacing(6)

        self.combo_preview_backend = QComboBox()
        self.combo_preview_backend.addItem(self.tr("Local"), "local")
        self.combo_preview_backend.addItem(self.tr("Vast.ai"), "vast")
        preview_form.addRow(self.tr("Backend"), self.combo_preview_backend)

        self.combo_preview_res = QComboBox()
        self.combo_preview_res.addItem("25%", 25)
        self.combo_preview_res.addItem("50%", 50)
        self.combo_preview_res.addItem("100%", 100)
        preview_form.addRow(self.tr("Resolution"), self.combo_preview_res)

        self.combo_preview_samples = QComboBox()
        self.combo_preview_samples.addItems(["16", "32", "64"])
        preview_form.addRow(self.tr("Samples"), self.combo_preview_samples)
        self.preview_settings_section.add_widget(preview_widget)

        vast_widget = QWidget()
        vast_form = QFormLayout(vast_widget)
        vast_form.setContentsMargins(0, 0, 0, 0)
        vast_form.setHorizontalSpacing(12)
        vast_form.setVerticalSpacing(6)

        self.combo_target = QComboBox()
        self.combo_target.addItem(self.tr("1 hour"), 1.0)
        self.combo_target.addItem(self.tr("2 hours"), 2.0)
        self.combo_target.addItem(self.tr("Custom"), 0.0)
        self.spin_hours = QDoubleSpinBox()
        self.spin_hours.setRange(0.25, 48.0)
        self.spin_hours.setSingleStep(0.25)
        self.spin_hours.setSuffix(self.tr(" h"))
        target_row = QHBoxLayout()
        target_row.addWidget(self.combo_target, 2)
        target_row.addWidget(self.spin_hours, 1)
        vast_form.addRow(self.tr("Target wall time"), target_row)

        self.combo_gpu = QComboBox()
        self.combo_gpu.addItem(self.tr("RTX 4070 12 GB"), "rtx_4070")
        self.combo_gpu.addItem(self.tr("RTX 3080 10 GB"), "rtx_3080")
        self.combo_gpu.addItem(self.tr("RTX 3070 8 GB"), "rtx_3070")
        self.combo_gpu.addItem(self.tr("RTX 3090 24 GB"), "rtx_3090")
        self.combo_gpu.addItem(self.tr("RTX 4090 24 GB"), "rtx_4090")
        self.combo_gpu.addItem(self.tr("RTX A6000 48 GB"), "rtx_a6000")
        vast_form.addRow(self.tr("GPU"), self.combo_gpu)

        limits = QHBoxLayout()
        self.spin_price = QDoubleSpinBox()
        self.spin_price.setRange(0.0, 5.0)
        self.spin_price.setSingleStep(0.05)
        self.spin_price.setPrefix("$")
        self.spin_price.setSuffix(self.tr("/h"))
        self.spin_nodes = QSpinBox()
        self.spin_nodes.setRange(0, 64)
        self.spin_nodes.setSpecialValueText(self.tr("Auto"))
        self.spin_budget = QDoubleSpinBox()
        self.spin_budget.setRange(0.0, 1000.0)
        self.spin_budget.setPrefix("$")
        limits.addWidget(QLabel(self.tr("Max price")))
        limits.addWidget(self.spin_price)
        limits.addWidget(QLabel(self.tr("Max nodes")))
        limits.addWidget(self.spin_nodes)
        limits.addWidget(QLabel(self.tr("Budget")))
        limits.addWidget(self.spin_budget)
        limits.addStretch()
        vast_form.addRow(self.tr("Limits"), limits)

        network_row = QHBoxLayout()
        self.combo_region = QComboBox()
        self.combo_region.addItem(self.tr("Prefer Americas"), "prefer_americas")
        self.combo_region.addItem(self.tr("Americas only"), "us")
        self.combo_region.addItem(self.tr("Any region"), "any")
        self.spin_min_down = QDoubleSpinBox()
        self.spin_min_down.setRange(0.0, 10000.0)
        self.spin_min_down.setSuffix(self.tr(" Mbps down"))
        self.spin_min_up = QDoubleSpinBox()
        self.spin_min_up.setRange(0.0, 10000.0)
        self.spin_min_up.setSuffix(self.tr(" Mbps up"))
        network_row.addWidget(self.combo_region)
        network_row.addWidget(self.spin_min_down)
        network_row.addWidget(self.spin_min_up)
        network_row.addStretch()
        vast_form.addRow(self.tr("Network"), network_row)
        self.vast_section.add_widget(vast_widget)

        self.settings_frame.add_widget(self.final_settings_section)
        self.settings_frame.add_widget(self.preview_settings_section)
        self.settings_frame.add_widget(self.vast_section)

        self.btn_recalculate = QPushButton(self.tr("Recalculate plan"))
        self.btn_recalculate.setObjectName("SecondaryButton")
        self.btn_recalculate.clicked.connect(self._scan)
        self.settings_frame.add_widget(self.btn_recalculate)

        layout.addWidget(self.settings_frame)
        self._sync_backend_sections()

    def _build_summary_frame(self) -> QFrame:
        frame = CollapsibleSection(self.tr("Plan"))
        self.lbl_summary = QLabel(self.tr("Scan a project to calculate the plan."))
        self.lbl_summary.setObjectName("InfoLabel")
        self.lbl_summary.setWordWrap(True)
        frame.add_widget(self.lbl_summary)
        return frame

    def _build_video_frame(self) -> QFrame:
        self.video_frame = CollapsibleSection(self.tr("Review video / Kitsu"), expanded=False)
        video_widget = QWidget()
        video_form = QFormLayout(video_widget)
        video_form.setContentsMargins(0, 0, 0, 0)
        video_form.setHorizontalSpacing(12)
        video_form.setVerticalSpacing(6)
        self.chk_video = QCheckBox(self.tr("Create review video when the render finishes"))
        video_form.addRow(self.chk_video)
        self.edit_video_task = QLineEdit("render")
        self.edit_video_version = QLineEdit()
        self.edit_video_version.setPlaceholderText(self.tr("auto"))
        video_row = QHBoxLayout()
        video_row.addWidget(QLabel(self.tr("Task type")))
        video_row.addWidget(self.edit_video_task)
        video_row.addWidget(QLabel(self.tr("Version")))
        video_row.addWidget(self.edit_video_version)
        video_form.addRow(self.tr("Video"), video_row)
        self.video_frame.add_widget(video_widget)

        self.lbl_video = QLabel(self.tr("No review video yet."))
        self.lbl_video.setObjectName("MutedLabel")
        self.lbl_video.setWordWrap(True)
        self.video_frame.add_widget(self.lbl_video)
        self.combo_kitsu_status = QComboBox()
        self.combo_kitsu_status.setObjectName("StandardComboBox")
        self.combo_kitsu_status.setMinimumWidth(180)
        self.txt_comment = QLineEdit()
        self.txt_comment.setPlaceholderText(self.tr("Render review comment"))
        row = QHBoxLayout()
        row.addWidget(self.combo_kitsu_status, 2)
        row.addWidget(self.txt_comment, 2)
        self.btn_upload_kitsu = QPushButton(self.tr("Upload video & set status"))
        self.btn_upload_kitsu.setObjectName("SuccessButton")
        self.btn_upload_kitsu.clicked.connect(self._upload_kitsu)
        row.addWidget(self.btn_upload_kitsu)
        self.video_frame.add_layout(row)
        return self.video_frame

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        self.btn_start = QPushButton(self.tr("▶ Start render"))
        self.btn_start.setObjectName("SuccessButton")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._start_render)
        self.btn_cancel = QPushButton(self.tr("Cancel"))
        self.btn_cancel.setObjectName("DangerButton")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_render)
        self.btn_retry_render = QPushButton(self.tr("Retry missing frames"))
        self.btn_retry_render.setObjectName("SecondaryButton")
        self.btn_retry_render.clicked.connect(self._retry_render)
        self.btn_retry_render.hide()
        self.btn_preview_video = QPushButton(self.tr("Create preview video"))
        self.btn_preview_video.setObjectName("SecondaryButton")
        self.btn_preview_video.clicked.connect(self._create_preview_video)
        self.btn_video = QPushButton(self.tr("Create review videos"))
        self.btn_video.setObjectName("SecondaryButton")
        self.btn_video.clicked.connect(self._create_video)
        self.btn_open_logs = QPushButton(self.tr("Open run logs"))
        self.btn_open_logs.setObjectName("SecondaryButton")
        self.btn_open_logs.clicked.connect(self._open_run_logs)
        self.btn_output = QPushButton(self.tr("Open output folder"))
        self.btn_output.setObjectName("SecondaryButton")
        self.btn_output.clicked.connect(self._open_output)
        actions.addWidget(self.btn_start)
        actions.addWidget(self.btn_cancel)
        actions.addWidget(self.btn_retry_render)
        actions.addWidget(self.btn_preview_video)
        actions.addWidget(self.btn_video)
        actions.addStretch()
        actions.addWidget(self.btn_open_logs)
        actions.addWidget(self.btn_output)
        return actions

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def _connect(self) -> None:
        self.player.delete_requested.connect(self._delete_frame)
        self.player.approve_requested.connect(self._approve_frame)
        self.combo_target.currentIndexChanged.connect(self._on_target_changed)
        self.combo_backend.currentIndexChanged.connect(self._sync_backend_sections)
        self.combo_preview_backend.currentIndexChanged.connect(self._sync_backend_sections)
        projects_loaded = getattr(self.project_list_vm, "projects_loaded", None)
        if projects_loaded is not None:
            projects_loaded.connect(self._on_projects_loaded)

        self.vm.shots_ready.connect(self._on_shots_ready)
        self.vm.scan_progress.connect(self._on_scan_progress)
        self.vm.scan_error.connect(self._on_error)
        self.vm.preview_ready.connect(self._on_preview_ready)
        self.vm.preview_progress.connect(self._on_preview_progress)
        self.vm.preview_error.connect(self._on_error)
        self.vm.preview_finished.connect(self._on_preview_finished)
        self.vm.benchmark_progress.connect(self._on_burst_progress)
        self.vm.benchmark_finished.connect(self._on_benchmark_finished)
        self.vm.benchmark_error.connect(self._on_error)
        self.vm.burst_progress.connect(self._on_burst_progress)
        self.vm.local_render_progress.connect(self._on_local_progress)
        self.vm.render_finished.connect(self._on_render_finished)
        self.vm.render_error.connect(self._on_error)
        self.vm.video_ready.connect(self._on_video_ready)
        self.vm.preview_video_ready.connect(self._on_preview_video_ready)
        self.vm.video_error.connect(self._on_error)
        self.vm.videos_finished.connect(self._on_videos_finished)
        self.vm.kitsu_statuses_ready.connect(self._on_kitsu_statuses)
        self.vm.kitsu_status_error.connect(self._on_error)
        self.vm.kitsu_upload_finished.connect(self._on_kitsu_upload_finished)
        self.vm.busy_changed.connect(self._on_busy_changed)

    def _load_projects(self) -> None:
        projects = getattr(self.project_list_vm, "_projects", None) or []
        if projects:
            self._on_projects_loaded(projects)
        else:
            refresh = getattr(self.project_list_vm, "refresh", None)
            if callable(refresh):
                refresh()

    def _on_projects_loaded(self, projects: list) -> None:
        self._projects = list(projects or [])
        self.combo_projects.blockSignals(True)
        current = self.combo_projects.currentText()
        self.combo_projects.clear()
        for project in self._projects:
            self.combo_projects.addItem(str(project.get("name") or ""), project)
        if current:
            index = self.combo_projects.findText(current)
            if index >= 0:
                self.combo_projects.setCurrentIndex(index)
        self.combo_projects.blockSignals(False)
        if self.combo_projects.count():
            self._on_project_changed(self.combo_projects.currentIndex())

    def select_project_by_name(self, name: str) -> None:
        index = self.combo_projects.findText(name)
        if index >= 0:
            self.combo_projects.setCurrentIndex(index)

    def _on_project_changed(self, index: int) -> None:
        if index < 0:
            return
        project = self.combo_projects.itemData(index) or {}
        name = str(project.get("name") or self.combo_projects.itemText(index))
        project_id = str(project.get("id") or "")
        try:
            project_root = self.project_list_vm.project_root_for(name)
        except Exception as error:  # noqa: BLE001
            self._append_log(f"Could not resolve project folder: {error}")
            return
        self._shots = []
        self._plan = None
        self._selected_shot = None
        self.table.setRowCount(0)
        self.lbl_setup.setText(self.tr("Render setup: scanning..."))
        self.lbl_summary.setText("")
        self.lbl_warnings.setText("")
        self.lbl_video.setText(self.tr("No review video yet."))
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self._clear_preview()
        self.vm.select_project(
            name,
            project_id,
            Path(project_root),
            read_only=self.read_only,
        )
        if not self.read_only:
            self.vm.load_kitsu_statuses()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def _on_target_changed(self, _index: int = 0) -> None:
        custom = float(self.combo_target.currentData() or 0.0) <= 0
        self.spin_hours.setEnabled(custom)
        if not custom:
            self.spin_hours.setValue(float(self.combo_target.currentData()))

    def _sync_backend_sections(self, _index: int = 0) -> None:
        final_vast = self.combo_backend.currentData() == "vast"
        preview_vast = self.combo_preview_backend.currentData() == "vast"
        self.vast_section.setVisible(final_vast or preview_vast)

    def _settings_from_ui(self) -> RenderSettings:
        base = replace(self.vm.settings)
        target = float(self.combo_target.currentData() or 0.0) or float(
            self.spin_hours.value()
        )
        final = replace(
            base.final_quality,
            engine="CYCLES",
            resolution_x=1920,
            resolution_y=1080,
            resolution_percentage=100,
            samples=int(self.combo_samples.currentText()),
        )
        preview = replace(
            base.preview_quality,
            resolution_x=1920,
            resolution_y=1080,
            resolution_percentage=int(self.combo_preview_res.currentData() or 50),
            samples=int(self.combo_preview_samples.currentText()),
        )
        return replace(
            base,
            final_quality=final,
            preview_quality=preview,
            gpu_profile=self.combo_gpu.currentData() or "rtx_3090",
            target_hours=target,
            max_price_per_hour=float(self.spin_price.value()),
            max_nodes=int(self.spin_nodes.value()),
            budget=float(self.spin_budget.value()),
            render_backend=self.combo_backend.currentData() or "vast",
            preview_backend=self.combo_preview_backend.currentData() or "local",
            video_enabled=bool(self.chk_video.isChecked()),
            video_task_type=(self.edit_video_task.text().strip() or "render"),
            video_version=self.edit_video_version.text().strip(),
            preferred_region=self.combo_region.currentData() or "prefer_americas",
            min_inet_down_mbps=float(self.spin_min_down.value()),
            min_inet_up_mbps=float(self.spin_min_up.value()),
        )

    def _apply_settings_to_ui(self) -> None:
        settings = self.vm.settings
        self.combo_target.blockSignals(True)
        self.combo_samples.blockSignals(True)
        self.combo_gpu.blockSignals(True)
        self.combo_backend.blockSignals(True)
        self.combo_preview_backend.blockSignals(True)
        self.combo_preview_res.blockSignals(True)
        self.combo_preview_samples.blockSignals(True)
        try:
            index = self.combo_target.findData(1.0)
            if float(settings.target_hours) not in (1.0, 2.0):
                index = self.combo_target.findData(0.0)
            self.combo_target.setCurrentIndex(max(0, index))
            self.spin_hours.setValue(float(settings.target_hours))
            self.combo_samples.setCurrentText(str(settings.final_quality.samples))
            gpu_index = self.combo_gpu.findData(settings.gpu_profile)
            self.combo_gpu.setCurrentIndex(max(0, gpu_index))
            self.spin_price.setValue(float(settings.max_price_per_hour))
            self.spin_nodes.setValue(int(settings.max_nodes))
            self.spin_budget.setValue(float(settings.budget))
            backend_index = self.combo_backend.findData(settings.render_backend)
            self.combo_backend.setCurrentIndex(max(0, backend_index))
            preview_index = self.combo_preview_backend.findData(settings.preview_backend)
            self.combo_preview_backend.setCurrentIndex(max(0, preview_index))
            res_index = self.combo_preview_res.findData(
                int(settings.preview_quality.resolution_percentage)
            )
            self.combo_preview_res.setCurrentIndex(max(0, res_index))
            self.combo_preview_samples.setCurrentText(str(settings.preview_quality.samples))
            region_index = self.combo_region.findData(settings.preferred_region)
            self.combo_region.setCurrentIndex(max(0, region_index))
            self.spin_min_down.setValue(float(settings.min_inet_down_mbps))
            self.spin_min_up.setValue(float(settings.min_inet_up_mbps))
            self.chk_video.setChecked(bool(settings.video_enabled))
            self.edit_video_task.setText(settings.video_task_type or "render")
            self.edit_video_version.setText(settings.video_version or "")
        finally:
            for widget in (
                self.combo_target,
                self.combo_samples,
                self.combo_gpu,
                self.combo_backend,
                self.combo_preview_backend,
                self.combo_preview_res,
                self.combo_preview_samples,
                self.combo_region,
            ):
                widget.blockSignals(False)
        self._on_target_changed()
        self._sync_backend_sections()

    def _scan(self) -> None:
        settings = self._settings_from_ui()
        self.vm.update_settings(settings)
        self.vm.scan()

    # ------------------------------------------------------------------
    # Shots
    # ------------------------------------------------------------------
    def _on_shots_ready(self, shots: list, plan: RenderPlan, offer, balance: float) -> None:
        self._shots = list(shots)
        self._plan = plan
        self._apply_settings_to_ui()
        self.lbl_balance.setText(
            self.tr("Vast.ai balance: ${0:.2f}").format(balance)
            if self.vm.settings.render_backend == "vast"
            or self.vm.settings.preview_backend == "vast"
            else self.tr("Render backend: local")
        )
        self._fill_table()
        self.lbl_summary.setText(self._summary_html(plan, offer))
        self.lbl_warnings.setText("\n".join(plan.warnings))
        self.btn_start.setEnabled(
            plan.total_frames > 0
            and (
                self.vm.settings.render_backend != "vast"
                or offer is not None
            )
        )
        if self._shots and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._append_log(
            f"Plan: {plan.total_frames} frame(s), {plan.required_nodes} node(s), "
            f"ETA {plan.estimated_wall_hours:.2f} h, ${plan.estimated_cost:.2f}."
        )

    def _fill_table(self) -> None:
        selected = set(self.vm.settings.selected_shots or ())
        price = self._plan.price_per_hour if self._plan else 0.0
        self._populating = True
        self.table.setRowCount(len(self._shots))
        for row, shot in enumerate(self._shots):
            check = QTableWidgetItem("")
            check.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                if shot.is_ready
                else Qt.ItemIsEnabled
            )
            check.setCheckState(
                Qt.Checked
                if shot.relative_path in selected and shot.is_ready
                else Qt.Unchecked
            )
            self.table.setItem(row, 0, check)
            values = [
                shot.name,
                str(shot.frames),
                self._shot_status(shot),
                shot.quality.label(),
                self._layer_label(shot),
                (
                    (
                        ("~" if shot.measurement_scaled else "")
                        + f"{shot.measured_seconds:.1f}"
                    )
                    if shot.measured_seconds is not None
                    else self.tr("estimate")
                ),
            ]
            for column, value in enumerate(values, start=1):
                self.table.setItem(row, column, QTableWidgetItem(value))
            seconds = shot.measured_seconds
            if seconds is None:
                seconds = default_seconds_per_frame(
                    shot.quality, shot.geometry_node_objects
                )
            cost = shot.frames * seconds / 3600.0 * max(0.0, price)
            self.table.setItem(row, 7, QTableWidgetItem(f"${cost:.2f}"))
        self._populating = False

    @staticmethod
    def _shot_status(shot: RenderShot) -> str:
        if not shot.is_ready:
            return "Not ready"
        setup = shot.setup
        if setup is not None and not setup.is_compositing_ready:
            return "Check setup"
        return "Ready"

    @staticmethod
    def _layer_label(shot: RenderShot) -> str:
        setup = shot.setup
        if setup is None:
            return "-"
        enabled = setup.enabled_layers
        connected = setup.connected_layers
        if not enabled:
            return "no layers"
        return f"{len(connected)}/{len(enabled)} connected"

    def _on_shot_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._shots):
            return
        self._selected_shot = self._shots[row]
        self.player.pause()
        self.preview_stack.setCurrentWidget(self.preview_label)
        self._show_setup(self._selected_shot)
        self._show_latest_preview(self._selected_shot)
        self._show_video(self._selected_shot)

    def _on_check_changed(self, item: QTableWidgetItem) -> None:
        if self._populating or item.column() != 0:
            return
        selected = []
        for row in range(self.table.rowCount()):
            check = self.table.item(row, 0)
            if check is not None and check.checkState() == Qt.Checked:
                shot = self._shots[row]
                selected.append(shot.relative_path)
        self.vm.set_selected_shots(selected)

    def _show_setup(self, shot: RenderShot) -> None:
        setup = shot.setup
        if setup is None:
            self.lbl_setup.setText(self.tr("Render setup: not available."))
            return
        layers = ", ".join(
            f"{layer.name}{'✓' if layer.connected_to_output else '⚠'}"
            for layer in setup.view_layers
        ) or "-"
        comp = "on" if setup.is_compositing_ready else "check"
        outputs = (
            ", ".join(item.base_path for item in setup.file_outputs)
            if setup.file_outputs
            else self.tr("composite only")
        )
        self.lbl_setup.setText(
            self.tr(
                "<b>Compositing:</b> {0} ({1}) · "
                "<b>View layers:</b> {2}<br>"
                "<b>Output:</b> {3} {4} {5} · <b>Color:</b> {6}<br>"
                "<b>Camera:</b> {7} · <b>FPS:</b> {8:.2f} · "
                "<b>Range:</b> {9}–{10}<br>"
                "<b>Files:</b> {11}"
            ).format(
                comp,
                setup.compositor_name or "-",
                layers,
                setup.output_format or "-",
                setup.color_mode or "-",
                f"{setup.color_depth}-bit" if setup.color_depth else "",
                setup.view_transform or "-",
                setup.camera or "-",
                setup.fps,
                shot.frame_start,
                shot.frame_end,
                outputs,
            )
        )
        warnings = list(shot.warnings)
        if setup.use_sequencer:
            warnings.append("Sequencer rendering is enabled.")
        self.lbl_warnings.setText("\n".join(warnings))

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def _preview_selected(self) -> None:
        if self._selected_shot is not None:
            self.preview_stack.setCurrentWidget(self.preview_label)
            self.vm.preview_shots([self._selected_shot])

    def _preview_all(self) -> None:
        self.preview_stack.setCurrentWidget(self.preview_label)
        self.vm.preview_shots(self.vm.selected_shots)

    def _play_final_sequence(self) -> None:
        if self._selected_shot is None:
            QMessageBox.warning(self, self.tr("Render"), self.tr("Select a shot first."))
            return
        entries = self.vm.sequence_entries(self._selected_shot)
        rendered = [entry for entry in entries if entry[1] is not None]
        if not rendered:
            QMessageBox.information(
                self,
                self.tr("Render"),
                self.tr("No rendered frames were found for this shot."),
            )
            return
        fps = self._selected_shot.setup.fps if self._selected_shot.setup else 24.0
        self.preview_stack.setCurrentWidget(self.player)
        self.player.set_sequence(
            rendered,
            fps=fps,
            approved=self.vm.approved_frames(self._selected_shot),
            autoplay=True,
        )
        self._append_log(
            f"Playing final sequence for {self._selected_shot.name} "
            f"({len(rendered)} frame(s))."
        )

    def _delete_frame(self, frame: int) -> None:
        if self._selected_shot is None:
            return
        ok, message = self.vm.delete_frame(self._selected_shot, frame)
        self._append_log(message)
        if ok:
            self.player.remove_frame(frame)
        else:
            QMessageBox.warning(self, self.tr("Delete frame"), message)

    def _approve_frame(self, frame: int, approved: bool) -> None:
        if self._selected_shot is None:
            return
        ok, message = self.vm.approve_frame(self._selected_shot, frame, approved)
        self._append_log(message)
        if ok:
            self.player.set_frame_approved(frame, approved)
        else:
            self.player.set_frame_approved(frame, not approved)
            QMessageBox.warning(self, self.tr("Approve frame"), message)

    def _benchmark_selected(self) -> None:
        if self._selected_shot is None:
            QMessageBox.warning(self, self.tr("Benchmark"), self.tr("Select a shot first."))
            return
        answer = QMessageBox.question(
            self,
            self.tr("Benchmark selected shot"),
            self.tr(
                "Rent one Vast.ai node and render 3 representative frames of {0}?\n\n"
                "The median time updates the measured profile. Estimated cost: ~$0.05."
            ).format(self._selected_shot.name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.vm.benchmark_selected(self._selected_shot)

    def _on_benchmark_finished(self, shot_name: str, median: float) -> None:
        self._append_log(f"Benchmark {shot_name}: {median:.1f} s/frame")
        QMessageBox.information(
            self,
            self.tr("Benchmark finished"),
            self.tr("{0}: {1:.1f} s/frame. The plan will be recalculated.").format(
                shot_name, median
            ),
        )

    def _on_preview_ready(self, shot_name: str, image_path: str) -> None:
        if self._selected_shot is not None and self._selected_shot.name == shot_name:
            self._load_preview_image(Path(image_path))
        self._append_log(f"Preview ready: {shot_name}")

    def _on_preview_progress(self, shot_name: str, done: int, total: int, seconds: float) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))
        self._append_log(f"{shot_name}: preview frame {done}/{total} ({seconds:.1f}s)")

    def _on_preview_finished(self, rendered: int, total: int) -> None:
        self._append_log(f"Previews finished: {rendered}/{total}")

    def _show_latest_preview(self, shot: RenderShot) -> None:
        path = self.vm.preview_paths.get(shot.name)
        if path is None or not path.is_file():
            base = self.vm.service.preview_dir(
                self.vm.project_root, shot, task_type=self.vm.settings.task_type
            )
            candidates = sorted(base.glob("*/frame_*.png"), reverse=True)
            path = candidates[0] if candidates else None
        if path is not None and Path(path).is_file():
            self._load_preview_image(Path(path))
        else:
            self._clear_preview(self.tr("No preview yet. Click Preview selected."))

    def _load_preview_image(self, path: Path) -> None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._clear_preview(self.tr("Preview could not be loaded."))
            return
        self._current_preview = str(path)
        self.preview_label.setPixmap(
            pixmap.scaled(520, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.preview_label.setToolTip(str(path))

    def _clear_preview(self, message: str = "") -> None:
        self._current_preview = ""
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(message or self.tr("Select a shot to see its preview."))

    # ------------------------------------------------------------------
    # Render / video
    # ------------------------------------------------------------------
    def _start_render(self) -> None:
        if self._plan is None or not self._plan.shots:
            QMessageBox.warning(self, self.tr("Render"), self.tr("Calculate a plan first."))
            return
        answer = QMessageBox.question(
            self,
            self.tr("Start render"),
            self.tr(
                "Render {0} frame(s) on {1} node(s)?\n\n"
                "Backend: {2}\nEstimated wall time: {3:.2f} h\nEstimated cost: ${4:.2f}"
            ).format(
                self._plan.total_frames,
                self._plan.required_nodes,
                self.vm.settings.render_backend,
                self._plan.estimated_wall_hours,
                self._plan.estimated_cost,
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.progress.setRange(0, max(1, self._plan.total_frames))
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self._append_log("Starting render...")
        self.vm.start_render()

    def _cancel_render(self) -> None:
        self._append_log("Cancelling render...")
        self.vm.cancel_render()

    def _create_video(self) -> None:
        self.vm.create_review_videos()

    def _create_preview_video(self) -> None:
        if self._selected_shot is None:
            QMessageBox.warning(self, self.tr("Render"), self.tr("Select a shot first."))
            return
        self.vm.create_preview_videos([self._selected_shot])

    def _retry_render(self) -> None:
        if not self.vm.start_render(retry=True):
            return
        self.btn_retry_render.hide()
        self._append_log("Retrying the missing frames...")

    def _open_run_logs(self) -> None:
        folder = self.vm.run_log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_local_progress(self, shot_name: str, done: int, total: int, seconds: float) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))
        self._append_log(f"{shot_name}: frame {done}/{total} ({seconds:.1f}s)")

    def _on_burst_progress(self, event) -> None:
        self._append_log(
            f"[node {event.node}] {event.stage}: {event.message}"
        )
        if event.frames_total > 0:
            self.progress.setRange(0, event.frames_total)
            self.progress.setValue(min(event.frames_done, event.frames_total))

    def _on_render_finished(self, report) -> None:
        self.progress.setValue(self.progress.maximum())
        self.btn_cancel.setEnabled(False)
        missing = self._report_missing_frames(report)
        self.btn_retry_render.setVisible(bool(missing))
        self.btn_start.setEnabled(
            self._plan is not None
            and self._plan.total_frames > 0
            and (
                self.vm.settings.render_backend != "vast"
                or self.vm.offer is not None
            )
        )
        if isinstance(report, list):
            rendered = sum(item.frames_rendered for item in report)
            expected = sum(item.frames_expected for item in report)
            message = self.tr("Local render: {0}/{1} frame(s).").format(
                rendered, expected
            )
        else:
            message = getattr(report, "message", "Render finished.")
        self._append_log(message)
        if not missing and self._selected_shot is not None:
            self._play_final_sequence()
        QMessageBox.information(self, self.tr("Render finished"), message)

    def _on_video_ready(self, shot_name: str, video_path: str) -> None:
        self._append_log(f"Review video ready for {shot_name}: {video_path}")
        if self._selected_shot is not None and self._selected_shot.name == shot_name:
            self.lbl_video.setText(video_path)
        self._populate_kitsu_statuses()

    def _on_preview_video_ready(self, shot_name: str, video_path: str) -> None:
        self._append_log(f"Preview video ready for {shot_name}: {video_path}")

    def _on_videos_finished(self, created: int, total: int) -> None:
        self._append_log(f"Videos created: {created}/{total}")

    @staticmethod
    def _report_missing_frames(report) -> int:
        if isinstance(report, list):
            return sum(len(item.missing) for item in report)
        return len(getattr(report, "missing", ()) or ())

    def _show_video(self, shot: RenderShot) -> None:
        path = self.vm.video_paths.get(shot.name)
        if path is not None and path.is_file():
            self.lbl_video.setText(str(path))
        else:
            self.lbl_video.setText(self.tr("No review video yet."))

    # ------------------------------------------------------------------
    # Kitsu
    # ------------------------------------------------------------------
    def _on_kitsu_statuses(self, statuses: list) -> None:
        self.combo_kitsu_status.clear()
        for status in statuses:
            self.combo_kitsu_status.addItem(str(status.get("name") or "-"), status)
        self._populate_kitsu_statuses()

    def _populate_kitsu_statuses(self) -> None:
        # The combo is populated by the signal; this is a hook for future
        # preselection of the task's current status.
        pass

    def _upload_kitsu(self) -> None:
        if self._selected_shot is None:
            return
        status = self.combo_kitsu_status.currentData()
        if not isinstance(status, dict):
            QMessageBox.warning(self, self.tr("Kitsu"), self.tr("Select a task status first."))
            return
        video = self.vm.video_paths.get(self._selected_shot.name)
        if video is None or not video.is_file():
            QMessageBox.warning(self, self.tr("Kitsu"), self.tr("Create the review video first."))
            return
        comment = self.txt_comment.text().strip() or f"Render review: {self._selected_shot.name}"
        self.vm.upload_to_kitsu(self._selected_shot.name, status, comment)

    def _on_kitsu_upload_finished(self, ok: bool, message: str) -> None:
        self._append_log(message)
        if ok:
            QMessageBox.information(self, self.tr("Kitsu"), message)
        else:
            QMessageBox.critical(self, self.tr("Kitsu"), message)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    def _on_busy_changed(self, busy: bool) -> None:
        for widget in (
            self.combo_projects,
            self.btn_refresh,
            self.btn_recalculate,
            self.btn_preview_selected,
            self.btn_preview_all,
            self.btn_benchmark,
            self.btn_play_final,
            self.btn_preview_video,
            self.btn_video,
            self.btn_open_logs,
        ):
            widget.setEnabled(not busy)
        if busy:
            self.btn_start.setEnabled(False)
        elif self._plan is not None and self._plan.total_frames > 0:
            self.btn_start.setEnabled(
                self.vm.settings.render_backend != "vast"
                or self.vm.offer is not None
            )

    def _on_scan_progress(self, name: str, index: int, total: int) -> None:
        self.lbl_setup.setText(
            self.tr("Scanning {0} ({1}/{2})...").format(name, index, total)
        )

    def _on_error(self, message: str) -> None:
        self._append_log(message)
        self.btn_cancel.setEnabled(False)
        QMessageBox.critical(self, self.tr("Render"), message)

    def _open_output(self) -> None:
        if self.vm.project_root is None:
            return
        path = self.vm.service.render_root(self.vm.project_root)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _summary_html(self, plan: RenderPlan, offer) -> str:
        if offer is not None:
            offer_text = (
                f"{offer.gpu_name} ${offer.price_per_hour:.3f}/h · "
                f"{offer.geolocation or '?'} · "
                f"{offer.inet_down_mbps:.0f}/{offer.inet_up_mbps:.0f} Mbps"
            )
        elif self.vm.settings.render_backend == "vast":
            offer_text = self.tr("no offer within the price/network limits")
        else:
            offer_text = self.tr("local")
        return self.tr(
            "<b>{0}</b> frames · <b>{1:.2f}</b> GPU-h · "
            "<b>{2}</b> node(s) · ETA <b>{3:.2f} h</b> · "
            "cost <b>${4:.2f}</b> · confidence <b>{5}</b><br>"
            "Offer: {6} · setup {7:.0f} min/node · utilization {8:.0%}"
        ).format(
            plan.total_frames,
            plan.total_gpu_seconds / 3600.0,
            plan.required_nodes,
            plan.estimated_wall_hours,
            plan.estimated_cost,
            plan.confidence,
            offer_text,
            plan.setup_seconds / 60.0,
            plan.utilization,
        )

    def _append_log(self, message: str) -> None:
        self.log.appendPlainText(message)
