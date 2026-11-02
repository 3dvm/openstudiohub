"""Tests for the read-only render progress widget."""

import json
from pathlib import Path

from PySide6.QtGui import QImage

import src.interfaces.qt.views.pm_view  # noqa: F401 - app import order
from src.interfaces.qt.widgets.render_progress_widget import RenderProgressWidget


def test_progress_widget_reads_shared_status(qapp, tmp_path):
    project = tmp_path / "p0005"
    status_dir = project / "03_render"
    status_dir.mkdir(parents=True)
    preview = tmp_path / "preview.png"
    image = QImage(20, 10, QImage.Format_RGB32)
    image.fill(0)
    image.save(str(preview))
    (status_dir / ".render_status.json").write_text(
        json.dumps(
            {
                "status": "rendering",
                "message": "Rendering sh010",
                "frames_done": 5,
                "frames_expected": 10,
                "nodes": 2,
                "cost": 0.12,
                "backend": "vast",
                "preview": str(preview),
                "video": str(tmp_path / "video.mp4"),
            }
        ),
        encoding="utf-8",
    )

    widget = RenderProgressWidget(None, lambda name: project)
    widget.set_projects([{"name": "p0005"}])
    widget._refresh_status()

    assert widget.progress.value() == 5
    assert widget.progress.maximum() == 10
    assert widget.lbl_status.text() == "Rendering"
    assert "5/10" in widget.lbl_detail.text()
    assert str(tmp_path / "video.mp4") in widget.lbl_video.text()
    widget.close()
