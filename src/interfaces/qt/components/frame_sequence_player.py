# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/frame_sequence_player.py
# Architectural role: UI component / lightweight PNG sequence player
# =========================================================================================

"""Lightweight player for rendered PNG sequences.

The render panel needs frame-accurate playback without an external dependency.
Frames are loaded on demand and kept in a small LRU cache so long 1080p
sequences do not exhaust memory.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

_CACHE_SIZE = 12


class FrameSequencePlayer(QWidget):
    """Play a list of ``(frame_number, path_or_none)`` entries at a fixed fps."""

    delete_requested = Signal(int)
    approve_requested = Signal(int, bool)
    position_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[tuple[int, Path | None]] = []
        self._approved: set[int] = set()
        self._cache: OrderedDict[int, QPixmap] = OrderedDict()
        self._fps = 24.0
        self._index = 0
        self._updating = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.image_label = QLabel(self.tr("No rendered frames."))
        self.image_label.setObjectName("MutedLabel")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(220)
        self.image_label.setWordWrap(True)
        layout.addWidget(self.image_label, 1)

        controls = QHBoxLayout()
        self.btn_play = QPushButton(self.tr("▶ Play"))
        self.btn_play.setObjectName("SecondaryButton")
        self.btn_play.clicked.connect(self.toggle_play)
        controls.addWidget(self.btn_play)

        self.lbl_frame = QLabel(self.tr("Frame -/-"))
        self.lbl_frame.setObjectName("InfoLabel")
        controls.addWidget(self.lbl_frame)
        controls.addStretch()

        self.chk_approve = QCheckBox(self.tr("Approved"))
        self.chk_approve.toggled.connect(self._on_approve_toggled)
        controls.addWidget(self.chk_approve)

        self.btn_delete = QPushButton(self.tr("Delete frame"))
        self.btn_delete.setObjectName("DangerButton")
        self.btn_delete.clicked.connect(self._on_delete)
        controls.addWidget(self.btn_delete)
        layout.addLayout(controls)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.slider)
        self._set_controls_enabled(False)

    # ------------------------------------------------------------------
    # Sequence
    # ------------------------------------------------------------------
    def set_sequence(
        self,
        entries: list[tuple[int, Path | None]],
        *,
        fps: float,
        approved: set[int] | None = None,
        autoplay: bool = True,
    ) -> None:
        self.pause()
        self._entries = list(entries)
        self._approved = set(approved or ())
        self._cache.clear()
        self._index = 0
        self._fps = max(1.0, float(fps or 24.0))
        self._timer.setInterval(max(1, int(round(1000.0 / self._fps))))
        self._updating = True
        self.slider.setRange(0, max(0, len(self._entries) - 1))
        self.slider.setValue(0)
        self._updating = False
        self._set_controls_enabled(bool(self._entries))
        self._show_index(0)
        if autoplay and self._entries:
            self.play()

    def remove_frame(self, frame: int) -> None:
        """Mark a frame as deleted by dropping it from the player timeline."""
        frame = int(frame)
        remaining = [entry for entry in self._entries if entry[0] != frame]
        had_entries = bool(self._entries)
        self._entries = remaining
        self._approved.discard(frame)
        self._cache.pop(frame, None)
        self._updating = True
        self.slider.setRange(0, max(0, len(self._entries) - 1))
        self._updating = False
        if not remaining:
            self.pause()
            self._set_controls_enabled(False)
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(self.tr("No rendered frames."))
            self.lbl_frame.setText(self.tr("Frame -/-"))
            return
        self._index = min(self._index, len(self._entries) - 1)
        if had_entries and not self._timer.isActive():
            self.pause()
        self._show_index(self._index)
        self.position_changed.emit(self.current_frame() or 0)

    def set_frame_approved(self, frame: int, approved: bool) -> None:
        frame = int(frame)
        if approved:
            self._approved.add(frame)
        else:
            self._approved.discard(frame)
        if self.current_frame() == frame:
            self._refresh_approval()

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
        self.btn_play.setText(self.tr("⏸ Pause"))

    def pause(self) -> None:
        self._timer.stop()
        self.btn_play.setText(self.tr("▶ Play"))

    def toggle_play(self) -> None:
        if self._timer.isActive():
            self.pause()
        else:
            self.play()

    def _advance(self) -> None:
        if not self._entries:
            self.pause()
            return
        self._show_index((self._index + 1) % len(self._entries))

    def _on_slider_changed(self, value: int) -> None:
        if self._updating:
            return
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
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(self.tr("Frame {0} is missing.").format(frame))
        self.lbl_frame.setText(
            self.tr("Frame {0} · {1}/{2}").format(frame, self._index + 1, len(self._entries))
        )
        self._refresh_approval()
        self.position_changed.emit(frame)

    def _refresh_approval(self) -> None:
        frame = self.current_frame()
        has_frame = frame is not None and self.current_path() is not None
        self._updating = True
        self.chk_approve.setChecked(bool(frame is not None and frame in self._approved))
        self._updating = False
        self.chk_approve.setEnabled(has_frame)
        self.btn_delete.setEnabled(has_frame and not self.chk_approve.isChecked())

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

    def _on_approve_toggled(self, checked: bool) -> None:
        if self._updating:
            return
        frame = self.current_frame()
        if frame is None:
            return
        self.approve_requested.emit(frame, bool(checked))

    def _on_delete(self) -> None:
        frame = self.current_frame()
        if frame is not None:
            self.delete_requested.emit(frame)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.btn_play.setEnabled(enabled)
        self.slider.setEnabled(enabled)
        self.chk_approve.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)
