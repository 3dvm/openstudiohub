"""Unit tests for Blender Studio render paths and review video naming."""

import json
import subprocess
from dataclasses import replace
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


def test_preview_video_uses_fast_half_resolution_encode(tmp_path):
    root = _project(tmp_path)
    service = RenderService()
    shot = _shot()
    calls = []

    class FakeVideo:
        def create_video(self, source, first, last, fps, output, **kwargs):
            calls.append((source, first, last, fps, output, kwargs))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"x")
            return output

    service.video = FakeVideo()

    path = service.create_preview_video(root, shot, service.load_settings(root))

    assert path.parent.name == ".previews"
    assert calls and calls[0][5]["crf"] == 28
    assert calls[0][5]["video_filter"] == "scale=iw/2:-2"


def test_frame_delete_moves_to_trash_and_respects_approval(tmp_path):
    root = _project(tmp_path)
    service = RenderService()
    shot = _shot()
    output = service.shot_output_dir(root, shot)
    output.mkdir(parents=True)
    frame = output / "frame_0101.png"
    frame.write_bytes(b"x")
    service.approve_frame(root, shot, 101, True)

    ok, message = service.delete_frame(root, shot, 101)

    assert ok is False
    assert "approved" in message.lower()
    service.approve_frame(root, shot, 101, False)

    ok, message = service.delete_frame(root, shot, 101)

    assert ok is True
    assert not frame.exists()
    assert (output / ".frame_trash" / "frame_0101.png").is_file()


def test_frame_ranges_can_be_approved_and_deleted_in_one_operation(tmp_path):
    root = _project(tmp_path)
    service = RenderService()
    shot = _shot()
    output = service.shot_output_dir(root, shot)
    output.mkdir(parents=True)
    for frame in (101, 102, 103):
        (output / f"frame_{frame:04d}.png").write_bytes(b"x")

    ok, _message = service.approve_frames(root, shot, [101, 102], True)
    assert ok is True
    approvals = service.frame_state_store(root, shot).approved_frames()
    assert approvals == {101, 102}

    ok, _message, deleted = service.delete_frames(root, shot, [101, 102, 103])
    assert ok is True
    assert deleted == (103,)
    assert not (output / "frame_0103.png").exists()
    assert (output / "frame_0101.png").is_file()


def test_frame_paths_and_proxies_follow_the_final_format(tmp_path):
    root = _project(tmp_path)
    service = RenderService()
    shot = _shot()
    shot = shot.with_quality(replace(shot.quality, file_format="OPEN_EXR"))

    final = service.frame_path(root, shot, 101)
    proxy = service.proxy_frame_path(root, shot, 101)

    assert final.name == "frame_0101.exr"
    assert proxy.name == "frame_0101.png"
    assert service.display_frame_path(root, shot, 101) == final
    proxy.parent.mkdir(parents=True)
    proxy.write_bytes(b"x")
    assert service.display_frame_path(root, shot, 101) == proxy


def test_video_command_uses_the_requested_frame_extension(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_0101.exr").write_bytes(b"x")
    service = RenderVideoService("ffmpeg")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("src.infrastructure.render.video.subprocess.run", fake_run)

    service.create_video(frames, 101, 101, 24.0, tmp_path / "review.mp4", extension="exr")

    assert str(frames / "frame_%04d.exr") in captured["command"]
