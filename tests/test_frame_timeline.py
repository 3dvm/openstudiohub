"""Unit tests for the visual frame timeline."""

from PySide6.QtGui import QColor

from src.interfaces.qt.components.frame_timeline import FrameTimeline


def _entries(tmp_path, count=10, start=101):
    entries = []
    for index in range(count):
        frame = start + index
        path = tmp_path / f"frame_{frame:04d}.png"
        path.write_bytes(b"x")
        entries.append((frame, path))
    return entries


def test_timeline_paints_the_selection_band_and_boundaries(qapp, tmp_path):
    timeline = FrameTimeline()
    timeline.resize(200, 42)
    timeline.set_state(
        _entries(tmp_path),
        approved=set(),
        in_point=103,
        out_point=106,
        index=104,
    )

    image = timeline.grab().toImage()

    assert image.pixelColor(80, 36) == QColor("#F97316")
    assert image.pixelColor(10, 36) == QColor("#0F172A")
    assert image.pixelColor(40, 20) == QColor("#F97316")
    assert image.pixelColor(120, 20) == QColor("#F97316")
    timeline.deleteLater()


def test_timeline_paints_a_single_in_marker(qapp, tmp_path):
    timeline = FrameTimeline()
    timeline.resize(200, 42)
    timeline.set_state(
        _entries(tmp_path),
        approved=set(),
        in_point=103,
        out_point=None,
        index=104,
    )

    image = timeline.grab().toImage()

    assert image.pixelColor(50, 20) == QColor("#F97316")
    assert image.pixelColor(10, 20) != QColor("#F97316")
    timeline.deleteLater()
