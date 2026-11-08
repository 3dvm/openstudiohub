# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/frame_sequence_player.py
# Architectural role: UI component / lightweight PNG sequence player
# =========================================================================================

"""Lightweight player for rendered frame sequences with review controls."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.interfaces.qt.components.frame_timeline import FrameTimeline

_CACHE_SIZE = 12
_ASSET_DIR = Path("assets/icons")


class FrameSequencePlayer(QWidget):
    """Play a list of ``(frame_number, path_or_none)`` entries at a fixed fps."""

    delete_frames_requested = Signal(list)
    approve_frames_requested = Signal(list, bool)
    position_changed = Signal(int)
    playback_changed = Signal(bool)
    comment_posted = Signal(str, int, str)
    comment_resolved = Signal(str, bool)
    comment_deleted = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[tuple[int, Path | None]] = []
        self._approved: set[int] = set()
        self._comment_frames: set[int] = set()
        self._comments: dict = {"shot": [], "frames": {}}
        self._cache: OrderedDict[int, QPixmap] = OrderedDict()
        self._fps = 24.0
        self._index = 0
        self._in_point: int | None = None
        self._out_point: int | None = None
        self._updating = False
        self._fullscreen_dialog: QDialog | None = None
        self._restore_stack: QStackedWidget | None = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(8)
        viewer = QWidget()
        viewer_layout = QVBoxLayout(viewer)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.setSpacing(6)

        self.image_label = QLabel(self.tr("No rendered frames."))
        self.image_label.setObjectName("MutedLabel")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(220)
        self.image_label.setWordWrap(True)
        viewer_layout.addWidget(self.image_label, 1)
        self.lbl_badge = QLabel(self.image_label)
        self.lbl_badge.setVisible(False)
        self.lbl_badge.setStyleSheet(
            "background-color: rgba(15, 23, 42, 190); border-radius: 10px; "
            "padding: 4px 8px; font-size: 11px; font-weight: bold;"
        )
        self.lbl_badge.move(10, 10)
        self.lbl_badge.raise_()

        self.timeline = FrameTimeline()
        self.timeline.seek_requested.connect(self._show_index)
        viewer_layout.addWidget(self.timeline)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.btn_step_back = self._icon_button("skip-back.svg", "Previous frame")
        self.btn_step_back.clicked.connect(lambda: self.step(-1))
        self.btn_play = self._icon_button("play.svg", "Play")
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_step_forward = self._icon_button("skip-forward.svg", "Next frame")
        self.btn_step_forward.clicked.connect(lambda: self.step(1))
        self.btn_loop = self._icon_button("repeat.svg", "Toggle loop")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setChecked(True)
        self.btn_loop.toggled.connect(self._on_loop_toggled)
        self.btn_fullscreen = self._icon_button("maximize.svg", "Fullscreen")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        self.btn_in = self._icon_button("arrow-left-to-line.svg", "Set in point")
        self.btn_in.clicked.connect(self._set_in_point)
        self.btn_out = self._icon_button("arrow-right-to-line.svg", "Set out point")
        self.btn_out.clicked.connect(self._set_out_point)
        self.btn_clear_range = QPushButton(self.tr("Clear"))
        self.btn_clear_range.setObjectName("SecondaryButton")
        self.btn_clear_range.clicked.connect(self._clear_range)
        self.btn_approve_selection = self._icon_button(
            "thumb-up.svg", "Approve selected frames"
        )
        self.btn_approve_selection.setObjectName("SuccessButton")
        self.btn_approve_selection.clicked.connect(self._on_approve_selection)
        self.btn_unapprove_selection = self._icon_button(
            "thumb-down.svg", "Unapprove selected frames"
        )
        self.btn_unapprove_selection.clicked.connect(self._on_unapprove_selection)
        self.btn_delete = self._icon_button(
            "trash-2.svg", "Delete selected frames"
        )
        self.btn_delete.setObjectName("DangerButton")
        self.btn_delete.clicked.connect(self._on_delete)
        for widget in (
            self.btn_step_back,
            self.btn_play,
            self.btn_step_forward,
            self.btn_loop,
            self.btn_fullscreen,
            self.btn_in,
            self.btn_out,
            self.btn_clear_range,
            self.btn_approve_selection,
            self.btn_unapprove_selection,
            self.btn_delete,
        ):
            controls.addWidget(widget)
        controls.addStretch()
        self.lbl_frame = QLabel(self.tr("Frame -/-"))
        self.lbl_frame.setObjectName("InfoLabel")
        controls.addWidget(self.lbl_frame)
        viewer_layout.addLayout(controls)

        self.lbl_range = QLabel(self.tr("Selection: current frame"))
        self.lbl_range.setObjectName("MutedLabel")
        viewer_layout.addWidget(self.lbl_range)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.valueChanged.connect(self._on_slider_changed)
        viewer_layout.addWidget(self.slider)
        main.addWidget(viewer, 3)

        self.comments_panel = QFrame()
        self.comments_panel.setObjectName("CardFrame")
        comments_layout = QVBoxLayout(self.comments_panel)
        comments_layout.setContentsMargins(10, 10, 10, 10)
        comments_layout.setSpacing(6)
        comments_header = QHBoxLayout()
        comments_title = QLabel(self.tr("Comments"))
        comments_title.setObjectName("SectionTitle")
        comments_header.addWidget(comments_title)
        comments_header.addStretch()
        self.combo_scope = QComboBox()
        self.combo_scope.addItem(self.tr("Shot"), "shot")
        self.combo_scope.currentIndexChanged.connect(self._refresh_comments)
        comments_header.addWidget(self.combo_scope)
        comments_layout.addLayout(comments_header)

        self.comments_list = QListWidget()
        self.comments_list.setObjectName("DataList")
        comments_layout.addWidget(self.comments_list, 1)
        input_row = QHBoxLayout()
        self.entry_comment = QLineEdit()
        self.entry_comment.setPlaceholderText(self.tr("Add a comment..."))
        input_row.addWidget(self.entry_comment, 1)
        self.btn_post = QPushButton(self.tr("Post"))
        self.btn_post.setObjectName("PrimaryButton")
        self.btn_post.clicked.connect(self._post_comment)
        input_row.addWidget(self.btn_post)
        comments_layout.addLayout(input_row)
        comment_actions = QHBoxLayout()
        self.btn_resolve = QPushButton(self.tr("Resolve"))
        self.btn_resolve.setObjectName("SecondaryButton")
        self.btn_resolve.clicked.connect(self._resolve_comment)
        self.btn_delete_comment = QPushButton(self.tr("Delete"))
        self.btn_delete_comment.setObjectName("SecondaryButton")
        self.btn_delete_comment.clicked.connect(self._delete_comment)
        comment_actions.addWidget(self.btn_resolve)
        comment_actions.addWidget(self.btn_delete_comment)
        comment_actions.addStretch()
        comments_layout.addLayout(comment_actions)
        main.addWidget(self.comments_panel, 2)

        self._set_controls_enabled(False)
        self._fullscreen_shortcut = QShortcut(QKeySequence(Qt.Key_F11), self)
        self._fullscreen_shortcut.activated.connect(self.toggle_fullscreen)

    # ------------------------------------------------------------------
    # Sequence
    # ------------------------------------------------------------------
    def set_sequence(
        self,
        entries: list[tuple[int, Path | None]],
        *,
        fps: float,
        approved: set[int] | None = None,
        comments: dict | None = None,
        autoplay: bool = True,
    ) -> None:
        self.pause()
        self._entries = list(entries)
        self._approved = set(approved or ())
        self._comments = comments or {"shot": [], "frames": {}}
        self._refresh_comment_frames()
        self._cache.clear()
        self._index = 0
        self._in_point = None
        self._out_point = None
        self._fps = max(1.0, float(fps or 24.0))
        self._timer.setInterval(max(1, int(round(1000.0 / self._fps))))
        self._updating = True
        self.slider.setRange(0, max(0, len(self._entries) - 1))
        self.slider.setValue(0)
        self._updating = False
        self._set_controls_enabled(bool(self._entries))
        self._show_index(0)
        self._update_range_label()
        if autoplay and self._entries:
            self.play()

    def set_comments(self, comments: dict) -> None:
        self._comments = comments or {"shot": [], "frames": {}}
        self._refresh_comment_frames()
        self._refresh_comments()
        self._update_timeline()

    def remove_frames(self, frames: list[int]) -> None:
        for frame in frames or []:
            self.remove_frame(frame)

    def remove_frame(self, frame: int) -> None:
        frame = int(frame)
        self._entries = [entry for entry in self._entries if entry[0] != frame]
        self._approved.discard(frame)
        self._cache.pop(frame, None)
        self._updating = True
        self.slider.setRange(0, max(0, len(self._entries) - 1))
        self._updating = False
        if not self._entries:
            self.pause()
            self._set_controls_enabled(False)
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(self.tr("No rendered frames."))
            self.lbl_frame.setText(self.tr("Frame -/-"))
            return
        self._index = min(self._index, len(self._entries) - 1)
        self._show_index(self._index)
        self._update_range_label()

    def set_frames_approved(self, frames: list[int], approved: bool) -> None:
        for frame in frames or []:
            if approved:
                self._approved.add(int(frame))
            else:
                self._approved.discard(int(frame))
        self._update_timeline()

    def current_frame(self) -> int | None:
        if not self._entries:
            return None
        return self._entries[self._index][0]

    def current_path(self) -> Path | None:
        if not self._entries:
            return None
        return self._entries[self._index][1]

    def is_playing(self) -> bool:
        return self._timer.isActive()

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def play(self) -> None:
        if not self._entries:
            return
        self._timer.start()
        self.btn_play.setIcon(self._icon("pause.svg"))
        self.btn_play.setToolTip(self.tr("Pause"))
        self.playback_changed.emit(True)

    def pause(self) -> None:
        self._timer.stop()
        self.btn_play.setIcon(self._icon("play.svg"))
        self.btn_play.setToolTip(self.tr("Play"))
        self.playback_changed.emit(False)

    def toggle_play(self) -> None:
        self.pause() if self._timer.isActive() else self.play()

    def step(self, delta: int) -> None:
        if not self._entries:
            return
        self.pause()
        self._show_index(max(0, min(len(self._entries) - 1, self._index + delta)))

    def _advance(self) -> None:
        if not self._entries:
            self.pause()
            return
        next_index = self._index + 1
        if next_index >= len(self._entries):
            if self.btn_loop.isChecked():
                next_index = 0
            else:
                self._show_index(len(self._entries) - 1)
                self.pause()
                return
        self._show_index(next_index)

    def _on_loop_toggled(self, enabled: bool) -> None:
        self.btn_loop.setToolTip(
            self.tr("Loop enabled") if enabled else self.tr("Loop disabled")
        )

    def _on_slider_changed(self, value: int) -> None:
        if self._updating:
            return
        self.pause()
        self._show_index(int(value))

    def _show_index(self, index: int) -> None:
        if not self._entries:
            return
        self._index = max(0, min(index, len(self._entries) - 1))
        frame, path = self._entries[self._index]
        self._updating = True
        self.slider.setValue(self._index)
        self._updating = False
        if path is not None and Path(path).is_file():
            pixmap = self._pixmap_for(frame, Path(path))
            self.image_label.setPixmap(
                pixmap.scaled(
                    max(320, self.image_label.width()),
                    max(220, self.image_label.height()),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            self.image_label.setToolTip(str(path))
        else:
            self.image_label.setPixmap(
                QIcon(str(_ASSET_DIR / "image-off.svg")).pixmap(96, 96)
            )
            self.image_label.setToolTip(self.tr("Frame {0} is missing.").format(frame))
        self.lbl_frame.setText(
            self.tr("Frame {0} · {1}/{2}").format(
                frame, self._index + 1, len(self._entries)
            )
        )
        self._update_timeline()
        self._refresh_approval()
        self._refresh_badge()
        self._refresh_scope()
        self._refresh_comments()
        self.position_changed.emit(frame)

    def _pixmap_for(self, frame: int, path: Path) -> QPixmap:
        cached = self._cache.get(frame)
        if cached is not None:
            self._cache.move_to_end(frame)
            return cached
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self._cache[frame] = pixmap
            while len(self._cache) > _CACHE_SIZE:
                self._cache.popitem(last=False)
        return pixmap

    # ------------------------------------------------------------------
    # Selection / timeline
    # ------------------------------------------------------------------
    def selected_frames(self) -> list[int]:
        if not self._entries:
            return []
        current = self.current_frame()
        if current is None:
            return []
        if self._in_point is not None and self._out_point is not None:
            first, last = sorted((self._in_point, self._out_point))
            return [
                frame
                for frame, path in self._entries
                if first <= frame <= last and path is not None
            ]
        if self.current_path() is None:
            return []
        return [current]

    def _set_in_point(self) -> None:
        frame = self.current_frame()
        if frame is not None:
            self._in_point = frame
            if self._out_point is not None and self._out_point < frame:
                self._out_point = frame
            self._update_range_label()

    def _set_out_point(self) -> None:
        frame = self.current_frame()
        if frame is not None:
            self._out_point = frame
            if self._in_point is None:
                self._in_point = frame
            elif self._out_point < self._in_point:
                self._in_point, self._out_point = self._out_point, self._in_point
            self._update_range_label()

    def _clear_range(self) -> None:
        self._in_point = None
        self._out_point = None
        self._update_range_label()

    def _update_range_label(self) -> None:
        if self._in_point is not None and self._out_point is not None:
            first, last = sorted((self._in_point, self._out_point))
            count = len(self.selected_frames())
            self.lbl_range.setText(
                self.tr("Selection: frames {0}–{1} ({2} frames)").format(
                    first, last, count
                )
            )
        else:
            self.lbl_range.setText(self.tr("Selection: current frame"))
        self._update_timeline()
        self._refresh_approval()

    def _update_timeline(self) -> None:
        self.timeline.set_state(
            self._entries,
            approved=self._approved,
            comment_frames=self._comment_frames,
            in_point=self._in_point,
            out_point=self._out_point,
            index=self._index,
        )

    def _refresh_approval(self) -> None:
        selected = self.selected_frames()
        self.btn_approve_selection.setEnabled(
            bool(selected) and any(frame not in self._approved for frame in selected)
        )
        self.btn_unapprove_selection.setEnabled(
            bool(selected) and any(frame in self._approved for frame in selected)
        )
        self.btn_delete.setEnabled(
            bool(selected) and any(frame not in self._approved for frame in selected)
        )

    def _on_approve_selection(self) -> None:
        frames = self.selected_frames()
        if frames:
            self.approve_frames_requested.emit(frames, True)

    def _on_unapprove_selection(self) -> None:
        frames = self.selected_frames()
        if frames:
            self.approve_frames_requested.emit(frames, False)

    def _on_delete(self) -> None:
        frames = self.selected_frames()
        if frames:
            self.delete_frames_requested.emit(frames)

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------
    def _refresh_comment_frames(self) -> None:
        self._comment_frames = {
            int(frame)
            for frame in (self._comments.get("frames") or {})
            if str(frame).lstrip("-").isdigit()
        }

    def _refresh_scope(self) -> None:
        current = self.current_frame()
        current_text = self.combo_scope.currentData()
        self.combo_scope.blockSignals(True)
        self.combo_scope.clear()
        self.combo_scope.addItem(self.tr("Shot"), "shot")
        self.combo_scope.addItem(
            self.tr("Frame {0}").format(current if current is not None else "-"),
            "frame",
        )
        index = self.combo_scope.findData(current_text)
        self.combo_scope.setCurrentIndex(max(0, index))
        self.combo_scope.blockSignals(False)

    def _refresh_comments(self, _index=None) -> None:
        if not hasattr(self, "comments_list"):
            return
        self.comments_list.clear()
        scope = self.combo_scope.currentData() or "shot"
        current = self.current_frame()
        if scope == "frame" and current is not None:
            comments = (self._comments.get("frames") or {}).get(str(current), [])
        else:
            comments = self._comments.get("shot", [])
        for comment in comments or []:
            if not isinstance(comment, dict):
                continue
            text = str(comment.get("text") or "")
            author = str(comment.get("author") or self.tr("Unknown"))
            resolved = bool(comment.get("resolved"))
            item = QListWidgetItem(
                f"{'✓ ' if resolved else ''}{author}\n{text}"
            )
            item.setData(Qt.UserRole, str(comment.get("id") or ""))
            self.comments_list.addItem(item)

    def _post_comment(self) -> None:
        text = self.entry_comment.text().strip()
        if not text:
            return
        scope = self.combo_scope.currentData() or "shot"
        frame = self.current_frame() if scope == "frame" else None
        if frame is None and scope == "frame":
            return
        self.comment_posted.emit(scope, int(frame or 0), text)
        self.entry_comment.clear()

    def _selected_comment_id(self) -> str:
        item = self.comments_list.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else ""

    def _resolve_comment(self) -> None:
        comment_id = self._selected_comment_id()
        if comment_id:
            self.comment_resolved.emit(comment_id, True)

    def _delete_comment(self) -> None:
        comment_id = self._selected_comment_id()
        if comment_id:
            self.comment_deleted.emit(comment_id)

    # ------------------------------------------------------------------
    # Frame status / fullscreen
    # ------------------------------------------------------------------
    def _refresh_badge(self) -> None:
        frame = self.current_frame()
        if frame is None:
            self.lbl_badge.hide()
            return
        current_path = self.current_path()
        if current_path is None or not Path(current_path).is_file():
            text, color = self.tr("Missing"), "#EF4444"
        elif frame in self._approved:
            text, color = self.tr("Approved"), "#10B981"
        else:
            text, color = self.tr("Rendered"), "#38BDF8"
        self.lbl_badge.setText(f"● {text}")
        self.lbl_badge.setStyleSheet(
            "background-color: rgba(15, 23, 42, 190); border-radius: 10px; "
            f"padding: 4px 8px; font-size: 11px; font-weight: bold; color: {color};"
        )
        self.lbl_badge.adjustSize()
        self.lbl_badge.move(10, 10)
        self.lbl_badge.show()
        self.lbl_badge.raise_()

    def toggle_fullscreen(self) -> None:
        if self._fullscreen_dialog is None:
            self._enter_fullscreen()
        else:
            self.exit_fullscreen()

    def _enter_fullscreen(self) -> None:
        parent = self.parentWidget()
        self._restore_stack = parent if isinstance(parent, QStackedWidget) else None
        if self._restore_stack is not None:
            self._restore_stack.removeWidget(self)
        else:
            self.setParent(None)
        dialog = QDialog(None)
        dialog.setObjectName("PlayerFullscreen")
        dialog.setWindowTitle(self.tr("Sequence player"))
        dialog.setWindowFlag(Qt.FramelessWindowHint, True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self)
        dialog.finished.connect(lambda _result: self.exit_fullscreen())
        self._fullscreen_dialog = dialog
        self.btn_fullscreen.setIcon(self._icon("minimize.svg"))
        self.btn_fullscreen.setToolTip(self.tr("Exit fullscreen"))
        dialog.showFullScreen()

    def exit_fullscreen(self) -> None:
        dialog = self._fullscreen_dialog
        if dialog is None:
            return
        self._fullscreen_dialog = None
        dialog.layout().removeWidget(self)
        self.setParent(None)
        dialog.close()
        dialog.deleteLater()
        if self._restore_stack is not None:
            self._restore_stack.addWidget(self)
            self._restore_stack.setCurrentWidget(self)
            self._restore_stack = None
        self.btn_fullscreen.setIcon(self._icon("maximize.svg"))
        self.btn_fullscreen.setToolTip(self.tr("Fullscreen"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _icon(name: str) -> QIcon:
        return QIcon(str(_ASSET_DIR / name))

    def _icon_button(self, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("SecondaryButton")
        button.setIcon(self._icon(icon_name))
        button.setIconSize(button.iconSize().expandedTo(button.iconSize()))
        button.setToolTip(self.tr(tooltip))
        button.setFixedWidth(32)
        return button

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.btn_step_back,
            self.btn_play,
            self.btn_step_forward,
            self.btn_loop,
            self.btn_fullscreen,
            self.btn_in,
            self.btn_out,
            self.btn_clear_range,
            self.btn_approve_selection,
            self.btn_unapprove_selection,
            self.btn_delete,
            self.slider,
        ):
            widget.setEnabled(enabled)
