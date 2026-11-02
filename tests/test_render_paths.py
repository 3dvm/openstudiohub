"""Unit tests for Blender Studio render paths and review video naming."""

import json
import subprocess
from pathlib import Path

from src.application.services.render_service import RenderService
from src.domain.render.models import RenderQuality, RenderShot
from src.infrastructure.render.video import RenderVideoService


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "p0005"
    pipeline = root / "05_config_estudio"
    pipeline.mkdir(parents=True)
    (pipeline / "project_init.json").write_text(
        json.dumps(
            {
                "project_name": "p0005",
                "blender_version": "5.2.3",
                "topography_signature": {
                    "vfs_svn": "02_archivos_de_produccion",
                    "vfs_shared": "04_datos_compartidos",
                    "vfs_local": "06_conf_LOCAL",
                    "vfs_pipeline": "05_config_estudio",
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def _shot() -> RenderShot:
    return RenderShot(
        name="sh010",
        blend_path=Path("/project/sh010.blend"),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=256),
        frame_start=101,
        frame_end=196,
        object_count=639,
        mesh_count=625,
        has_camera=True,
    )


def test_blender_studio_paths(tmp_path):
    root = _project(tmp_path)
    service = RenderService()
    shot = _shot()

    assert (
        service.shot_output_dir(root, shot, "render")
        == root / "03_render" / "shots" / "sq010" / "sh010.render"
    )
    assert (
        service.kitsu_review_dir(root, shot, "render")
        == root
        / "04_datos_compartidos"
        / "editorial"
        / "footage"
        / "pro"
        / "sq010"
        / "sh010"
        / "sh010-render"
    )


def test_review_video_version_increments(tmp_path):
    root = _project(tmp_path)
    service = RenderService()
    shot = _shot()
    review = service.kitsu_review_dir(root, shot, "render")
    review.mkdir(parents=True)
    (review / "sh010-render-v001.mp4").write_bytes(b"x")
    (review / "sh010-render-v002.mp4").write_bytes(b"x")

    video = service.kitsu_review_video_path(root, shot, "render")

    assert video.name == "sh010-render-v003.mp4"


def test_video_command_and_metadata(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_0101.png").write_bytes(b"x")
    (frames / "frame_0102.png").write_bytes(b"x")
    service = RenderVideoService("ffmpeg")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("src.infrastructure.render.video.subprocess.run", fake_run)
    output = tmp_path / "review.mp4"

    result = service.create_video(frames, 101, 102, 24.0, output)

    assert result == output
    command = captured["command"]
    assert "-start_number" in command and "101" in command
    assert "libx264" in command
    assert str(frames / "frame_%04d.png") in command

    metadata = service.write_review_metadata(tmp_path / "review", output.name, frames)
    data = json.loads(metadata.read_text(encoding="utf-8"))
    assert data[output.name] == str(frames)
