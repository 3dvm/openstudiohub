"""Unit tests for review video helpers."""

from pathlib import Path

from src.infrastructure.render.video import RenderVideoService


def test_missing_frame_placeholder_matches_render_aspect(qapp, tmp_path):
    path = tmp_path / "frame_0042.png"

    RenderVideoService._write_missing_frame(
        path,
        42,
        width=1080,
        height=1920,
        icon_path=Path("assets/icons/image-off.svg"),
    )

    from PySide6.QtGui import QImage

    image = QImage(str(path))
    assert not image.isNull()
    assert image.width() == 1080
    assert image.height() == 1920
