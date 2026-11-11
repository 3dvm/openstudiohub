# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/frame_timeline.py
# Architectural role: UI component / rendered frame timeline
# =========================================================================================

"""Timeline that paints approved, pending and missing frames."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget


class FrameTimeline(QWidget):
    seek_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FrameTimeline")
        self.setMinimumHeight(42)
        self.setMouseTracking(True)
        self._entries: list[tuple[int, Path | None]] = []
        self._approved: set[int] = set()
        self._comment_frames: set[int] = set()
        self._in_point: int | None = None
        self._out_point: int | None = None
        self._index = 0

    def set_state(
        self,
        entries: list[tuple[int, Path | None]],
        *,
        approved: set[int],
        comment_frames: set[int] | None = None,
        in_point: int | None,
        out_point: int | None,
        index: int,
    ) -> None:
        self._entries = list(entries)
        self._approved = set(approved)
        self._comment_frames = set(comment_frames or ())
        self._in_point = in_point
        self._out_point = out_point
        self._index = max(0, min(int(index), max(0, len(self._entries) - 1)))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = max(1, self.width())
        height = max(1, self.height())
        painter.fillRect(self.rect(), QColor("#0F172A"))
        if not self._entries:
            painter.end()
            return

        count = len(self._entries)
        frame_width = max(1.0, width / max(1, count))
        bar_top = 6.0
        band_height = 4.0
        band_top = height - 8.0
        bar_height = max(2.0, band_top - 3.0 - bar_top)
        positions = {
            frame: position for position, (frame, _path) in enumerate(self._entries)
        }
        in_index = positions.get(self._in_point)
        out_index = positions.get(self._out_point)

        if in_index is not None and out_index is not None:
            low_index, high_index = sorted((in_index, out_index))
            start = low_index * frame_width
            end = (high_index + 1) * frame_width
        else:
            start = self._index * frame_width
            end = (self._index + 1) * frame_width
        if in_index is not None and out_index is not None:
            painter.fillRect(
                QRectF(start, 0, max(2.0, end - start), height),
                QColor(249, 115, 22, 34),
            )
        painter.fillRect(
            QRectF(start, band_top, max(2.0, end - start), band_height),
            QColor("#F97316"),
        )

        for position, (frame, path) in enumerate(self._entries):
            x = position * frame_width
            if path is None:
                color = QColor("#EF4444")
            elif frame in self._approved:
                color = QColor("#10B981")
            else:
                color = QColor("#38BDF8")
            painter.fillRect(
                QRectF(x, bar_top, max(1.0, frame_width), bar_height), color
            )
            if frame in self._comment_frames:
                painter.setBrush(QColor("#F59E0B"))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(
                    QRectF(x + frame_width / 2 - 2, 1, 4, 4)
                )

        marker_color = QColor("#F97316")
        if in_index is not None:
            x = (
                min(in_index, out_index) * frame_width
                if out_index is not None
                else in_index * frame_width + frame_width / 2
            )
            painter.fillRect(QRectF(x - 1, 2, 2, height - 4), marker_color)
            painter.fillRect(QRectF(x - 4, 1, 8, 3), marker_color)
        if out_index is not None:
            x = (
                (max(in_index, out_index) + 1) * frame_width
                if in_index is not None
                else out_index * frame_width + frame_width / 2
            )
            painter.fillRect(QRectF(x - 1, 2, 2, height - 4), marker_color)
            painter.fillRect(QRectF(x - 4, 1, 8, 3), marker_color)

        if self._index < count:
            x = self._index * frame_width + frame_width / 2
            painter.setPen(QPen(QColor("#F8FAFC"), 2))
            painter.drawLine(x, 0, x, height)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._seek(event.position().x())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.buttons() & Qt.LeftButton:
            self._seek(event.position().x())
        else:
            index = self._index_at(event.position().x())
            if 0 <= index < len(self._entries):
                frame, path = self._entries[index]
                state = "missing" if path is None else (
                    "approved" if frame in self._approved else "rendered"
                )
                selected = False
                if self._in_point is not None and self._out_point is not None:
                    low, high = sorted((self._in_point, self._out_point))
                    selected = low <= frame <= high
                elif self._in_point is not None:
                    selected = frame == self._in_point
                elif self._out_point is not None:
                    selected = frame == self._out_point
                if selected:
                    state += " · selected"
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"Frame {frame} · {state}",
                    self,
                )

    def _seek(self, x: float) -> None:
        index = self._index_at(x)
        if 0 <= index < len(self._entries):
            self.seek_requested.emit(index)

    def _index_at(self, x: float) -> int:
        if not self._entries:
            return -1
        ratio = max(0.0, min(1.0, float(x) / max(1, self.width())))
        return min(len(self._entries) - 1, int(ratio * len(self._entries)))
