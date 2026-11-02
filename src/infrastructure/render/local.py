# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/local.py
# Architectural role: Render infrastructure / local headless Blender
# =========================================================================================

"""Render frames with the project's isolated Blender on this workstation.

The local backend is used for previews and for small projects that do not need
cloud GPUs. It runs Blender headlessly, applies the requested quality in memory,
and never saves the ``.blend``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from src.domain.render.models import RenderQuality

ProgressCallback = Callable[[int, int, float], None]

_RENDER_SCRIPT = r"""
import bpy
import json
import os
import sys
import time

config_path = sys.argv[-1]
with open(config_path, "r", encoding="utf-8") as handle:
    config = json.load(handle)

scene = bpy.context.scene
quality = config["quality"]
scene.render.engine = quality["engine"]
scene.render.resolution_x = int(quality["resolution_x"])
scene.render.resolution_y = int(quality["resolution_y"])
scene.render.resolution_percentage = int(quality["resolution_percentage"])
scene.render.image_settings.file_format = config.get("file_format", "PNG")
scene.render.use_compositing = bool(config.get("use_compositing", True))

if quality["engine"] == "CYCLES":
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = config.get("device_type", "CUDA")
    prefs.get_devices()
    for device in prefs.devices:
        device.use = device.type != "CPU"
    scene.cycles.device = "GPU"
    scene.cycles.samples = int(quality["samples"])
    scene.cycles.use_denoising = bool(quality.get("denoise", True))
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    scene.render.use_persistent_data = True
    print("OSDEVICES::" + json.dumps([(d.name, d.type, d.use) for d in prefs.devices]))
elif quality["engine"].upper().startswith("BLENDER_EEVEE"):
    eevee = getattr(scene, "eevee", None)
    if eevee is not None:
        eevee.taa_render_samples = int(quality["samples"])

output_dir = config["output_dir"]
os.makedirs(output_dir, exist_ok=True)
for frame in config["frames"]:
    frame = int(frame)
    scene.frame_set(frame)
    scene.render.filepath = os.path.join(output_dir, "frame_%04d" % frame)
    started = time.monotonic()
    bpy.ops.render.render(write_still=True)
    elapsed = time.monotonic() - started
    print("OSFRAME::" + json.dumps({"frame": frame, "seconds": round(elapsed, 3)}))
"""


class LocalRenderError(RuntimeError):
    """Raised when a local headless render fails."""


@dataclass(frozen=True)
class LocalRenderReport:
    ok: bool
    message: str
    output_dir: Path
    frames_expected: int
    frames_rendered: int
    seconds: tuple[float, ...]
    missing: tuple[int, ...]


class LocalRenderRunner:
    def __init__(self, blender_path: Path | str, *, timeout: float = 86400.0) -> None:
        self.blender_path = Path(blender_path)
        self.timeout = float(timeout)
        self._cancel = threading.Event()
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

    def render(
        self,
        blend_path: Path | str,
        quality: RenderQuality,
        frames: Iterable[int],
        output_dir: Path | str,
        *,
        use_compositing: bool = True,
        file_format: str = "PNG",
        progress: ProgressCallback | None = None,
    ) -> LocalRenderReport:
        if not self.blender_path.is_file():
            raise LocalRenderError(f"Blender executable not found: {self.blender_path}")
        blend = Path(blend_path)
        if not blend.is_file():
            raise LocalRenderError(f"Scene not found: {blend}")
        frame_list = tuple(sorted({int(frame) for frame in frames}))
        if not frame_list:
            return LocalRenderReport(True, "No frames to render.", Path(output_dir), 0, 0, (), ())
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        self._cancel.clear()

        with tempfile.TemporaryDirectory(prefix="openstudio_local_render_") as temp_dir:
            temp = Path(temp_dir)
            script = temp / "render_frames.py"
            script.write_text(_RENDER_SCRIPT, encoding="utf-8")
            config = temp / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "quality": {
                            "engine": quality.engine,
                            "resolution_x": quality.resolution_x,
                            "resolution_y": quality.resolution_y,
                            "resolution_percentage": quality.resolution_percentage,
                            "samples": quality.samples,
                            "denoise": quality.denoise,
                        },
                        "frames": list(frame_list),
                        "output_dir": str(destination),
                        "use_compositing": use_compositing,
                        "file_format": file_format,
                    }
                ),
                encoding="utf-8",
            )
            config_dir = temp / "config"
            scripts_dir = temp / "scripts"
            config_dir.mkdir()
            scripts_dir.mkdir()
            env = os.environ.copy()
            env["BLENDER_USER_CONFIG"] = str(config_dir)
            env["BLENDER_USER_SCRIPTS"] = str(scripts_dir)
            env.setdefault("LC_ALL", "C")
            env.setdefault("LANG", "C")

            command = [
                str(self.blender_path),
                "-b",
                "--factory-startup",
                str(blend),
                "--python",
                str(script),
                "--",
                str(config),
            ]
            if quality.is_eevee and shutil.which("xvfb-run"):
                command = ["xvfb-run", "-a", *command]

            started = time.monotonic()
            deadline = started + self.timeout
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            with self._lock:
                self._process = process
            done = 0
            seconds: list[float] = []
            try:
                for line in process.stdout or ():
                    if self._cancel.is_set() or time.monotonic() > deadline:
                        process.terminate()
                        break
                    if "OSFRAME::" in line:
                        try:
                            payload = json.loads(line.split("OSFRAME::", 1)[1])
                        except ValueError:
                            payload = {}
                        done += 1
                        elapsed = float(payload.get("seconds") or 0.0)
                        seconds.append(elapsed)
                        if progress is not None:
                            progress(done, len(frame_list), elapsed)
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                raise LocalRenderError("Local render timed out.")
            finally:
                with self._lock:
                    self._process = None
                if process.poll() is None:
                    process.kill()

        missing = tuple(
            frame
            for frame in frame_list
            if not (destination / f"frame_{frame:04d}.png").is_file()
        )
        ok = process.returncode == 0 and not missing and not self._cancel.is_set()
        message = (
            f"Rendered {len(frame_list) - len(missing)}/{len(frame_list)} frame(s) locally."
            if ok
            else f"Local render finished with {len(missing)} missing frame(s)."
        )
        return LocalRenderReport(
            ok=ok,
            message=message,
            output_dir=destination,
            frames_expected=len(frame_list),
            frames_rendered=len(frame_list) - len(missing),
            seconds=tuple(seconds),
            missing=missing,
        )
