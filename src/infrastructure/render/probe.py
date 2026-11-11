# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/probe.py
# Architectural role: Render infrastructure / Blender scene inspection
# =========================================================================================

"""Read render and compositing settings from a ``.blend`` without the GUI.

The probe runs the project's isolated Blender with ``--factory-startup`` and a
temporary configuration directory, so it never mutates the artist's sandbox or
the scene file. The result feeds the capacity calculator, the render setup
audit and the preview workflow.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.domain.render.models import FileOutputInfo, RenderSetup, ViewLayerInfo

_PROBE_MARKER = "OSJSON::"

_PROBE_SCRIPT = r"""
import bpy
import json

scene = bpy.context.scene
render = scene.render
engine = str(render.engine or "")
if engine == "CYCLES":
    samples = int(getattr(scene.cycles, "samples", 128) or 128)
    denoise = bool(getattr(scene.cycles, "use_denoising", False))
elif engine.upper().startswith("BLENDER_EEVEE"):
    eevee = getattr(scene, "eevee", None)
    samples = int(getattr(eevee, "taa_render_samples", 64) or 64) if eevee else 64
    denoise = False
else:
    samples = int(getattr(scene.cycles, "samples", 128) or 128) if hasattr(scene, "cycles") else 128
    denoise = False

geometry_nodes = 0
for obj in bpy.data.objects:
    for modifier in getattr(obj, "modifiers", ()):
        if getattr(modifier, "type", "") == "NODES":
            geometry_nodes += 1

group = getattr(scene, "compositing_node_group", None)
if group is None:
    group = getattr(scene, "node_tree", None)
nodes = list(getattr(group, "nodes", ())) if group is not None else []
links = list(getattr(group, "links", ())) if group is not None else []

output_types = {"GROUP_OUTPUT", "COMPOSITE"}
layer_nodes = {}
for node in nodes:
    if getattr(node, "type", "") == "R_LAYERS":
        layer_nodes[getattr(node, "layer", "")] = node

def reaches_output(node, seen):
    if node is None:
        return False
    if getattr(node, "type", "") in output_types:
        return True
    for output in getattr(node, "outputs", ()):
        for link in getattr(output, "links", ()):
            target = getattr(link, "to_node", None)
            if target is None or target.name in seen:
                continue
            if reaches_output(target, seen | {target.name}):
                return True
    return False

view_layers = []
for view_layer in scene.view_layers:
    node = layer_nodes.get(view_layer.name)
    view_layers.append({
        "name": view_layer.name,
        "enabled": bool(getattr(view_layer, "use", True)),
        "render_layers_node": node.name if node is not None else "",
        "connected_to_output": reaches_output(node, set()) if node is not None else False,
        "samples": int(getattr(view_layer, "samples", 0) or 0),
    })

file_outputs = []
for node in nodes:
    if getattr(node, "type", "") != "OUTPUT_FILE":
        continue
    output_format = getattr(getattr(node, "format", None), "file_format", "")
    file_outputs.append({
        "name": node.name,
        "base_path": str(getattr(node, "base_path", "") or ""),
        "file_format": str(output_format or ""),
        "layer": "",
    })

data = {
    "engine": engine,
    "resolution_x": int(render.resolution_x),
    "resolution_y": int(render.resolution_y),
    "resolution_percentage": int(render.resolution_percentage),
    "samples": samples,
    "denoise": denoise,
    "frame_start": int(scene.frame_start),
    "frame_end": int(scene.frame_end),
    "frame_step": int(scene.frame_step),
    "object_count": len(bpy.data.objects),
    "mesh_count": len(bpy.data.meshes),
    "library_count": len(bpy.data.libraries),
    "geometry_node_objects": geometry_nodes,
    "has_camera": scene.camera is not None,
    "camera": scene.camera.name if scene.camera is not None else "",
    "libraries": sorted({lib.filepath for lib in bpy.data.libraries if lib.filepath}),
    "images": sorted({
        image.filepath
        for image in bpy.data.images
        if image.filepath and not image.packed_file
    }),
    "output_path": str(render.filepath or ""),
    "file_format": str(render.image_settings.file_format or ""),
    "use_nodes": bool(getattr(scene, "use_nodes", False)),
    "compositing_enabled": bool(getattr(render, "use_compositing", False)),
    "compositor_name": str(getattr(group, "name", "") or ""),
    "view_layers": view_layers,
    "file_outputs": file_outputs,
    "color_mode": str(render.image_settings.color_mode or ""),
    "color_depth": str(render.image_settings.color_depth or ""),
    "view_transform": str(scene.view_settings.view_transform or ""),
    "look": str(scene.view_settings.look or ""),
    "fps": float(render.fps) / float(render.fps_base or 1.0),
    "film_transparent": bool(render.film_transparent),
    "motion_blur": bool(render.use_motion_blur),
    "use_sequencer": bool(render.use_sequencer),
}
print("OSJSON::" + json.dumps(data))
"""


class RenderProbeError(RuntimeError):
    """Raised when Blender cannot inspect a scene."""


@dataclass(frozen=True)
class RenderProbeResult:
    engine: str
    resolution_x: int
    resolution_y: int
    resolution_percentage: int
    samples: int
    denoise: bool
    frame_start: int
    frame_end: int
    frame_step: int
    object_count: int
    mesh_count: int
    library_count: int
    geometry_node_objects: int
    has_camera: bool
    libraries: tuple[str, ...]
    images: tuple[str, ...]
    output_path: str
    file_format: str
    setup: RenderSetup

    def to_dict(self) -> dict:
        """Serialize the probe result so the scan cache can reuse it."""
        setup = self.setup
        return {
            "engine": self.engine,
            "resolution_x": self.resolution_x,
            "resolution_y": self.resolution_y,
            "resolution_percentage": self.resolution_percentage,
            "samples": self.samples,
            "denoise": self.denoise,
            "frame_start": self.frame_start,
            "frame_end": self.frame_end,
            "frame_step": self.frame_step,
            "object_count": self.object_count,
            "mesh_count": self.mesh_count,
            "library_count": self.library_count,
            "geometry_node_objects": self.geometry_node_objects,
            "has_camera": self.has_camera,
            "libraries": list(self.libraries),
            "images": list(self.images),
            "output_path": self.output_path,
            "file_format": self.file_format,
            "use_nodes": setup.use_nodes,
            "compositing_enabled": setup.compositing_enabled,
            "compositor_name": setup.compositor_name,
            "view_layers": [
                {
                    "name": layer.name,
                    "enabled": layer.enabled,
                    "render_layers_node": layer.render_layers_node,
                    "connected_to_output": layer.connected_to_output,
                    "samples": layer.samples,
                }
                for layer in setup.view_layers
            ],
            "file_outputs": [
                {
                    "name": output.name,
                    "base_path": output.base_path,
                    "file_format": output.file_format,
                    "layer": output.layer,
                }
                for output in setup.file_outputs
            ],
            "color_mode": setup.color_mode,
            "color_depth": setup.color_depth,
            "view_transform": setup.view_transform,
            "look": setup.look,
            "camera": setup.camera,
            "fps": setup.fps,
            "film_transparent": setup.film_transparent,
            "motion_blur": setup.motion_blur,
            "use_sequencer": setup.use_sequencer,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RenderProbeResult":
        view_layers = tuple(
            ViewLayerInfo(
                name=str(item.get("name") or ""),
                enabled=bool(item.get("enabled", True)),
                render_layers_node=str(item.get("render_layers_node") or ""),
                connected_to_output=bool(item.get("connected_to_output")),
                samples=int(item.get("samples") or 0),
            )
            for item in data.get("view_layers") or ()
            if isinstance(item, dict)
        )
        file_outputs = tuple(
            FileOutputInfo(
                name=str(item.get("name") or ""),
                base_path=str(item.get("base_path") or ""),
                file_format=str(item.get("file_format") or ""),
                layer=str(item.get("layer") or ""),
            )
            for item in data.get("file_outputs") or ()
            if isinstance(item, dict)
        )
        setup = RenderSetup(
            use_nodes=bool(data.get("use_nodes")),
            compositing_enabled=bool(data.get("compositing_enabled")),
            compositor_name=str(data.get("compositor_name") or ""),
            view_layers=view_layers,
            file_outputs=file_outputs,
            output_format=str(data.get("file_format") or ""),
            color_mode=str(data.get("color_mode") or ""),
            color_depth=str(data.get("color_depth") or ""),
            view_transform=str(data.get("view_transform") or ""),
            look=str(data.get("look") or ""),
            camera=str(data.get("camera") or ""),
            fps=float(data.get("fps") or 24.0),
            film_transparent=bool(data.get("film_transparent")),
            motion_blur=bool(data.get("motion_blur")),
            denoise=bool(data.get("denoise")),
            use_sequencer=bool(data.get("use_sequencer")),
        )
        return cls(
            engine=str(data.get("engine") or ""),
            resolution_x=int(data.get("resolution_x") or 0),
            resolution_y=int(data.get("resolution_y") or 0),
            resolution_percentage=int(data.get("resolution_percentage") or 100),
            samples=int(data.get("samples") or 0),
            denoise=bool(data.get("denoise")),
            frame_start=int(data.get("frame_start") or 0),
            frame_end=int(data.get("frame_end") or 0),
            frame_step=int(data.get("frame_step") or 1),
            object_count=int(data.get("object_count") or 0),
            mesh_count=int(data.get("mesh_count") or 0),
            library_count=int(data.get("library_count") or 0),
            geometry_node_objects=int(data.get("geometry_node_objects") or 0),
            has_camera=bool(data.get("has_camera")),
            libraries=tuple(str(item) for item in data.get("libraries") or ()),
            images=tuple(str(item) for item in data.get("images") or ()),
            output_path=str(data.get("output_path") or ""),
            file_format=str(data.get("file_format") or ""),
            setup=setup,
        )


class BlenderProbe:
    """Run the probe script with a specific Blender executable."""

    def __init__(self, blender_path: Path | str, *, timeout: float = 120.0) -> None:
        self.blender_path = Path(blender_path)
        self.timeout = float(timeout)

    def probe(self, blend_path: Path | str) -> RenderProbeResult:
        blend = Path(blend_path)
        if not blend.is_file():
            raise RenderProbeError(f"Scene not found: {blend}")
        if not self.blender_path.is_file():
            raise RenderProbeError(f"Blender executable not found: {self.blender_path}")

        with tempfile.TemporaryDirectory(prefix="openstudio_render_probe_") as temp_dir:
            temp = Path(temp_dir)
            script = temp / "probe.py"
            script.write_text(_PROBE_SCRIPT, encoding="utf-8")
            config = temp / "config"
            scripts = temp / "scripts"
            config.mkdir()
            scripts.mkdir()

            env = os.environ.copy()
            env["BLENDER_USER_CONFIG"] = str(config)
            env["BLENDER_USER_SCRIPTS"] = str(scripts)
            env.setdefault("LC_ALL", "C")
            env.setdefault("LANG", "C")

            command = [
                str(self.blender_path),
                "-b",
                "--factory-startup",
                str(blend),
                "--python",
                str(script),
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    env=env,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise RenderProbeError(f"Could not inspect {blend.name}: {error}") from error

        payload = _extract_payload(result.stdout)
        if payload is None:
            tail = (result.stderr or result.stdout or "").strip().splitlines()[-8:]
            detail = " | ".join(tail) or "no output"
            raise RenderProbeError(f"Blender could not inspect {blend.name}: {detail}")
        return RenderProbeResult.from_dict(payload)


def _extract_payload(stdout: str) -> dict | None:
    for line in (stdout or "").splitlines():
        if _PROBE_MARKER in line:
            try:
                return json.loads(line.split(_PROBE_MARKER, 1)[1])
            except ValueError:
                return None
    return None


def iter_blend_files(root: Path | str) -> Iterable[Path]:
    """Yield shot ``.blend`` files under ``root`` without SVN/backup noise."""
    root_path = Path(root)
    if not root_path.exists():
        return
    for path in sorted(root_path.rglob("*.blend")):
        if not path.is_file():
            continue
        if ".svn" in path.parts or path.name.endswith((".blend1", ".blend2")):
            continue
        if "__pycache__" in path.parts:
            continue
        yield path
