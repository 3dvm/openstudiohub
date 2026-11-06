# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/video.py
# Architectural role: Render infrastructure / ffmpeg review videos
# =========================================================================================

"""Create review MP4s from rendered frames with ffmpeg.

The naming follows Blender Studio Tools: the review copy lives in
``shared/editorial/footage/pro/<seq>/<shot>/<shot>-<task>/`` and is named
``<shot>-<task>-v###.mp4``. A render-review copy can also be written next to
the frames as ``<shot>-<first>-<last>.mp4``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class RenderVideoError(RuntimeError):
    """Raised when ffmpeg is missing or a video cannot be created."""


class RenderVideoService:
    def __init__(self, ffmpeg_path: str = "") -> None:
        self.ffmpeg_path = ffmpeg_path or (shutil.which("ffmpeg") or "")

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg_path)

    def version(self) -> str:
        if not self.available:
            return ""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return ""
        first = (result.stdout or "").splitlines()
        return first[0].strip() if first else ""

    def create_video(
        self,
        frames_dir: Path | str,
        first_frame: int,
        last_frame: int,
        fps: float,
        output_path: Path | str,
        *,
        crf: int = 18,
        preset: str = "medium",
        video_filter: str = "",
    ) -> Path:
        if not self.available:
            raise RenderVideoError(
                "ffmpeg is not installed; install it to create review videos."
            )
        source = Path(frames_dir)
        destination = Path(output_path)
        if not source.is_dir():
            raise RenderVideoError(f"Frames folder not found: {source}")
        first = int(first_frame)
        last = int(last_frame)
        if last < first:
            raise RenderVideoError("The last frame is before the first frame.")
        missing = [
            frame
            for frame in range(first, last + 1)
            if not (source / f"frame_{frame:04d}.png").is_file()
        ]
        if missing:
            raise RenderVideoError(
                f"{len(missing)} frame(s) are missing; cannot create the video."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-start_number",
            str(first),
            "-framerate",
            f"{float(fps):.6g}",
            "-i",
            str(source / "frame_%04d.png"),
            "-frames:v",
            str(last - first + 1),
        ]
        if video_filter:
            command.extend(["-vf", str(video_filter)])
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(int(crf)),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(destination),
            ]
        )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RenderVideoError(f"ffmpeg failed: {error}") from error
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            raise RenderVideoError(
                "ffmpeg failed: " + (" | ".join(detail[-5:]) or str(result.returncode))
            )
        return destination

    def copy_for_render_review(self, source: Path | str, destination: Path | str) -> Path:
        source_path = Path(source)
        destination_path = Path(destination)
        if not source_path.is_file():
            raise RenderVideoError(f"Video not found: {source_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        return destination_path

    @staticmethod
    def write_review_metadata(
        review_folder: Path | str,
        video_name: str,
        source_frames_dir: Path | str,
    ) -> Path:
        folder = Path(review_folder)
        folder.mkdir(parents=True, exist_ok=True)
        metadata_path = folder / "metadata.json"
        data = {}
        if metadata_path.exists():
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        if not isinstance(data, dict):
            data = {}
        data[video_name] = str(Path(source_frames_dir))
        metadata_path.write_text(
            json.dumps(data, indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return metadata_path
