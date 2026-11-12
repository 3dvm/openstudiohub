# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/shot_review_card.py
# Architectural role: UI component / collapsible per-shot render review
# =========================================================================================

"""Collapsible shot card with render progress, status and per-shot actions."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.interfaces.qt.ui_format import format_rate

_STATUS_COLORS = {
    "not_ready": "#EF4444",
    "check_setup": "#F59E0B",
    "rendering": "#F59E0B",
    "queued": "#38BDF8",
    "failed": "#EF4444",
    "finished": "#10B981",
    "in_review": "#38BDF8",
    "with_renders": "#A78BFA",
    "ready": "#94A3B8",
}


class ShotReviewCard(QFrame):
    selection_changed = Signal(str, bool)
    activated = Signal(str)
    action_requested = Signal(str, str)
    inspector_requested = Signal(str, str)
    publish_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ShotReviewCard")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._shot_name = ""
        self._shot_path = ""
        self._model = None
        self._busy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        header = QHBoxLayout()
        self.check = QCheckBox()
        self.check.toggled.connect(self._on_selection_changed)
        header.addWidget(self.check)

        self.toggle = QToolButton()
        self.toggle.setObjectName("ShotReviewToggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setArrowType(Qt.RightArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.clicked.connect(self._on_toggle)
        header.addWidget(self.toggle)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("font-weight: bold;")
        header.addWidget(self.lbl_status)
        self.lbl_deps = QLabel("")
        self.lbl_deps.setObjectName("MutedLabel")
        self.lbl_deps.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        header.addWidget(self.lbl_deps)
        header.addStretch()
        outer.addLayout(header)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet("color: #94A3B8; font-size: 11px;")
        outer.addWidget(self.lbl_progress)
        for label in (self.lbl_status, self.lbl_deps, self.lbl_progress):
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.content = QWidget()
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(24, 0, 0, 0)
        content_layout.setSpacing(6)
        self.lbl_details = QLabel("")
        self.lbl_details.setWordWrap(True)
        self.lbl_details.setStyleSheet("color: #CBD5E1; font-size: 11px;")
        self.lbl_details.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        content_layout.addWidget(self.lbl_details)

        self.lbl_warnings = QLabel("")
        self.lbl_warnings.setWordWrap(True)
        self.lbl_warnings.setStyleSheet("color: #F59E0B; font-size: 11px;")
        self.lbl_warnings.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        content_layout.addWidget(self.lbl_warnings)

        self.setup_toggle = QToolButton()
        self.setup_toggle.setObjectName("ShotReviewToggle")
        self.setup_toggle.setCheckable(True)
        self.setup_toggle.setChecked(False)
        self.setup_toggle.setArrowType(Qt.RightArrow)
        self.setup_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setup_toggle.setText(self.tr("Shot setup"))
        self.setup_toggle.clicked.connect(self._on_setup_toggle)
        content_layout.addWidget(self.setup_toggle)
        self.lbl_setup = QLabel("")
        self.lbl_setup.setWordWrap(True)
        self.lbl_setup.setStyleSheet("color: #CBD5E1; font-size: 11px;")
        self.lbl_setup.hide()
        content_layout.addWidget(self.lbl_setup)

        primary = QHBoxLayout()
        self.btn_view = self._action_button("", "view", "View the rendered sequence")
        self.btn_view.setFixedWidth(32)
        self.set_view_playing(False)
        self.btn_preview = self._action_button(
            "Preview", "preview", "Render a preview frame for this shot"
        )
        self.btn_benchmark = self._action_button(
            "Benchmark", "benchmark", "Benchmark this shot on Vast.ai"
        )
        self.btn_render = self._action_button(
            "Render", "render", "Render only this shot"
        )
        self.btn_comments = self._inspector_button("Comments", "comments")
        self.btn_dependencies = self._inspector_button(
            "Dependencies", "dependencies"
        )
        self.btn_publish = QPushButton(self.tr("Publish"))
        self.btn_publish.setObjectName("SuccessButton")
        self.btn_publish.setToolTip(self.tr("Open Publish Shot for this shot"))
        self.btn_publish.clicked.connect(self._on_publish_clicked)
        primary.addWidget(self.btn_view)
        primary.addWidget(self.btn_preview)
        primary.addWidget(self.btn_benchmark)
        primary.addWidget(self.btn_render)
        primary.addWidget(self.btn_comments)
        primary.addWidget(self.btn_dependencies)
        primary.addWidget(self.btn_publish)
        primary.addStretch()
        content_layout.addLayout(primary)

        secondary = QHBoxLayout()
        self.btn_retry = self._action_button(
            "Retry", "retry", "Retry the missing frames of this shot"
        )
        self.btn_approve = self._action_button(
            "Approve", "approve_all", "Approve every rendered frame"
        )
        self.btn_delete = self._action_button(
            "Delete", "delete_unapproved", "Move unapproved frames to .frame_trash"
        )
        self.btn_more = QPushButton(self.tr("More"))
        self.btn_more.setObjectName("SecondaryButton")
        self.menu = QMenu(self)
        self._add_menu_action("Unapprove all", "unapprove_all")
        self._add_menu_action("Create preview video", "preview_video")
        self.menu.addSeparator()
        self._add_menu_action("Open output folder", "open_output")
        self._add_menu_action("Open .blend", "open_blend")
        self.btn_more.setMenu(self.menu)
        self.btn_more.clicked.connect(
            lambda _checked=False: self.activated.emit(self._shot_path)
        )
        secondary.addWidget(self.btn_retry)
        secondary.addWidget(self.btn_approve)
        secondary.addWidget(self.btn_delete)
        secondary.addWidget(self.btn_more)
        secondary.addStretch()
        content_layout.addLayout(secondary)
        outer.addWidget(self.content)
        self.content.setVisible(False)

    def _action_button(self, label: str, action: str, tooltip: str = "") -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("SecondaryButton")
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(
            lambda _checked=False, name=action: (
                self.activated.emit(self._shot_path),
                self.action_requested.emit(self._shot_path, name),
            )
        )
        button.setProperty("shotAction", action)
        return button

    def _inspector_button(self, label: str, tab: str) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("SecondaryButton")
        button.clicked.connect(
            lambda _checked=False, name=tab: (
                self.activated.emit(self._shot_path),
                self.inspector_requested.emit(self._shot_path, name),
            )
        )
        return button

    def _on_publish_clicked(self) -> None:
        self.activated.emit(self._shot_path)
        self.publish_requested.emit(self._shot_path)

    def _add_menu_action(self, label: str, action: str) -> None:
        item = self.menu.addAction(label)
        item.triggered.connect(
            lambda _checked=False, name=action: self.action_requested.emit(self._shot_path, name)
        )

    def update_model(self, model) -> None:
        self._model = model
        self._shot_name = model.name
        self._shot_path = model.relative_path
        self.check.blockSignals(True)
        self.check.setChecked(bool(model.selected))
        self.check.setEnabled(not model.locked)
        self.check.blockSignals(False)
        task = str(getattr(model, "task_type", "") or "").strip()
        header_text = f"{model.name} · {model.sequence}"
        if task:
            header_text += f" · {task}"
        self.toggle.setText(header_text)
        self.lbl_status.setText(model.status_label)
        self.lbl_status.setToolTip(model.status_tooltip)
        self.lbl_status.setStyleSheet(
            "font-weight: bold; color: "
            f"{_STATUS_COLORS.get(model.status, '#94A3B8')};"
        )
        self.lbl_progress.setText(
            f"R {model.rendered}/{model.frames} · A {model.approved}/{model.frames}"
        )
        dep_count = int(getattr(model, "dependency_count", 0) or 0)
        dep_blocking = int(getattr(model, "dependency_blocking_count", 0) or 0)
        if dep_count:
            self.lbl_deps.setText(
                self.tr("Deps {0} · {1} blocking").format(dep_count, dep_blocking)
            )
            color = "#EF4444" if dep_blocking else "#F59E0B"
            self.lbl_deps.setStyleSheet(f"color: {color}; font-size: 11px;")
            self.lbl_deps.setToolTip(
                self.tr("Show shot dependencies")
            )
        else:
            self.lbl_deps.setText("")
        self.lbl_setup.setText(str(getattr(model, "setup_html", "") or ""))
        self.lbl_progress.setToolTip(
            f"{model.rendered}/{model.frames} rendered · "
            f"{model.approved}/{model.frames} approved · "
            f"{model.missing} missing"
        )
        measured = (
            f"{format_rate(model.measured_seconds)}/frame"
            if model.measured_seconds is not None
            else "unmeasured"
        )
        details = (
            f"Frames {model.frame_range} · {model.engine} "
            f"{model.resolution} @ {model.samples} spp · "
            f"{model.image_format} · {measured}"
        )
        particle_state = str(getattr(model, "particle_state", "") or "")
        if particle_state:
            details += f" · {particle_state}"
        self.lbl_details.setText(details)
        self.lbl_warnings.setText(" · ".join(model.warnings) if model.warnings else "")
        self.lbl_warnings.setVisible(bool(model.warnings))

        can_render = model.ready and not model.locked
        self.btn_view.setEnabled(model.rendered > 0)
        self.btn_preview.setEnabled(can_render)
        self.btn_benchmark.setEnabled(can_render)
        self.btn_render.setEnabled(can_render)
        self.btn_retry.setEnabled(can_render and model.missing > 0)
        self.btn_approve.setEnabled(model.rendered > model.approved)
        self.btn_delete.setEnabled(model.rendered > model.approved)
        self.btn_more.setEnabled(model.ready)
        self._apply_busy_state()
        for action in self.menu.actions():
            text = action.text()
            if text == "Unapprove all":
                action.setEnabled(model.approved > 0)
            elif text in ("Create preview video", "Create review video"):
                action.setEnabled(model.rendered >= model.frames > 0)
            elif text == "Open output folder":
                action.setEnabled(True)
            elif text == "Open .blend":
                action.setEnabled(bool(model.ready))

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        if not self._busy and self._model is not None:
            self.update_model(self._model)
        else:
            self._apply_busy_state()

    def _apply_busy_state(self) -> None:
        if not self._busy:
            return
        for button in (
            self.btn_preview,
            self.btn_benchmark,
            self.btn_render,
            self.btn_retry,
            self.btn_approve,
            self.btn_delete,
            self.btn_more,
        ):
            button.setEnabled(False)
        for action in self.menu.actions():
            action.setEnabled(False)

    def _on_selection_changed(self, checked: bool) -> None:
        self.activated.emit(self._shot_path)
        self.selection_changed.emit(self._shot_path, bool(checked))

    def _on_setup_toggle(self) -> None:
        expanded = self.setup_toggle.isChecked()
        self.setup_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.lbl_setup.setVisible(expanded)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._shot_path:
            self.activated.emit(self._shot_path)
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.MouseButtonPress and self._shot_path:
            self.activated.emit(self._shot_path)
        return super().eventFilter(watched, event)

    def set_view_playing(self, playing: bool) -> None:
        icon = QStyle.SP_MediaStop if playing else QStyle.SP_MediaPlay
        self.btn_view.setIcon(self.style().standardIcon(icon))
        self.btn_view.setToolTip(
            self.tr("Stop sequence playback") if playing else self.tr("View the rendered sequence")
        )

    def set_active(self, active: bool) -> None:
        self.setProperty("active", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)

    def _on_toggle(self) -> None:
        expanded = self.toggle.isChecked()
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)
        self.activated.emit(self._shot_path)
