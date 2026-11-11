# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/render_panel_widget.py
# Architectural role: UI Widget / dedicated render panel
# =========================================================================================

"""Dedicated render panel: shot selection, setup audit, preview, burst and video."""

from __future__ import annotations

import traceback
import json
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
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
    QVBoxLayout,
    QWidget,
)

from src.domain.render.image_formats import IMAGE_FORMATS, image_format
from src.domain.render.models import RenderPlan, RenderQuality, RenderSettings, RenderShot
from src.interfaces.qt.components.collapsible_section import CollapsibleSection
from src.interfaces.qt.components.frame_sequence_player import FrameSequencePlayer
from src.interfaces.qt.components.preview_poster import PreviewPoster
from src.interfaces.qt.components.render_node_card import RenderNodeCard
from src.interfaces.qt.components.shot_review_card import ShotReviewCard
from src.interfaces.qt.ui_format import format_bytes, format_duration, format_rate
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
        self._current_preview = ""
        self._player_shot_path = ""
        self._syncing_preview_frame = False
        self._preview_active = False
        self._benchmark_active = False
        self._bake_touched = False
        self._node_card_widgets: dict[str, RenderNodeCard] = {}
        self._shot_cards: dict[str, ShotReviewCard] = {}
        self._shot_progress_timer = QTimer(self)
        self._shot_progress_timer.setInterval(2000)
        self._shot_progress_timer.timeout.connect(self._refresh_shot_progress)

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
        self.btn_refresh = QPushButton(self.tr("⟳ Re-scan"))
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.setFixedSize(100, 34)
        self.btn_refresh.setToolTip(
            self.tr("Re-run Blender for every .blend and refresh Kitsu tasks")
        )
        self.btn_refresh.clicked.connect(self._scan)
        header.addWidget(self.btn_refresh)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)

        left = QWidget()
        left.setMinimumWidth(430)
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
        self.shots_scroll = QScrollArea()
        self.shots_scroll.setObjectName("InvisibleScrollArea")
        self.shots_scroll.setWidgetResizable(True)
        self.shots_scroll.setFrameShape(QFrame.NoFrame)
        self.shots_container = QWidget()
        self.shots_container.setObjectName("TransparentGridContainer")
        self.shots_layout = QVBoxLayout(self.shots_container)
        self.shots_layout.setContentsMargins(0, 0, 0, 0)
        self.shots_layout.setSpacing(6)
        self.shots_layout.addStretch()
        self.shots_scroll.setWidget(self.shots_container)
        shots_layout.addWidget(self.shots_scroll, 1)
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
        self.lbl_busy = QLabel(
            self.tr(
                "Render process in progress — controls are locked. "
                "Use Stop all processes to cancel."
            )
        )
        self.lbl_busy.setObjectName("WarningLabel")
        self.lbl_busy.setWordWrap(True)
        self.lbl_busy.hide()
        right_layout.addWidget(self.lbl_busy)
        right_layout.addLayout(self._build_actions())

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        right_layout.addWidget(self.progress)

        preview_frame = CollapsibleSection(self.tr("Preview (composite)"))
        self.preview_section = preview_frame
        self.poster = PreviewPoster()
        self.preview_label = self.poster.image_label
        self.poster.play_requested.connect(self._play_final_sequence)
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.poster)
        self.player = FrameSequencePlayer()
        self.preview_stack.addWidget(self.player)
        preview_frame.add_widget(self.preview_stack)
        preview_frame_row = QHBoxLayout()
        preview_frame_row.addWidget(QLabel(self.tr("Preview frame")))
        self.spin_preview_frame = QSpinBox()
        self.spin_preview_frame.setRange(1, 1)
        self.spin_preview_frame.setEnabled(False)
        self.spin_preview_frame.valueChanged.connect(self._on_preview_frame_changed)
        preview_frame_row.addWidget(self.spin_preview_frame)
        self.lbl_preview_frame_range = QLabel("")
        self.lbl_preview_frame_range.setObjectName("MutedLabel")
        preview_frame_row.addWidget(self.lbl_preview_frame_range)
        preview_frame_row.addStretch()
        preview_frame.add_layout(preview_frame_row)
        preview_buttons = QHBoxLayout()
        self.btn_preview_all = QPushButton(self.tr("Preview all selected"))
        self.btn_preview_all.setObjectName("SecondaryButton")
        self.btn_preview_all.clicked.connect(self._preview_all)
        self.btn_benchmark_all = QPushButton(self.tr("Benchmark all selected"))
        self.btn_benchmark_all.setObjectName("SecondaryButton")
        self.btn_benchmark_all.clicked.connect(self._benchmark_all)
        preview_buttons.addWidget(self.btn_preview_all)
        preview_buttons.addWidget(self.btn_benchmark_all)
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
        right_layout.addStretch()
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 720])
        layout.addWidget(splitter, 1)

        if self.read_only:
            for widget in (
                self.btn_refresh,
                self.btn_preview_all,
                self.btn_benchmark_all,
                self.btn_start,
                self.btn_cancel,
                self.btn_stop_all,
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
        final_form.addRow(self.tr("Final backend"), self.combo_backend)

        self.combo_samples = QComboBox()
        self.combo_samples.addItems(["128", "256"])
        final_form.addRow(self.tr("Samples"), self.combo_samples)

        self.combo_image_format = QComboBox()
        for image_format_item in IMAGE_FORMATS:
            self.combo_image_format.addItem(
                image_format_item.label, image_format_item.identifier
            )
        self.combo_image_format.currentIndexChanged.connect(
            self._on_image_format_changed
        )
        final_form.addRow(self.tr("Image format"), self.combo_image_format)

        format_row = QHBoxLayout()
        self.combo_color_mode = QComboBox()
        self.combo_color_depth = QComboBox()
        format_row.addWidget(QLabel(self.tr("Mode")))
        format_row.addWidget(self.combo_color_mode)
        format_row.addWidget(QLabel(self.tr("Depth")))
        format_row.addWidget(self.combo_color_depth)
        format_row.addStretch()
        final_form.addRow(self.tr("Color"), format_row)
        self._on_image_format_changed()
        self.final_settings_section.add_widget(final_widget)

        preview_widget = QWidget()
        preview_form = QFormLayout(preview_widget)
        preview_form.setContentsMargins(0, 0, 0, 0)
        preview_form.setHorizontalSpacing(12)
        preview_form.setVerticalSpacing(6)

        self.combo_preview_backend = QComboBox()
        self.combo_preview_backend.addItem(self.tr("Local"), "local")
        self.combo_preview_backend.addItem(self.tr("Vast.ai"), "vast")
        preview_form.addRow(self.tr("Preview backend"), self.combo_preview_backend)

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
        self.combo_target.addItem(format_duration(3600), 1.0)
        self.combo_target.addItem(format_duration(7200), 2.0)
        self.combo_target.addItem(self.tr("Custom"), 0.0)
        self.spin_hours = QDoubleSpinBox()
        self.spin_hours.setRange(0.25, 48.0)
        self.spin_hours.setSingleStep(0.25)
        self.spin_hours.setSuffix(self.tr(" h"))
        self.spin_hours.setMinimumWidth(90)
        self.spin_hours.valueChanged.connect(self._update_target_duration)
        self.lbl_target_duration = QLabel("")
        self.lbl_target_duration.setObjectName("MutedLabel")
        self.combo_target.setMinimumWidth(120)
        target_row = QHBoxLayout()
        target_row.addWidget(self.combo_target, 2)
        target_row.addWidget(self.spin_hours, 1)
        target_row.addWidget(self.lbl_target_duration)
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
        self.spin_price.setMinimumWidth(95)
        self.spin_nodes = QSpinBox()
        self.spin_nodes.setRange(0, 64)
        self.spin_nodes.setSpecialValueText(self.tr("Auto"))
        self.spin_nodes.setMinimumWidth(85)
        self.spin_budget = QDoubleSpinBox()
        self.spin_budget.setRange(0.0, 1000.0)
        self.spin_budget.setPrefix("$")
        self.spin_budget.setMinimumWidth(95)
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
        self.combo_region.setMinimumWidth(150)
        self.spin_min_down = QDoubleSpinBox()
        self.spin_min_down.setRange(0.0, 10000.0)
        self.spin_min_down.setSuffix(self.tr(" Mbps down"))
        self.spin_min_down.setMinimumWidth(130)
        self.spin_min_up = QDoubleSpinBox()
        self.spin_min_up.setRange(0.0, 10000.0)
        self.spin_min_up.setSuffix(self.tr(" Mbps up"))
        self.spin_min_up.setMinimumWidth(120)
        self.spin_min_ram = QDoubleSpinBox()
        self.spin_min_ram.setRange(0.0, 1024.0)
        self.spin_min_ram.setDecimals(0)
        self.spin_min_ram.setSuffix(self.tr(" GB"))
        self.spin_min_ram.setSpecialValueText(self.tr("Auto"))
        self.spin_min_ram.setToolTip(
            self.tr(
                "Minimum system RAM per Vast.ai host. 0 = automatic: 60 GB "
                "when geometry nodes are baked on the node."
            )
        )
        self.spin_min_ram.setMinimumWidth(100)
        network_row.addWidget(self.combo_region)
        network_row.addWidget(self.spin_min_down)
        network_row.addWidget(self.spin_min_up)
        network_row.addWidget(self.spin_min_ram)
        network_row.addStretch()
        vast_form.addRow(self.tr("Network / RAM"), network_row)
        self.chk_bake_geometry_nodes = QCheckBox(
            self.tr("Bake geometry nodes on the node (skip cache upload)")
        )
        self.chk_bake_geometry_nodes.setToolTip(
            self.tr(
                "Exclude geometry-node bake caches from the upload and run "
                "the simulation bake on each Vast node before rendering."
            )
        )
        self.chk_bake_geometry_nodes.stateChanged.connect(
            self._on_bake_geometry_toggled
        )
        vast_form.addRow(self.chk_bake_geometry_nodes)
        self.vast_section.add_widget(vast_widget)

        self.settings_frame.add_widget(self.final_settings_section)
        self.settings_frame.add_widget(self.preview_settings_section)
        self.settings_frame.add_widget(self.vast_section)

        self.btn_recalculate = QPushButton(self.tr("Recalculate plan"))
        self.btn_recalculate.setObjectName("SecondaryButton")
        self.btn_recalculate.clicked.connect(self._recalculate)
        self.settings_frame.add_widget(self.btn_recalculate)

        layout.addWidget(self.settings_frame)
        self._sync_backend_sections()

    def _build_summary_frame(self) -> QFrame:
        frame = CollapsibleSection(self.tr("Plan"))
        header = QHBoxLayout()
        self.lbl_summary = QLabel(self.tr("Scan a project to calculate the plan."))
        self.lbl_summary.setObjectName("InfoLabel")
        self.lbl_summary.setWordWrap(True)
        header.addWidget(self.lbl_summary, 1)
        self.btn_refresh_candidates = QPushButton(self.tr("Refresh candidates"))
        self.btn_refresh_candidates.setObjectName("SecondaryButton")
        self.btn_refresh_candidates.clicked.connect(self._refresh_candidates)
        header.addWidget(self.btn_refresh_candidates)
        frame.add_layout(header)

        self.node_grid_widget = QWidget()
        self.node_grid_widget.setObjectName("TransparentGridContainer")
        self.node_grid = QGridLayout(self.node_grid_widget)
        self.node_grid.setContentsMargins(0, 0, 0, 0)
        self.node_grid.setHorizontalSpacing(8)
        self.node_grid.setVerticalSpacing(8)
        self.node_grid_scroll = QScrollArea()
        self.node_grid_scroll.setObjectName("InvisibleScrollArea")
        self.node_grid_scroll.setWidgetResizable(True)
        self.node_grid_scroll.setFrameShape(QFrame.NoFrame)
        self.node_grid_scroll.setMinimumHeight(180)
        self.node_grid_scroll.setMaximumHeight(380)
        self.node_grid_scroll.setWidget(self.node_grid_widget)
        self.node_grid_scroll.hide()
        frame.add_widget(self.node_grid_scroll)
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
        self.btn_stop_all = QPushButton(self.tr("Stop all processes"))
        self.btn_stop_all.setObjectName("DangerButton")
        self.btn_stop_all.clicked.connect(self._stop_all)
        self.btn_stop_all.setEnabled(False)
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
        actions.addWidget(self.btn_stop_all)
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
        self.player.delete_frames_requested.connect(self._delete_frames)
        self.player.approve_frames_requested.connect(self._approve_frames)
        self.player.playback_changed.connect(self._on_playback_changed)
        self.player.comment_posted.connect(self._on_comment_posted)
        self.player.comment_resolved.connect(self._on_comment_resolved)
        self.player.comment_deleted.connect(self._on_comment_deleted)
        self.combo_target.currentIndexChanged.connect(self._on_target_changed)
        self.combo_backend.currentIndexChanged.connect(self._on_final_backend_changed)
        self.combo_preview_backend.currentIndexChanged.connect(self._sync_backend_sections)
        projects_loaded = getattr(self.project_list_vm, "projects_loaded", None)
        if projects_loaded is not None:
            projects_loaded.connect(self._on_projects_loaded)

        self.vm.shots_ready.connect(self._on_shots_ready)
        self.vm.node_cards_ready.connect(self._on_node_cards_ready)
        self.vm.node_card_updated.connect(self._on_node_card_updated)
        self.vm.shot_reviews_ready.connect(self._on_shot_reviews_ready)
        self.vm.shot_launch_finished.connect(self._on_shot_launch_finished)
        self.vm.scan_progress.connect(self._on_scan_progress)
        self.vm.scan_error.connect(self._on_error)
        self.vm.preview_ready.connect(self._on_preview_ready)
        self.vm.preview_progress.connect(self._on_preview_progress)
        self.vm.preview_error.connect(self._on_error)
        self.vm.preview_finished.connect(self._on_preview_finished)
        self.vm.benchmark_progress.connect(self._on_burst_progress)
        self.vm.benchmark_finished.connect(self._on_benchmark_finished)
        self.vm.benchmarks_finished.connect(self._on_benchmarks_finished)
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
        self.vm.render_runs_changed.connect(self._on_render_runs_changed)
        self.vm.measurement_conflicts.connect(self._on_measurement_conflicts)
        self.vm.preview_running.connect(self._on_preview_running)
        self.vm.benchmark_running.connect(self._on_benchmark_running)

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
        self._bake_touched = False
        self._clear_shot_cards()
        self.lbl_setup.setText(self.tr("Render setup: scanning..."))
        self.lbl_summary.setText("")
        self.lbl_warnings.setText("")
        self.lbl_video.setText(self.tr("No review video yet."))
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._on_node_cards_ready([])
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
        self._update_target_duration()

    def _update_target_duration(self, _value: float = 0.0) -> None:
        if hasattr(self, "lbl_target_duration"):
            self.lbl_target_duration.setText(
                format_duration(self.spin_hours.value() * 3600)
            )

    def _on_image_format_changed(self, _index: int = 0) -> None:
        fmt = image_format(self.combo_image_format.currentData() or "PNG")
        mode = self.combo_color_mode.currentData()
        depth = self.combo_color_depth.currentData()
        self.combo_color_mode.blockSignals(True)
        self.combo_color_depth.blockSignals(True)
        self.combo_color_mode.clear()
        for item in fmt.modes:
            self.combo_color_mode.addItem(item, item)
        self.combo_color_depth.clear()
        for item in fmt.depths:
            self.combo_color_depth.addItem(item, item)
        mode_index = self.combo_color_mode.findData(mode)
        self.combo_color_mode.setCurrentIndex(
            mode_index if mode_index >= 0 else self.combo_color_mode.findData(fmt.default_mode)
        )
        depth_index = self.combo_color_depth.findData(depth)
        self.combo_color_depth.setCurrentIndex(
            depth_index if depth_index >= 0 else self.combo_color_depth.findData(fmt.default_depth)
        )
        self.combo_color_mode.blockSignals(False)
        self.combo_color_depth.blockSignals(False)

    def _sync_backend_sections(self, _index: int = 0) -> None:
        final_vast = self.combo_backend.currentData() == "vast"
        preview_vast = self.combo_preview_backend.currentData() == "vast"
        self.vast_section.setVisible(final_vast or preview_vast)

    def _on_final_backend_changed(self, index: int = 0) -> None:
        self._sync_backend_sections(index)
        backend = self.combo_backend.currentData()
        if backend:
            self.vm.set_render_backend(str(backend), self._settings_from_ui())

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
            file_format=self.combo_image_format.currentData() or "PNG",
            color_mode=self.combo_color_mode.currentData() or "RGBA",
            color_depth=self.combo_color_depth.currentData() or "8",
        )
        preview = replace(
            base.preview_quality,
            resolution_x=1920,
            resolution_y=1080,
            resolution_percentage=int(self.combo_preview_res.currentData() or 50),
            samples=int(self.combo_preview_samples.currentText()),
            file_format="PNG",
            color_mode="RGBA",
            color_depth="8",
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
            min_cpu_ram_gb=float(self.spin_min_ram.value()),
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
        self.combo_image_format.blockSignals(True)
        self.combo_color_mode.blockSignals(True)
        self.combo_color_depth.blockSignals(True)
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
            format_index = self.combo_image_format.findData(
                settings.final_quality.file_format
            )
            self.combo_image_format.setCurrentIndex(max(0, format_index))
            self._on_image_format_changed()
            mode_index = self.combo_color_mode.findData(
                settings.final_quality.color_mode
            )
            self.combo_color_mode.setCurrentIndex(max(0, mode_index))
            depth_index = self.combo_color_depth.findData(
                settings.final_quality.color_depth
            )
            self.combo_color_depth.setCurrentIndex(max(0, depth_index))
            region_index = self.combo_region.findData(settings.preferred_region)
            self.combo_region.setCurrentIndex(max(0, region_index))
            self.spin_min_down.setValue(float(settings.min_inet_down_mbps))
            self.spin_min_up.setValue(float(settings.min_inet_up_mbps))
            self.spin_min_ram.setValue(float(settings.min_cpu_ram_gb or 0.0))
            self.chk_video.setChecked(bool(settings.video_enabled))
            self.chk_bake_geometry_nodes.blockSignals(True)
            if settings.bake_geometry_nodes is None:
                self.chk_bake_geometry_nodes.setChecked(
                    self.vm.bake_geometry_nodes_effective()
                )
            else:
                self.chk_bake_geometry_nodes.setChecked(
                    bool(settings.bake_geometry_nodes)
                )
            self.chk_bake_geometry_nodes.blockSignals(False)
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
                self.combo_image_format,
                self.combo_color_mode,
                self.combo_color_depth,
                self.combo_region,
            ):
                widget.blockSignals(False)
        self._on_target_changed()
        self._sync_backend_sections()
        self._sync_preview_frame_control()

    def _scan(self) -> None:
        settings = self._settings_from_ui()
        self.vm.update_settings(settings)
        self.vm.scan(force=True)

    def _recalculate(self) -> None:
        settings = self._settings_from_ui()
        self.vm.update_settings(settings)
        self.vm.recalculate()

    def _on_bake_geometry_toggled(self, _state: int) -> None:
        self._bake_touched = True
        self.vm.update_settings(
            replace(
                self.vm.settings,
                bake_geometry_nodes=bool(
                    self.chk_bake_geometry_nodes.isChecked()
                ),
            )
        )

    # ------------------------------------------------------------------
    # Shots
    # ------------------------------------------------------------------
    def _on_shots_ready(
        self, shots: list, plan: RenderPlan, offer, balance: float, _candidates: list
    ) -> None:
        self._shots = list(shots)
        self._plan = plan
        self._apply_settings_to_ui()
        self.lbl_balance.setText(
            self.tr("Vast.ai balance: ${0:.2f}").format(balance)
            if self.vm.settings.render_backend == "vast"
            or self.vm.settings.preview_backend == "vast"
            else self.tr("Render backend: local")
        )
        self._sync_shot_cards()
        self.lbl_summary.setText(self._summary_html(plan, offer))
        self.lbl_warnings.setText("\n".join(plan.warnings))
        self.btn_start.setEnabled(
            plan.total_frames > 0
            and (
                self.vm.settings.render_backend != "vast"
                or offer is not None
            )
        )
        if self._shots and self._selected_shot is None:
            self._select_shot(self._shots[0].relative_path)
        self._append_log(
            f"Plan: {plan.total_frames} frame(s), {plan.required_nodes} node(s), "
            f"ETA {format_duration(plan.estimated_wall_seconds)}, ${plan.estimated_cost:.2f}."
        )

    def _refresh_candidates(self) -> None:
        if not self.vm.refresh_candidates():
            self._append_log("Candidate refresh is not available right now.")

    def _on_node_cards_ready(self, cards: list) -> None:
        while self.node_grid.count():
            item = self.node_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._node_card_widgets = {}
        for index, card in enumerate(cards or []):
            widget = RenderNodeCard()
            widget.relaunch_requested.connect(self._relaunch_node)
            widget.update_model(card)
            row, column = divmod(index, 4)
            self.node_grid.addWidget(widget, row, column)
            self._node_card_widgets[card.key] = widget
        self.node_grid_scroll.setVisible(bool(cards))
        self.btn_refresh_candidates.setVisible(
            self.vm.settings.render_backend == "vast"
        )

    def _on_node_card_updated(self, key: str) -> None:
        widget = self._node_card_widgets.get(str(key))
        if widget is None:
            return
        card = next(
            (item for item in self.vm.node_cards if item.key == str(key)),
            None,
        )
        if card is not None:
            widget.update_model(card)

    def _relaunch_node(self, key: str) -> None:
        card = self.vm.node_card(str(key))
        if card is None:
            return
        relaunch = self.vm.relaunch_plan(card)
        if relaunch is None:
            QMessageBox.warning(
                self,
                self.tr("Relaunch node"),
                self.tr("This node has no failed frames to relaunch."),
            )
            return
        launch = relaunch.launch
        frames = int(relaunch.plan.total_frames)
        shots = ", ".join(
            f"{shot.name} {shot.frame_start}-{shot.frame_end}"
            for shot in relaunch.shots[:6]
        )
        if len(relaunch.shots) > 6:
            shots += self.tr(" … +{0}").format(len(relaunch.shots) - 6)
        bake = (
            self.tr("bake geometry nodes on the node")
            if relaunch.bake_geometry_nodes
            else self.tr("upload the current caches")
        )
        answer = QMessageBox.question(
            self,
            self.tr("Relaunch failed node"),
            self.tr(
                "Relaunch Node {0} with a new Vast.ai offer?\n\n"
                "Frames: {1}\nShots: {2}\n"
                "GPU profile: {3} (max ${4:.2f}/h)\n"
                "Region: {5}\n"
                "Upload: {6} · {7:,} file(s) ({8})\n\n"
                "Estimated cost: ~${9:.2f}"
            ).format(
                card.node + 1,
                frames,
                shots,
                launch.gpu_profile,
                launch.max_price_per_hour,
                launch.preferred_region,
                format_bytes(int(getattr(relaunch.staging, "bytes", 0) or 0)),
                int(getattr(relaunch.staging, "files", 0) or 0),
                bake,
                float(relaunch.plan.estimated_cost or 0.0),
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.vm.relaunch_node(card, relaunch)

    def _sync_shot_cards(self) -> None:
        reviews = {model.relative_path: model for model in self.vm.shot_reviews()}
        for path in list(self._shot_cards):
            if path not in reviews:
                card = self._shot_cards.pop(path)
                card.setParent(None)
                card.deleteLater()
        for index, model in enumerate(reviews.values()):
            card = self._shot_cards.get(model.relative_path)
            if card is None:
                card = ShotReviewCard()
                card.selection_changed.connect(self._on_shot_selection_changed)
                card.activated.connect(self._select_shot)
                card.action_requested.connect(self._on_shot_action)
                self.shots_layout.insertWidget(max(0, self.shots_layout.count() - 1), card)
                self._shot_cards[model.relative_path] = card
            card.update_model(model)
            card.set_active(
                self._selected_shot is not None
                and self._selected_shot.relative_path == model.relative_path
            )

    def _set_active_card(self, relative_path: str) -> None:
        for path, card in self._shot_cards.items():
            card.set_active(path == relative_path)

    def _on_playback_changed(self, playing: bool) -> None:
        for card in self._shot_cards.values():
            card.set_view_playing(False)
        if playing and self._selected_shot is not None:
            card = self._shot_cards.get(self._selected_shot.relative_path)
            if card is not None:
                card.set_view_playing(True)

    def _on_shot_reviews_ready(self, _reviews: list) -> None:
        self._sync_shot_cards()
        self._refresh_action_buttons()

    def _on_shot_launch_finished(
        self, relative_path: str, ok: bool, message: str
    ) -> None:
        self._append_log(message)
        if not ok:
            QMessageBox.warning(self, self.tr("Open .blend"), message)

    def _on_shot_selection_changed(self, relative_path: str, checked: bool) -> None:
        selected = [
            path
            for path, card in self._shot_cards.items()
            if card.check.isChecked()
        ]
        if checked and relative_path not in selected:
            selected.append(relative_path)
        self.vm.set_selected_shots(selected)
        self._sync_shot_cards()

    def _select_shot(self, relative_path: str) -> None:
        shot = next(
            (candidate for candidate in self._shots if candidate.relative_path == relative_path),
            None,
        )
        if shot is None:
            return
        self._selected_shot = shot
        self._player_shot_path = ""
        self._set_active_card(shot.relative_path)
        self.player.pause()
        self._set_preview_page(self.poster)
        self._sync_preview_frame_control()
        self._refresh_action_buttons()
        self._show_setup(shot)
        self._show_latest_preview(shot)
        self._show_video(shot)

    def _on_shot_action(self, relative_path: str, action: str) -> None:
        shot = next(
            (candidate for candidate in self._shots if candidate.relative_path == relative_path),
            None,
        )
        if shot is None:
            return
        if action == "view":
            if (
                self._selected_shot is not None
                and self._selected_shot.relative_path == shot.relative_path
                and self.player.is_playing()
            ):
                self.player.pause()
            else:
                self._show_sequence_for_shot(shot)
            return
        if action == "preview":
            self._apply_preview_settings()
            if self._confirm_preview([shot]):
                self._set_preview_page(self.poster)
                self.vm.preview_shots([shot])
            return
        if action == "benchmark":
            self._benchmark_shot(shot)
            return
        if action in ("render", "retry"):
            if not self._confirm_shot_render(shot, action == "retry"):
                return
            started = (
                self.vm.retry_missing_shot(shot)
                if action == "retry"
                else self.vm.render_single_shot(shot)
            )
            if started:
                self._shot_progress_timer.start()
                self._refresh_shot_progress()
            return
        if action == "approve_all":
            ok, message = self.vm.approve_all_rendered(shot)
            self._append_log(message)
            if not ok:
                QMessageBox.warning(self, self.tr("Approve frames"), message)
            else:
                self._sync_player_approvals(shot)
        elif action == "unapprove_all":
            ok, message = self.vm.unapprove_all(shot)
            self._append_log(message)
            if not ok:
                QMessageBox.warning(self, self.tr("Unapprove frames"), message)
            else:
                self._sync_player_approvals(shot)
        elif action == "delete_unapproved":
            if not self._confirm_delete_unapproved(shot):
                return
            ok, message = self.vm.delete_unapproved(shot)
            self._append_log(message)
            if not ok:
                QMessageBox.warning(self, self.tr("Delete unapproved"), message)
        elif action == "preview_video":
            self.vm.create_preview_videos([shot])
        elif action == "review_video":
            self.vm.create_review_videos([shot])
        elif action == "open_output":
            folder = self.vm.service.shot_output_dir(
                self.vm.project_root, shot, self.vm.settings.task_type
            )
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        elif action == "open_blend":
            self.vm.open_shot_blend(shot)
        self._refresh_shot_progress()

    def _confirm_shot_render(self, shot: RenderShot, retry: bool) -> bool:
        text = (
            f"Retry only the missing frames of {shot.name}?"
            if retry
            else f"Render {shot.name} on its own node(s)?"
        )
        answer = QMessageBox.question(
            self,
            self.tr("Render shot"),
            self.tr(text),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _confirm_delete_unapproved(self, shot: RenderShot) -> bool:
        answer = QMessageBox.question(
            self,
            self.tr("Delete unapproved frames"),
            self.tr(
                "Move every unapproved rendered frame of {0} to .frame_trash?"
            ).format(shot.name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _benchmark_shot(self, shot: RenderShot) -> None:
        self._run_benchmark(shot)

    def _run_benchmark(self, shot: RenderShot) -> None:
        proceed, overwrite = self._confirm_benchmark(shot)
        if proceed:
            self.vm.benchmark_selected(shot, overwrite=overwrite)

    def _confirm_benchmark(self, shot: RenderShot) -> tuple[bool, bool]:
        estimate = self.vm.benchmark_estimate(shot)
        existing = self.vm.measurement_for(shot)
        overwrite = existing is not None
        if estimate is None:
            text = self.tr(
                "Rent one Vast.ai node and measure representative frames of {0}?\n\n"
                "The median time updates the measured profile."
            ).format(shot.name)
        else:
            selection = estimate.selection
            frames = ", ".join(str(frame) for frame in selection.frames)
            folders = "\n".join(
                f"  - {entry.label}: {format_bytes(entry.bytes)} "
                f"({entry.files:,} file(s))"
                for entry in estimate.staging.entries
            ) or "  - (no production folder found)"
            offer = getattr(self.vm, "offer", None)
            gpu = str(getattr(offer, "gpu_name", "") or "").strip()
            price = float(getattr(offer, "price_per_hour", 0.0) or 0.0)
            if price > 0:
                node = self.tr("1 node ({0}, {1}) at ${2:.2f}/h").format(
                    gpu or self.vm.settings.gpu_profile,
                    self.vm.settings.gpu_profile,
                    price,
                )
            else:
                node = self.tr("1 node ({0}), cheapest available").format(
                    gpu or self.vm.settings.gpu_profile
                )
            text = self.tr(
                "Benchmark {0}\n\n"
                "File: {1}\n"
                "Frames to measure: {2}\n"
                "Scene range: {3}-{4} (step {5})\n"
                "Node: {6}\n"
                "Upload: {7} · {8:,} file(s)\n"
                "{9}\n\n"
                "Estimated cost: ~${10:.2f}\n"
                "The median time updates the measured profile."
            ).format(
                shot.name,
                shot.relative_path,
                frames,
                selection.range_start,
                selection.range_end,
                selection.step,
                node,
                format_bytes(estimate.staging.bytes),
                estimate.staging.files,
                folders,
                float(getattr(estimate.plan, "estimated_cost", 0.0) or 0.0),
            )
        if overwrite:
            existing_text = self.tr(
                "{0} already has a remote benchmark of {1}/frame ({2}).\n\n"
                "Overwrite it with this new benchmark?"
            ).format(
                shot.name,
                format_rate(existing.get("seconds")),
                str(existing.get("measured_at") or "") or self.tr("date unknown"),
            )
            text = f"{existing_text}\n\n{text}"
        title = (
            self.tr("Overwrite benchmark")
            if overwrite
            else self.tr("Benchmark shot")
        )
        answer = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes, overwrite

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
    def _sync_preview_frame_control(self) -> None:
        shot = self._selected_shot
        self._syncing_preview_frame = True
        try:
            if shot is None:
                self.spin_preview_frame.setEnabled(False)
                self.lbl_preview_frame_range.setText("")
                return
            self.spin_preview_frame.setRange(shot.frame_start, shot.frame_end)
            self.spin_preview_frame.setValue(self.vm.preview_frame_for(shot))
            self.spin_preview_frame.setEnabled(True)
            self.lbl_preview_frame_range.setText(
                self.tr("of {0}–{1}").format(shot.frame_start, shot.frame_end)
            )
        finally:
            self._syncing_preview_frame = False

    def _on_preview_frame_changed(self, frame: int) -> None:
        if self._syncing_preview_frame or self._selected_shot is None:
            return
        self.vm.set_preview_frame(self._selected_shot, int(frame))

    def _preview_all(self) -> None:
        targets = self.vm.selected_shots
        self._apply_preview_settings()
        if self._confirm_preview(targets):
            self._set_preview_page(self.poster)
            self.vm.preview_shots(targets)

    def _apply_preview_settings(self) -> None:
        self.vm.update_preview_settings(self._settings_from_ui())

    def _confirm_preview(self, shots: list) -> bool:
        if not shots:
            QMessageBox.warning(
                self, self.tr("Preview"), self.tr("Select at least one shot.")
            )
            return False
        if self.vm.settings.preview_backend == "vast":
            target = self.tr("on Vast.ai")
            detail = self.tr(
                "One frame will be rendered per shot. Vast.ai may rent a node."
            )
        else:
            target = self.tr("locally")
            detail = self.tr(
                "One frame will be rendered per shot on this workstation."
            )
        answer = QMessageBox.question(
            self,
            self.tr("Render previews"),
            self.tr("Render {0} preview(s) {1}?\n\n{2}").format(
                len(shots), target, detail
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _play_final_sequence(self) -> None:
        if self._selected_shot is None:
            QMessageBox.warning(self, self.tr("Render"), self.tr("Select a shot first."))
            return
        self._show_sequence_for_shot(self._selected_shot)

    def _show_sequence_for_shot(self, shot: RenderShot) -> None:
        entries = self.vm.sequence_entries(shot)
        if not entries:
            QMessageBox.information(
                self,
                self.tr("Render"),
                self.tr("No frame range was found for this shot."),
            )
            return
        self._selected_shot = shot
        self._player_shot_path = shot.relative_path
        self._set_active_card(shot.relative_path)
        fps = shot.setup.fps if shot.setup else 24.0
        if not self.player.is_fullscreen():
            self._set_preview_page(self.player)
        self.player.set_sequence(
            entries,
            fps=fps,
            approved=self.vm.approved_frames(shot),
            comments=self.vm.render_comments(shot),
            autoplay=True,
        )
        rendered = sum(1 for _frame, path in entries if path is not None)
        self._append_log(
            f"Playing final sequence for {shot.name} "
            f"({rendered}/{len(entries)} frame(s))."
        )

    def _clear_shot_cards(self) -> None:
        for card in self._shot_cards.values():
            card.setParent(None)
            card.deleteLater()
        self._shot_cards = {}
        self._selected_shot = None
        self._shots = []

    def _refresh_shot_progress(self) -> None:
        if not self._shots:
            return
        self._sync_shot_cards()

    def _on_comment_posted(self, scope: str, frame: int, text: str) -> None:
        if self._selected_shot is None:
            return
        comments = self.vm.add_render_comment(
            self._selected_shot,
            text,
            frame=frame if scope == "frame" else None,
        )
        self.player.set_comments(comments)

    def _on_comment_resolved(self, comment_id: str, resolved: bool) -> None:
        if self._selected_shot is None:
            return
        comments = self.vm.resolve_render_comment(
            self._selected_shot, comment_id, resolved
        )
        self.player.set_comments(comments)

    def _on_comment_deleted(self, comment_id: str) -> None:
        if self._selected_shot is None:
            return
        comments = self.vm.delete_render_comment(self._selected_shot, comment_id)
        self.player.set_comments(comments)

    def _delete_frames(self, frames: list) -> None:
        if self._selected_shot is None or not frames:
            return
        ok, message, deleted = self.vm.delete_frames(self._selected_shot, frames)
        self._append_log(message)
        if ok:
            self.player.remove_frames(list(deleted))
        else:
            QMessageBox.warning(self, self.tr("Delete frames"), message)

    def _approve_frames(self, frames: list, approved: bool) -> None:
        if self._selected_shot is None or not frames:
            return
        ok, message = self.vm.approve_frames(self._selected_shot, frames, approved)
        self._append_log(message)
        self._sync_player_approvals(self._selected_shot)
        if not ok:
            QMessageBox.warning(self, self.tr("Approve frames"), message)

    def _sync_player_approvals(self, shot: RenderShot) -> None:
        if (
            self._selected_shot is None
            or self._selected_shot.relative_path != shot.relative_path
            or self._player_shot_path != shot.relative_path
        ):
            return
        self.player.set_approved_frames(self.vm.approved_frames(shot))

    def _benchmark_all(self) -> None:
        shots = self.vm.selected_shots
        if not shots:
            QMessageBox.warning(
                self, self.tr("Benchmark"), self.tr("Select at least one shot.")
            )
            return
        estimate = self.vm.benchmark_batch_estimate(shots)
        proceed, overwrite = self._confirm_benchmark_batch(shots, estimate)
        if proceed:
            self.vm.benchmark_shots(shots, overwrite=overwrite)

    def _confirm_benchmark_batch(self, shots: list, estimate) -> tuple[bool, bool]:
        existing = [shot for shot in shots if self.vm.measurement_for(shot) is not None]
        overwrite = bool(existing)
        if estimate is None or not getattr(estimate, "shots", ()):
            text = self.tr(
                "Rent one Vast.ai node and benchmark {0} shot(s)?\n\n"
                "The median time of each shot updates its measured profile."
            ).format(len(shots))
        else:
            lines = []
            for shot, selection in estimate.shots[:10]:
                frames = ", ".join(str(frame) for frame in selection.frames)
                task = shot.task_type or self.tr("no task")
                lines.append(f"  - {shot.name} ({task}): frames {frames}")
            if len(estimate.shots) > 10:
                lines.append(
                    self.tr("  - … and {0} more").format(len(estimate.shots) - 10)
                )
            offer = getattr(self.vm, "offer", None)
            gpu = str(getattr(offer, "gpu_name", "") or "").strip()
            price = float(getattr(offer, "price_per_hour", 0.0) or 0.0)
            if price > 0:
                node = self.tr("1 node ({0}, {1}) at ${2:.2f}/h").format(
                    gpu or self.vm.settings.gpu_profile,
                    self.vm.settings.gpu_profile,
                    price,
                )
            else:
                node = self.tr("1 node ({0}), cheapest available").format(
                    gpu or self.vm.settings.gpu_profile
                )
            text = self.tr(
                "Benchmark {0} shot(s) on one Vast.ai node\n\n"
                "{1}\n\n"
                "Node: {2}\n"
                "Upload: {3} · {4:,} file(s)\n\n"
                "Estimated cost: ~${5:.2f}\n"
                "Frames are written to each shot's render folder; fully approved "
                "shots are measured in .benchmarks/ only."
            ).format(
                len(estimate.shots),
                "\n".join(lines),
                node,
                format_bytes(estimate.staging.bytes),
                estimate.staging.files,
                float(getattr(estimate.plan, "estimated_cost", 0.0) or 0.0),
            )
        if overwrite:
            text = self.tr(
                "{0} selected shot(s) already have a benchmark. Overwrite them?"
            ).format(len(existing)) + "\n\n" + text
        title = (
            self.tr("Overwrite benchmarks")
            if overwrite
            else self.tr("Benchmark shots")
        )
        answer = QMessageBox.question(
            self, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        return answer == QMessageBox.Yes, overwrite

    def _on_benchmark_finished(self, shot_name: str, median: float) -> None:
        self._append_log(f"Benchmark {shot_name}: {format_rate(median)}/frame")
        QMessageBox.information(
            self,
            self.tr("Benchmark finished"),
            self.tr("{0}: {1}/frame. The plan will be recalculated.").format(
                shot_name, format_rate(median)
            ),
        )

    def _on_benchmarks_finished(self, results: list, message: str) -> None:
        self._append_log(message)
        lines = "\n".join(
            f"{name}: {format_rate(seconds)}/frame"
            for name, seconds in (results or ())
        )
        QMessageBox.information(
            self,
            self.tr("Benchmarks finished"),
            f"{message}\n\n{lines}".strip(),
        )

    def _on_preview_ready(self, shot_name: str, image_path: str) -> None:
        if self._selected_shot is not None and self._selected_shot.name == shot_name:
            self._load_preview_image(Path(image_path))
        self._append_log(f"Preview ready: {shot_name}")

    def _on_preview_progress(self, shot_name: str, done: int, total: int, seconds: float) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))
        self._append_log(
            f"{shot_name}: preview frame {done}/{total} ({format_rate(seconds)})"
        )

    def _on_preview_finished(
        self, rendered: int, total: int, failed: list, report
    ) -> None:
        self._append_log(f"Previews finished: {rendered}/{total}")
        failed = list(failed or [])
        summary = (
            f"{rendered}/{total} preview(s) rendered."
            if not failed
            else (
                f"{rendered}/{total} preview(s) rendered.\n\n"
                "Failed shots: " + ", ".join(failed)
            )
        )
        details = self._report_details(report) if failed else ""
        self._show_result_dialog(
            self.tr("Previews finished"),
            summary,
            details,
            report,
            retry_callback=self.vm.retry_failed_previews if failed else None,
        )

    def _set_preview_page(self, page) -> None:
        if self.preview_stack.indexOf(page) < 0:
            self._trace_preview_stack(
                "setCurrentWidget skipped: page is not contained in the stack"
            )
            return
        self.preview_stack.setCurrentWidget(page)

    def _trace_preview_stack(self, action: str) -> None:
        player = getattr(self, "player", None)
        parent = player.parentWidget() if player is not None else None
        fullscreen = bool(getattr(player, "_fullscreen_dialog", None)) if player else False
        print(
            f"[PreviewStack] {action}; player_parent={parent!r}; "
            f"fullscreen={fullscreen}; stack_count={self.preview_stack.count()}; "
            f"player_index={self.preview_stack.indexOf(player) if player else -1}"
        )
        print("".join(traceback.format_stack()))

    def _show_latest_preview(self, shot: RenderShot) -> None:
        path = self.vm.latest_preview_path(shot)
        if path is not None and path.is_file():
            self._load_preview_image(Path(path))
        else:
            self._clear_preview(self.tr("No preview yet. Click Preview selected."))

    def _load_preview_image(self, path: Path) -> None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._clear_preview(self.tr("Preview could not be loaded."))
            return
        self._current_preview = str(path)
        self._refresh_poster(path)

    def _clear_preview(self, message: str = "") -> None:
        self._current_preview = ""
        self._refresh_poster(None, message)

    def _refresh_poster(self, preview_path: Path | None, message: str = "") -> None:
        if self._selected_shot is None:
            self.poster.set_state(message=message or self.tr("Select a shot to see its preview."))
            return
        entries = self.vm.sequence_entries(self._selected_shot)
        rendered = [path for _frame, path in entries if path is not None]
        self.poster.set_state(
            preview_path=preview_path,
            fallback_frame=rendered[0] if rendered else None,
            has_sequence=bool(rendered),
            message=message,
        )

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
                "Backend: {2}\nEstimated wall time: {3}\nEstimated cost: ${4:.2f}{5}"
            ).format(
                self._plan.total_frames,
                self._plan.required_nodes,
                self.vm.settings.render_backend,
                format_duration(self._plan.estimated_wall_seconds),
                self._plan.estimated_cost,
                (
                    "\n\nGeometry-node bakes will run on each node before "
                    "the first frame."
                    if self.vm.bake_geometry_nodes_effective(
                        list(self._plan.shots)
                    )
                    else ""
                ),
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
        self._shot_progress_timer.start()
        if not self.vm.start_render():
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(self.vm.has_active_runs())

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

    def _stop_all(self) -> None:
        self._shot_progress_timer.stop()
        self.vm.stop_all_processes()
        self._append_log("Stopping every render process...")

    def _retry_render(self) -> None:
        if not self.vm.start_render(retry=True):
            return
        self.btn_retry_render.hide()
        self._shot_progress_timer.start()
        self._append_log("Retrying the missing frames...")

    def _open_run_logs(self) -> None:
        folder = self.vm.run_log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_local_progress(self, shot_name: str, done: int, total: int, seconds: float) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))
        self._append_log(
            f"{shot_name}: frame {done}/{total} ({format_rate(seconds)})"
        )

    def _on_burst_progress(self, event) -> None:
        stage = str(getattr(event, "stage", "") or "")
        message = str(getattr(event, "message", "") or "")
        if stage == "frame":
            try:
                payload = json.loads(message)
                self._append_log(
                    f"[node {event.node}] frame {payload.get('frame', '?')} · "
                    f"{format_rate(payload.get('seconds'))}"
                )
            except (TypeError, ValueError):
                self._append_log(f"[node {event.node}] frame: {message}")
        else:
            self._append_log(f"[node {event.node}] {stage}: {message}")
        if stage not in ("frame", "device", "bake"):
            self._refresh_shot_progress()
        if stage == "stage":
            total = int(getattr(event, "bytes_total", 0) or 0)
            done = int(getattr(event, "bytes_done", 0) or 0)
            if total > 0:
                self.progress.setRange(0, 100)
                self.progress.setValue(
                    max(0, min(100, int(done * 100 / total)))
                )
        if event.frames_total > 0:
            self.progress.setRange(0, event.frames_total)
            self.progress.setValue(min(event.frames_done, event.frames_total))

    def _on_render_finished(self, report) -> None:
        active = bool(self.vm.has_active_runs())
        if not active:
            self.progress.setValue(self.progress.maximum())
            self.btn_cancel.setEnabled(False)
            self._shot_progress_timer.stop()
        missing = self._report_missing_frames(report)
        self.btn_retry_render.setVisible(bool(missing) and not active)
        if isinstance(report, list):
            rendered = sum(item.frames_rendered for item in report)
            expected = sum(item.frames_expected for item in report)
            message = self.tr("Local render: {0}/{1} frame(s).").format(
                rendered, expected
            )
        else:
            message = getattr(report, "message", "Render finished.")
        self._refresh_shot_progress()
        self._append_log(message)
        if active:
            self._append_log(self.tr("Other render runs are still active."))
            return
        details = self._report_details(report)
        self._show_result_dialog(
            self.tr("Render finished"),
            message,
            details,
            report,
            retry_callback=self._retry_render if missing else None,
            view_callback=(
                self._play_final_sequence
                if not missing and self._selected_shot is not None
                else None
            ),
        )

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
    def _on_render_runs_changed(self, count: int) -> None:
        active = int(count or 0) > 0
        self.lbl_busy.setVisible(active)
        if active:
            self.lbl_busy.setText(
                self.tr(
                    "{0} render run(s) active — shots in those runs are locked. "
                    "Other shots can start on new instances."
                ).format(int(count))
            )
        self.btn_stop_all.setEnabled(active)
        self.btn_cancel.setEnabled(active)
        self.combo_projects.setEnabled(not active)
        plan = self.vm.plan or self._plan
        self.btn_start.setEnabled(
            bool(
                plan
                and plan.total_frames > 0
                and (
                    self.vm.settings.render_backend != "vast"
                    or self.vm.offer is not None
                )
            )
        )
        self._refresh_action_buttons()

    def _on_preview_running(self, running: bool) -> None:
        self._preview_active = bool(running)
        self._refresh_action_buttons()

    def _on_benchmark_running(self, running: bool) -> None:
        self._benchmark_active = bool(running)
        self._refresh_action_buttons()

    def _refresh_action_buttons(self) -> None:
        self.combo_projects.setEnabled(
            not (
                self._preview_active
                or self._benchmark_active
                or bool(self.vm.has_active_runs())
            )
        )
        targets = self.vm.selected_shots
        self.btn_preview_all.setEnabled(
            bool(targets)
            and not self._preview_active
            and not self._benchmark_active
            and not bool(self.vm.has_active_runs())
        )
        self.btn_benchmark_all.setEnabled(
            bool(targets)
            and not self._preview_active
            and not self._benchmark_active
            and not bool(self.vm.has_active_runs())
        )

    def _on_measurement_conflicts(self, conflicts: list) -> None:
        for item in conflicts or ():
            shot = item.get("shot")
            if shot is None:
                continue
            existing = item.get("existing") or {}
            backend = (
                self.tr("local")
                if str(item.get("backend")) == "local"
                else self.tr("remote")
            )
            measured_at = str(existing.get("measured_at") or "")
            answer = QMessageBox.question(
                self,
                self.tr("Overwrite benchmark"),
                self.tr(
                    "{0} finished with {1}/frame.\n\n"
                    "It already has a {2} benchmark of {3}/frame ({4}).\n"
                    "Replace the benchmark with the measured render time?"
                ).format(
                    shot.name,
                    format_rate(item.get("seconds")),
                    backend,
                    format_rate(existing.get("seconds")),
                    measured_at or self.tr("date unknown"),
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            self.vm.resolve_measurement_conflict(
                item, answer == QMessageBox.Yes
            )

    def _on_busy_changed(self, busy: bool) -> None:
        active_runs = bool(self.vm.has_active_runs())
        self.lbl_busy.setVisible(busy or active_runs)
        if busy:
            self.lbl_busy.setText(
                self.tr("Render process in progress — controls are locked.")
            )
        self.btn_stop_all.setEnabled(busy or active_runs)
        for card in self._shot_cards.values():
            card.set_busy(busy)
        for widget in (
            self.combo_projects,
            self.btn_refresh,
            self.btn_recalculate,
            self.btn_preview_all,
            self.btn_benchmark_all,
            self.btn_preview_video,
            self.btn_video,
            self.btn_open_logs,
        ):
            widget.setEnabled(not busy)
        if busy:
            self.btn_start.setEnabled(False)
            self.btn_cancel.setEnabled(True)
            self.btn_stop_all.setEnabled(True)
        else:
            active_runs = bool(self.vm.has_active_runs())
            self.btn_cancel.setEnabled(active_runs)
            self.btn_stop_all.setEnabled(active_runs)
            if self._plan is not None and self._plan.total_frames > 0:
                self.btn_start.setEnabled(
                    self.vm.settings.render_backend != "vast"
                    or self.vm.offer is not None
                )
        self._refresh_action_buttons()

    def _on_scan_progress(self, name: str, index: int, total: int) -> None:
        self.lbl_setup.setText(
            self.tr("Scanning {0} ({1}/{2})...").format(name, index, total)
        )

    def _on_error(self, message: str) -> None:
        if not self.vm.has_active_runs():
            self._shot_progress_timer.stop()
            self.btn_cancel.setEnabled(False)
            self.btn_stop_all.setEnabled(False)
        self._append_log(message)
        QMessageBox.critical(self, self.tr("Render"), message)

    @staticmethod
    def _report_details(report) -> str:
        if report is None:
            return ""
        nodes = getattr(report, "nodes", ()) or ()
        lines: list[str] = []
        for node in nodes:
            lines.append(
                f"Node {int(getattr(node, 'node', 0)) + 1}: "
                f"{getattr(node, 'stage', '')} · "
                f"{getattr(node, 'message', '')} · "
                f"{getattr(node, 'frames_done', 0)}/"
                f"{getattr(node, 'frames_expected', 0)} frames"
            )
        if not lines:
            message = getattr(report, "message", "")
            if message:
                lines.append(str(message))
        return "\n".join(lines)

    def _show_result_dialog(
        self,
        title: str,
        summary: str,
        details: str,
        report,
        *,
        retry_callback=None,
        view_callback=None,
    ) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(
            QMessageBox.Warning
            if retry_callback is not None
            else QMessageBox.Information
        )
        box.setText(summary)
        if details:
            box.setDetailedText(details)
        open_button = box.addButton(
            self.tr("Open log file"), QMessageBox.ActionRole
        )
        retry_button = (
            box.addButton(self.tr("Retry"), QMessageBox.ActionRole)
            if retry_callback is not None
            else None
        )
        view_button = (
            box.addButton(self.tr("View result"), QMessageBox.ActionRole)
            if view_callback is not None
            else None
        )
        box.addButton(QMessageBox.Close)
        box.exec()
        clicked = box.clickedButton()
        log_path = self.vm.latest_log_path(report)
        if clicked is open_button:
            if log_path.is_dir():
                log_path.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path)))
        elif retry_button is not None and clicked is retry_button:
            retry_callback()
        elif view_button is not None and clicked is view_button:
            view_callback()

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
            "<b>{2}</b> node(s) · ETA <b>{3}</b> · "
            "cost <b>${4:.2f}</b> · confidence <b>{5}</b><br>"
            "Offer: {6} · setup {7}/node · utilization {8:.0%}"
        ).format(
            plan.total_frames,
            plan.total_gpu_seconds / 3600.0,
            plan.required_nodes,
            format_duration(plan.estimated_wall_seconds),
            plan.estimated_cost,
            plan.confidence,
            offer_text,
            format_duration(plan.setup_seconds),
            plan.utilization,
        )

    def _append_log(self, message: str) -> None:
        self.log.appendPlainText(message)
