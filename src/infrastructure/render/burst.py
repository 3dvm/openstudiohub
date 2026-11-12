# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/burst.py
# Architectural role: Render infrastructure / direct Vast.ai burst
# =========================================================================================

"""Render selected shots on short-lived Vast.ai GPU instances.

This is the "direct burst" backend: the Hub rents on-demand instances, installs
the project's Blender version inside each instance, stages the production folder
over SSH, renders a contiguous frame chunk and syncs the frames back to
``03_render``. Every instance is destroyed in a ``finally`` block.

Flamenco is intentionally not required here: the shared-storage constraint of a
persistent farm does not apply to an ephemeral per-job burst.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections import deque
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from src.domain.render.capacity import default_seconds_per_frame
from src.domain.render.formatting import format_bytes
from src.domain.render.image_formats import image_format
from src.domain.render.models import RenderPlan, RenderShot
from src.infrastructure.render.frame_state import RenderFrameStateStore
from src.infrastructure.render.run_audit import RenderRunAuditLogger
from src.infrastructure.render.staging import (
    STAGING_EXCLUDES,
    bake_cache_names,
    scan_staging_for_shots,
)
from src.infrastructure.render.vast import (
    DEFAULT_DISK_GB,
    DEFAULT_IMAGE,
    VastError,
    VastInstance,
    VastOffer,
    VastProvider,
)

ProgressCallback = Callable[["BurstProgress"], None]

_VERIFY_SCRIPT = r"""
import hashlib
import json
import os
import sys

manifest = json.load(open(sys.argv[1], "r", encoding="utf-8"))
root = sys.argv[2]
missing = []
bad = []
for relative, expected in manifest.items():
    path = os.path.join(root, relative)
    if not os.path.isfile(path):
        missing.append(relative)
        continue
    size = os.path.getsize(path)
    if int(expected.get("bytes") or -1) != size:
        bad.append({"path": relative, "reason": "size", "actual": size,
                    "expected": expected.get("bytes")})
        continue
    digest = expected.get("sha256") or ""
    if digest:
        hasher = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        actual = hasher.hexdigest()
        if actual != digest:
            bad.append({"path": relative, "reason": "sha256",
                        "actual": actual, "expected": digest})
print("OSVERIFY::" + json.dumps({"missing": missing, "bad": bad}))
"""

_PREFLIGHT_SCRIPT = r"""
import bpy
import json
import os

missing_images = []
missing_libs = []
for image in bpy.data.images:
    if getattr(image, "packed_file", None) or not image.filepath:
        continue
    path = bpy.path.abspath(image.filepath)
    if path and not os.path.isfile(path):
        missing_images.append(image.filepath)
for library in bpy.data.libraries:
    path = bpy.path.abspath(library.filepath)
    if path and not os.path.isfile(path):
        missing_libs.append(library.filepath)
for world in bpy.data.worlds:
    tree = getattr(world, "node_tree", None)
    if tree is None:
        continue
    for node in tree.nodes:
        if getattr(node, "type", "") != "TEX_ENVIRONMENT":
            continue
        image = getattr(node, "image", None)
        if image is None or getattr(image, "packed_file", None):
            continue
        path = bpy.path.abspath(image.filepath)
        if path and not os.path.isfile(path):
            missing_images.append(image.filepath)
print("OSPREFLIGHT::" + json.dumps({
    "missing_images": sorted(set(missing_images)),
    "missing_libs": sorted(set(missing_libs)),
}))
"""

_RENDER_SCRIPT = r"""
import json
import os
import sys
import time

import bpy

config_path = sys.argv[-1]
with open(config_path, "r", encoding="utf-8") as handle:
    config = json.load(handle)

scene = bpy.context.scene
scene.render.engine = config["engine"]
scene.render.resolution_x = int(config["resolution_x"])
scene.render.resolution_y = int(config["resolution_y"])
scene.render.resolution_percentage = int(config["resolution_percentage"])
image_settings = scene.render.image_settings
if hasattr(image_settings, "media_type"):
    image_settings.media_type = config.get("media_type", "IMAGE")
image_settings.file_format = config.get("file_format", "PNG")
image_settings.color_mode = config.get("color_mode", "RGBA")
image_settings.color_depth = config.get("color_depth", "8")
scene.render.filepath = config["output_dir"]

if config["engine"] == "CYCLES":
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = config.get("device_type", "CUDA")
    prefs.get_devices()
    for device in prefs.devices:
        device.use = device.type != "CPU"
    scene.cycles.device = "GPU"
    scene.cycles.samples = int(config["samples"])
    scene.cycles.use_denoising = bool(config.get("denoise", True))
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    scene.render.use_persistent_data = True
    print(
        "OSDEVICES::" + json.dumps([(d.name, d.type, d.use) for d in prefs.devices]),
        flush=True,
    )
elif config["engine"].upper().startswith("BLENDER_EEVEE"):
    eevee = getattr(scene, "eevee", None)
    if eevee is not None:
        eevee.taa_render_samples = int(config["samples"])


if config.get("bake_geometry_nodes"):
    host_names = list(config.get("bake_hosts") or [])
    missing_hosts = [
        name for name in host_names if bpy.data.objects.get(name) is None
    ]
    if missing_hosts:
        raise RuntimeError(
            "Geometry-node bake host(s) not found: " + ", ".join(missing_hosts)
        )

    def enable_object_collections(view_layer, obj):
        def walk(layer_collection):
            collection = layer_collection.collection
            if obj.name in collection.objects:
                layer_collection.exclude = False
                layer_collection.hide_viewport = False
                collection.hide_viewport = False
                return True
            for child in layer_collection.children:
                if walk(child):
                    return True
            return False

        return walk(view_layer.layer_collection)

    hosts = []
    try:
        for candidate in bpy.context.view_layer.objects:
            candidate.select_set(False)
    except Exception:
        pass
    for name in host_names:
        obj = bpy.data.objects.get(name)
        if obj is None or getattr(obj, "hide_render", False):
            continue
        try:
            enable_object_collections(bpy.context.view_layer, obj)
            obj.hide_set(False)
            obj.hide_viewport = False
            obj.select_set(True)
        except Exception as exc:
            print("OSBAKE::gn:select_error::%s::%s" % (obj.name, exc), flush=True)
        if obj.select_get():
            hosts.append(obj)

    if host_names and not hosts:
        raise RuntimeError(
            "No geometry-node bake host could be selected: "
            + ", ".join(host_names)
        )
    if not hosts:
        print("OSBAKE::gn:none", flush=True)
    else:
        print("OSBAKE::gn:start::" + ",".join(obj.name for obj in hosts), flush=True)
        for obj in hosts:
            for modifier in obj.modifiers:
                if getattr(modifier, "type", "") != "NODES":
                    continue
                bakes = list(getattr(modifier, "bakes", ()) or ())
                for bake in bakes:
                    print(
                        "OSBAKE::gn:bake::%s::%s::%s::%s::%s::%s"
                        % (
                            obj.name,
                            modifier.name,
                            getattr(bake, "bake_mode", ""),
                            getattr(bake, "bake_target", ""),
                            getattr(bake, "frame_start", 0),
                            getattr(bake, "frame_end", 0),
                        ),
                        flush=True,
                    )
        bpy.context.view_layer.objects.active = hosts[0]
        with bpy.context.temp_override(
            scene=scene,
            selected_objects=hosts,
            selected_editable_objects=hosts,
            active_object=hosts[0],
            object=hosts[0],
        ):
            result = bpy.ops.object.simulation_nodes_cache_bake(selected=True)
        print("OSBAKE::gn:result::%s" % result, flush=True)
        if "FINISHED" not in result:
            raise RuntimeError(
                "Geometry-node bake did not finish: %s" % (result,)
            )
        print("OSBAKE::gn:done", flush=True)

if config.get("bake_particles"):
    print("OSBAKE::start", flush=True)
    scene.frame_start = int(config.get("frame_start", scene.frame_start))
    scene.frame_end = int(config.get("frame_end", scene.frame_end))
    baked = 0
    for obj in bpy.data.objects:
        for psys in getattr(obj, "particle_systems", []):
            point_cache = getattr(psys, "point_cache", None)
            if point_cache is None:
                continue
            point_cache.use_disk_cache = True
            try:
                with bpy.context.temp_override(
                    scene=scene,
                    object=obj,
                    active_object=obj,
                    selected_objects=[obj],
                    selected_editable_objects=[obj],
                    point_cache=point_cache,
                ):
                    bpy.ops.ptcache.bake(bake=True)
                baked += 1
                print("OSBAKE::baked::%s::%s" % (obj.name, psys.name), flush=True)
            except Exception as exc:
                print(
                    "OSBAKE::error::%s::%s::%s" % (obj.name, psys.name, exc),
                    flush=True,
                )
    if baked == 0:
        try:
            with bpy.context.temp_override(scene=scene):
                bpy.ops.ptcache.bake_all(bake=True)
            print("OSBAKE::bake_all_done", flush=True)
        except Exception as exc:
            print("OSBAKE::bake_all_error::%s" % exc, flush=True)
    print("OSBAKE::done::%d" % baked, flush=True)

output_dir = config["output_dir"]
preview_dir = config.get("preview_dir") or os.path.join(output_dir, ".live")
os.makedirs(output_dir, exist_ok=True)
os.makedirs(preview_dir, exist_ok=True)
for frame in config["frames"]:
    frame = int(frame)
    scene.frame_set(frame)
    scene.render.filepath = os.path.join(output_dir, "frame_%04d" % frame)
    started = time.monotonic()
    bpy.ops.render.render(write_still=True)
    elapsed = time.monotonic() - started
    preview_path = os.path.join(preview_dir, "frame_%04d.png" % frame)
    try:
        image = bpy.data.images.get("Render Result")
        settings = scene.render.image_settings
        previous = (
            getattr(settings, "file_format", ""),
            getattr(settings, "color_mode", ""),
            getattr(settings, "color_depth", ""),
        )
        settings.file_format = "PNG"
        settings.color_mode = "RGBA"
        settings.color_depth = "8"
        image.save_render(preview_path, scene=scene)
        settings.file_format, settings.color_mode, settings.color_depth = previous
    except Exception:
        preview_path = ""
    print(
        "OSFRAME::" + json.dumps({
            "frame": frame,
            "seconds": round(elapsed, 3),
            "preview": preview_path,
        }),
        flush=True,
    )
"""


class BurstError(RuntimeError):
    """Raised when the burst cannot start or a node fails unexpectedly."""


@dataclass(frozen=True)
class BurstProgress:
    node: int
    stage: str
    message: str
    frames_done: int = 0
    frames_total: int = 0
    instance_id: int = 0
    gpu_name: str = ""
    region: str = ""
    price_per_hour: float = 0.0
    offer_id: int = 0
    shot: str = ""
    shot_path: str = ""
    assignment: tuple[tuple[str, tuple[int, ...]], ...] = ()
    ok: bool = False
    frame: int = 0
    live_frame_path: str = ""
    bytes_done: int = 0
    bytes_total: int = 0
    files_total: int = 0
    blender_logs: tuple[str, ...] = ()
    run_id: str = ""


@dataclass
class NodeResult:
    node: int
    instance_id: int
    ok: bool
    message: str
    frames_done: int
    frames_expected: int
    wall_seconds: float
    cost: float
    missing: tuple[int, ...] = ()
    stage: str = ""
    gpu_name: str = ""
    region: str = ""
    price_per_hour: float = 0.0
    duration_ms: int = 0
    blender_logs: tuple[str, ...] = ()
    remote_logs: tuple[str, ...] = ()
    diagnostics_log: str = ""


@dataclass
class BurstReport:
    ok: bool
    message: str
    nodes: tuple[NodeResult, ...]
    frames_expected: int
    frames_rendered: int
    missing: tuple[int, ...]
    wall_seconds: float
    cost: float
    run_id: str = ""


@dataclass(frozen=True)
class BurstTask:
    shot: RenderShot
    frames: tuple[int, ...]
    output_subdir: str
    output_root: Path | None = None

    @property
    def remote_blend(self) -> str:
        return self.shot.relative_path

    @property
    def remote_output_subdir(self) -> str:
        """Unique remote folder so variants of one shot never share frames."""
        token = hashlib.sha1(
            self.shot.relative_path.encode("utf-8")
        ).hexdigest()[:10]
        return f"{token}/{self.output_subdir}"


class RenderBurstRunner:
    def __init__(
        self,
        provider: VastProvider,
        *,
        project_root: Path | str,
        output_root: Path | str,
        ssh_key_path: Path | str,
        production_folder: str,
        blender_version: str,
        work_root: str = "/root/openstudio",
        image: str = DEFAULT_IMAGE,
        disk_gb: int = DEFAULT_DISK_GB,
        max_price_per_hour: float = 0.0,
        task_type: str = "render",
        preferred_region: str = "prefer_us",
        min_inet_down_mbps: float = 0.0,
        min_inet_up_mbps: float = 0.0,
        bake_particles: bool = False,
        bake_geometry_nodes: bool = False,
        min_cpu_ram_gb: float = 0.0,
        fill_similar_gpus: bool = False,
        similar_gpu_mode: str = "floor",
        fill_allow_less_vram: bool = False,
        gpu_profile: str = "",
        audit: RenderRunAuditLogger | None = None,
        skip_existing: bool = False,
        run_id: str = "",
        output_roots: dict[str, Path | str] | None = None,
    ) -> None:
        self.provider = provider
        self.project_root = Path(project_root)
        self.output_root = Path(output_root)
        self.ssh_key_path = Path(ssh_key_path).expanduser()
        self.production_folder = production_folder
        self.blender_version = blender_version
        self.work_root = work_root.rstrip("/")
        self.image = image
        self.disk_gb = int(disk_gb)
        self.max_price_per_hour = float(max_price_per_hour)
        self.task_type = str(task_type or "render")
        self.preferred_region = str(preferred_region or "prefer_us")
        self.min_inet_down_mbps = float(min_inet_down_mbps or 0.0)
        self.min_inet_up_mbps = float(min_inet_up_mbps or 0.0)
        self.bake_particles = bool(bake_particles)
        self.bake_geometry_nodes = bool(bake_geometry_nodes)
        self.min_cpu_ram_gb = float(min_cpu_ram_gb or 0.0)
        self.fill_similar_gpus = bool(fill_similar_gpus)
        self.similar_gpu_mode = str(similar_gpu_mode or "floor")
        self.fill_allow_less_vram = bool(fill_allow_less_vram)
        self.gpu_profile = str(gpu_profile or "")
        self.audit = audit
        self.skip_existing = bool(skip_existing)
        self._output_roots = {
            str(relative_path): Path(root)
            for relative_path, root in (output_roots or {}).items()
        }
        self._plan_bake_cache_names: tuple[str, ...] = ()
        self._instances: dict[int, VastInstance] = {}
        self._node_stage: dict[int, str] = {}
        self._node_diagnostics: dict[int, str] = {}
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._run_id = str(run_id or uuid.uuid4().hex[:8])

    @property
    def run_id(self) -> str:
        return self._run_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            instances = list(self._instances.items())
        for instance_id, _instance in instances:
            try:
                self.provider.destroy_instance(instance_id)
            except VastError:
                continue

    def run(
        self,
        shots: Sequence[RenderShot],
        plan: RenderPlan,
        *,
        progress: ProgressCallback | None = None,
        node_indices: Sequence[int] | None = None,
    ) -> BurstReport:
        if not self.ssh_key_path.is_file():
            raise BurstError(f"SSH key not found: {self.ssh_key_path}")
        self._plan_bake_cache_names = (
            bake_cache_names(plan.shots) if self.bake_geometry_nodes else ()
        )

        initial_assignments = [
            assignment
            for assignment in self._assign(shots, max(1, plan.required_nodes), plan)
            if assignment
        ]
        if not initial_assignments:
            return BurstReport(
                ok=False,
                message="No ready shots with frames to render.",
                nodes=(),
                frames_expected=0,
                frames_rendered=0,
                missing=(),
                wall_seconds=0.0,
                cost=0.0,
            )

        balance = self.provider.balance()
        if plan.estimated_cost > 0 and balance < plan.estimated_cost:
            raise BurstError(
                f"Vast.ai balance ({balance:.2f}) is below the estimated cost "
                f"({plan.estimated_cost:.2f}). Top up before starting."
            )

        offers = self.provider.choose_offers(
            self.gpu_profile or plan.gpu_profile,
            count=len(initial_assignments),
            max_price_per_hour=self.max_price_per_hour or plan.price_per_hour,
            min_disk_gb=self.disk_gb,
            preferred_region=self.preferred_region,
            min_inet_down_mbps=self.min_inet_down_mbps,
            min_inet_up_mbps=self.min_inet_up_mbps,
            min_cpu_ram_gb=self.min_cpu_ram_gb,
            fill_similar=self.fill_similar_gpus,
            similar_mode=self.similar_gpu_mode,
            allow_less_vram=self.fill_allow_less_vram,
        )
        if not offers:
            raise BurstError("No Vast.ai offer is available for this GPU profile.")
        if len(offers) < len(initial_assignments):
            raise BurstError(
                f"Only {len(offers)} Vast.ai offer(s) are available for "
                f"{len(initial_assignments)} planned node(s). Refresh the plan, "
                "fill with similar GPUs, or cap the node count."
            )

        indices = (
            list(node_indices)
            if node_indices is not None
            else list(range(len(initial_assignments)))
        )
        if len(indices) < len(initial_assignments):
            indices.extend(
                range(len(indices), len(initial_assignments))
            )
        indices = indices[: len(initial_assignments)]

        self._audit(
            "run_start",
            project=self.project_root.name,
            plan_frames=plan.total_frames,
            nodes=len(initial_assignments),
            gpu_profile=plan.gpu_profile,
            estimated_cost=plan.estimated_cost,
            balance=balance,
        )

        started = time.monotonic()
        results: list[NodeResult] = []
        expected_total = sum(
            len(task.frames) for tasks in initial_assignments for task in tasks
        )

        try:
            with ThreadPoolExecutor(max_workers=len(initial_assignments)) as pool:
                futures = {
                    pool.submit(
                        self._run_node,
                        indices[index],
                        tasks,
                        offers[index % len(offers)],
                        progress,
                    ): index
                    for index, tasks in enumerate(initial_assignments)
                }
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        results.append(future.result())
                    except Exception as error:  # noqa: BLE001
                        results.append(
                            NodeResult(
                                node=indices[index],
                                instance_id=0,
                                ok=False,
                                message=str(error),
                                frames_done=0,
                                frames_expected=sum(
                                    len(task.frames)
                                    for task in initial_assignments[index]
                                ),
                                wall_seconds=0.0,
                                cost=0.0,
                                stage="unknown",
                            )
                        )
        except Exception as error:  # noqa: BLE001
            self._audit("run_error", message=str(error))
            raise
        finally:
            self.cancel()

        wall_seconds = time.monotonic() - started
        expected = expected_total
        rendered = sum(result.frames_done for result in results)
        missing = tuple(frame for result in results for frame in result.missing)
        cost = sum(result.cost for result in results)
        ok = bool(results) and all(result.ok for result in results) and not missing
        message = (
            f"Rendered {rendered}/{expected} frame(s) on {len(results)} node(s)."
            if ok
            else f"Rendered {rendered}/{expected} frame(s); {len(missing)} missing."
        )
        report = BurstReport(
            ok=ok,
            message=message,
            nodes=tuple(sorted(results, key=lambda item: item.node)),
            frames_expected=expected,
            frames_rendered=rendered,
            missing=missing,
            wall_seconds=wall_seconds,
            cost=cost,
            run_id=self._run_id,
        )
        self._finish_audit(report)
        return report

    def _audit(self, event: str, **fields) -> None:
        if self.audit is None:
            return
        try:
            self.audit.log(event, run_id=self._run_id, **fields)
        except Exception:  # noqa: BLE001 - audit must never break a render
            pass

    def _audit_node(self, event: str, node: int, **fields) -> None:
        if self.audit is None:
            return
        try:
            self.audit.node_event(event, run_id=self._run_id, node=node, **fields)
        except Exception:  # noqa: BLE001 - audit must never break a render
            pass

    def _finish_audit(self, report: BurstReport) -> None:
        if self.audit is None:
            return
        self._audit(
            "run_finished",
            ok=report.ok,
            message=report.message,
            frames_expected=report.frames_expected,
            frames_rendered=report.frames_rendered,
            missing=list(report.missing),
            cost=report.cost,
            wall_seconds=report.wall_seconds,
        )
        try:
            self.audit.write_summary(
                self._run_id,
                {
                    "ok": report.ok,
                    "message": report.message,
                    "frames_expected": report.frames_expected,
                    "frames_rendered": report.frames_rendered,
                    "missing": list(report.missing),
                    "cost": report.cost,
                    "wall_seconds": report.wall_seconds,
                    "nodes": [
                        {
                            "node": node.node,
                            "instance_id": node.instance_id,
                            "ok": node.ok,
                            "stage": node.stage,
                            "message": node.message,
                            "frames_done": node.frames_done,
                            "frames_expected": node.frames_expected,
                            "cost": node.cost,
                            "gpu_name": node.gpu_name,
                            "region": node.region,
                            "price_per_hour": node.price_per_hour,
                            "duration_ms": node.duration_ms,
                            "blender_logs": list(node.blender_logs),
                        }
                        for node in report.nodes
                    ],
                },
            )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------
    def _assign(
        self,
        shots: Sequence[RenderShot],
        nodes: int,
        plan: RenderPlan | None = None,
    ) -> list[list[BurstTask]]:
        nodes = max(1, int(nodes))
        shot_frames: list[tuple[RenderShot, list[int], float]] = []
        for shot in shots:
            if not shot.is_ready:
                continue
            sequence = shot.sequence or "shots"
            output_subdir = f"shots/{sequence}/{shot.name}.{self.task_type}"
            output_root = self._output_roots.get(
                shot.relative_path, self.output_root
            )
            state = RenderFrameStateStore(output_root / output_subdir)
            approved = state.approved_frames()
            step = max(1, shot.frame_step)
            frames: list[int] = []
            for frame in range(shot.frame_start, shot.frame_end + 1, step):
                if frame in approved:
                    continue
                if self.skip_existing:
                    extension = image_format(shot.quality.file_format).extension
                    path = (
                        output_root
                        / output_subdir
                        / f"frame_{frame:04d}.{extension}"
                    )
                    if path.is_file():
                        continue
                frames.append(frame)
            if not frames:
                continue
            seconds = shot.measured_seconds
            if not seconds or seconds <= 0:
                seconds = default_seconds_per_frame(
                    shot.quality, shot.geometry_node_objects
                )
            shot_frames.append(
                (shot, frames, len(frames) * max(0.1, float(seconds)))
            )
        if not shot_frames:
            return []
        if nodes == 1:
            return [
                self._tasks_from_pairs(
                    (shot, frame)
                    for shot, frames, _weight in shot_frames
                    for frame in frames
                )
            ]

        total_weight = sum(weight for _shot, _frames, weight in shot_frames)
        if plan is not None:
            single_capacity = max(
                60.0,
                float(plan.target_seconds) - float(plan.setup_seconds),
            ) * max(0.1, float(plan.utilization))
        else:
            single_capacity = total_weight / nodes
        if any(weight > single_capacity for _shot, _frames, weight in shot_frames):
            entries = [
                (shot, frame)
                for shot, frames, _weight in shot_frames
                for frame in frames
            ]
            total = len(entries)
            chunks: list[list[tuple[RenderShot, int]]] = [[] for _ in range(nodes)]
            for index, entry in enumerate(entries):
                node = min(nodes - 1, (index * nodes) // total)
                chunks[node].append(entry)
            return [self._tasks_from_pairs(chunk) for chunk in chunks]

        bins: list[list[tuple[RenderShot, list[int], float]]] = [
            [] for _ in range(nodes)
        ]
        bin_weights = [0.0 for _ in range(nodes)]
        for item in sorted(shot_frames, key=lambda entry: entry[2], reverse=True):
            index = min(range(nodes), key=lambda candidate: bin_weights[candidate])
            bins[index].append(item)
            bin_weights[index] += item[2]
        return [
            self._tasks_from_pairs(
                (shot, frame)
                for shot, frames, _weight in items
                for frame in frames
            )
            for items in bins
        ]

    def _tasks_from_pairs(
        self, pairs: Iterable[tuple[RenderShot, int]]
    ) -> list[BurstTask]:
        tasks: list[BurstTask] = []
        current_shot: RenderShot | None = None
        current_frames: list[int] = []
        for shot, frame in pairs:
            if current_shot is not None and shot.relative_path != current_shot.relative_path:
                tasks.append(self._task(current_shot, current_frames))
                current_frames = []
            current_shot = shot
            current_frames.append(frame)
        if current_shot is not None:
            tasks.append(self._task(current_shot, current_frames))
        return [task for task in tasks if task.frames]

    def _task(self, shot: RenderShot, frames: Iterable[int]) -> BurstTask:
        sequence = shot.sequence or "shots"
        return BurstTask(
            shot=shot,
            frames=tuple(sorted(frames)),
            output_subdir=f"shots/{sequence}/{shot.name}.{self.task_type}",
            output_root=self._output_roots.get(shot.relative_path),
        )

    # ------------------------------------------------------------------
    # Node lifecycle
    # ------------------------------------------------------------------
    def _run_node(
        self,
        index: int,
        tasks: list[BurstTask],
        offer: VastOffer,
        progress: ProgressCallback | None,
    ) -> NodeResult:
        started = time.monotonic()
        instance: VastInstance | None = None
        expected = sum(len(task.frames) for task in tasks)
        rendered = 0
        missing: list[int] = []
        blender_logs: list[str] = []
        remote_logs: list[str] = []
        result: NodeResult | None = None
        stage = "offer"
        label = f"osh-render-{self.project_root.name}-{self._run_id}-{index}"
        self._audit_node(
            "node_started",
            index,
            instance_id=0,
            stage=stage,
            message="node assigned",
            gpu_name=getattr(offer, "gpu_name", ""),
            region=getattr(offer, "geolocation", ""),
            price_per_hour=getattr(offer, "price_per_hour", 0.0),
            frames_expected=expected,
        )
        try:
            self._emit(
                progress,
                index,
                "offer",
                f"renting {offer.gpu_name} at ${offer.price_per_hour:.2f}/h",
                gpu_name=getattr(offer, "gpu_name", ""),
                region=getattr(offer, "geolocation", ""),
                price_per_hour=getattr(offer, "price_per_hour", 0.0),
                offer_id=getattr(offer, "id", 0),
                assignment=tuple(
                    (task.shot.relative_path, task.frames) for task in tasks
                ),
            )
            stage = "create"
            instance = self.provider.create_instance(
                offer.id,
                label=label,
                image=self.image,
                disk_gb=self.disk_gb,
            )
            with self._lock:
                self._instances[instance.id] = instance
            self._emit(progress, index, "boot", f"instance {instance.id} created", instance_id=instance.id)
            stage = "boot"
            instance = self.provider.wait_running(
                instance.id,
                progress=lambda message: self._emit(
                    progress, index, "boot", message, instance_id=instance.id
                ),
            )
            stage = "ssh"
            self._wait_for_ssh(instance, index, progress)
            stage = "install"
            self._install_blender(instance, index, progress)
            stage = "stage"
            self._stage_project(instance, index, progress, tasks)
            stage = "verify"
            self._preflight_assets(instance, index, tasks, progress)

            with tempfile.TemporaryDirectory(prefix="openstudio_burst_") as temp_dir:
                temp = Path(temp_dir)
                render_script = temp / "render_frames.py"
                render_script.write_text(_RENDER_SCRIPT, encoding="utf-8")
                self._scp(instance, render_script, "/root/render_frames.py")

                for task in tasks:
                    if self._cancel.is_set():
                        raise BurstError("Render cancelled.")
                    stage = "render"
                    frames_rendered, remote_log = self._render_task(
                        instance,
                        task,
                        index,
                        progress,
                        rendered,
                        expected,
                        temp,
                        blender_logs,
                    )
                    rendered += frames_rendered
                    if remote_log:
                        remote_logs.append(remote_log)
                    stage = "sync"
                    self._sync_task_output(instance, task, index, progress)
                    if self.bake_particles:
                        stage = "bake"
                        self._sync_bake_cache(instance, task, index, progress)

            stage = "validate"
            for task in tasks:
                for frame in task.frames:
                    local = self._local_frame_path(task, frame)
                    if not local.is_file():
                        missing.append(frame)
            result = NodeResult(
                node=index,
                instance_id=instance.id,
                ok=not missing,
                message="completed" if not missing else f"{len(missing)} frame(s) missing",
                frames_done=rendered,
                frames_expected=expected,
                wall_seconds=time.monotonic() - started,
                cost=instance.price_per_hour * (time.monotonic() - started) / 3600.0,
                missing=tuple(missing),
                stage=stage,
                gpu_name=getattr(offer, "gpu_name", ""),
                region=getattr(offer, "geolocation", ""),
                price_per_hour=getattr(offer, "price_per_hour", 0.0),
                duration_ms=int((time.monotonic() - started) * 1000),
                blender_logs=tuple(blender_logs),
                remote_logs=tuple(remote_logs),
            )
            self._audit_node(
                "node_finished",
                index,
                instance_id=instance.id,
                stage=stage,
                ok=result.ok,
                message=result.message,
                frames_done=rendered,
                frames_expected=expected,
                cost=result.cost,
                blender_logs=list(blender_logs),
            )
            return result
        except Exception as error:  # noqa: BLE001
            if not missing:
                missing = [
                    frame
                    for task in tasks
                    for frame in task.frames
                    if not self._local_frame_path(task, frame).is_file()
                ]
            result = NodeResult(
                node=index,
                instance_id=instance.id if instance is not None else 0,
                ok=False,
                message=str(error),
                frames_done=rendered,
                frames_expected=expected,
                wall_seconds=time.monotonic() - started,
                cost=(
                    instance.price_per_hour * (time.monotonic() - started) / 3600.0
                    if instance is not None
                    else 0.0
                ),
                missing=tuple(missing),
                stage=stage,
                gpu_name=getattr(offer, "gpu_name", ""),
                region=getattr(offer, "geolocation", ""),
                price_per_hour=getattr(offer, "price_per_hour", 0.0),
                duration_ms=int((time.monotonic() - started) * 1000),
                blender_logs=tuple(blender_logs),
                remote_logs=tuple(remote_logs),
            )
            self._audit_node(
                "node_failed",
                index,
                instance_id=result.instance_id,
                stage=stage,
                message=str(error),
                frames_done=rendered,
                frames_expected=expected,
                cost=result.cost,
                blender_logs=list(blender_logs),
            )
            return result
        finally:
            if instance is not None:
                self._capture_remote_artifacts(instance, index, remote_logs)
                if result is not None:
                    result.diagnostics_log = self._node_diagnostics.get(index, "")
            if result is not None:
                self._write_node_summary(index, result)
                self._emit(
                    progress,
                    index,
                    "finished" if result.ok else "failed",
                    result.message,
                    frames_done=result.frames_done,
                    frames_total=result.frames_expected,
                    instance_id=result.instance_id,
                    gpu_name=result.gpu_name,
                    region=result.region,
                    price_per_hour=result.price_per_hour,
                    ok=result.ok,
                    blender_logs=result.blender_logs,
                )
            if instance is not None:
                reason = "cancelled" if self._cancel.is_set() else "cleanup"
                try:
                    self.provider.destroy_instance(instance.id)
                    self._emit(
                        progress,
                        index,
                        "destroy",
                        f"instance {instance.id} destroyed ({reason})",
                        instance_id=instance.id,
                    )
                    self._audit_node(
                        "instance_destroyed",
                        index,
                        instance_id=instance.id,
                        reason=reason,
                        message=f"instance {instance.id} destroyed",
                    )
                except VastError as error:
                    self._audit_node(
                        "instance_destroy_failed",
                        index,
                        instance_id=instance.id,
                        message=str(error),
                    )
                with self._lock:
                    self._instances.pop(instance.id, None)

    def _write_node_summary(self, index: int, result: NodeResult) -> None:
        if self.audit is None:
            return
        try:
            self.audit.node_summary(
                self._run_id,
                index,
                {
                    "node": result.node,
                    "instance_id": result.instance_id,
                    "ok": result.ok,
                    "stage": result.stage,
                    "message": result.message,
                    "frames_done": result.frames_done,
                    "frames_expected": result.frames_expected,
                    "cost": result.cost,
                    "duration_ms": result.duration_ms,
                    "gpu_name": result.gpu_name,
                    "region": result.region,
                    "price_per_hour": result.price_per_hour,
                    "blender_logs": list(result.blender_logs),
                    "remote_logs": list(result.remote_logs),
                    "diagnostics_log": self._node_diagnostics.get(index, ""),
                },
            )
        except Exception:  # noqa: BLE001
            pass

    def _capture_remote_artifacts(
        self, instance: VastInstance, index: int, remote_logs: list[str]
    ) -> None:
        """Copy remote Blender logs and diagnostics before destroying the node."""
        if self.audit is None:
            return
        run_dir = self.audit.run_dir(self._run_id)
        for remote in remote_logs:
            name = Path(remote).name
            result = self._ssh(
                instance, f"cat '{remote}'", check=False, timeout=60
            )
            if result.stdout:
                destination = run_dir / f"node-{index}-remote-{name}"
                try:
                    destination.write_text(result.stdout, encoding="utf-8")
                    self._audit_node(
                        "remote_log_saved",
                        index,
                        message=str(destination),
                    )
                except OSError:
                    pass
        diagnostics_command = (
            "nvidia-smi 2>&1 | head -80; echo '--- free ---'; free -m; "
            "echo '--- disk ---'; df -h /root; "
            "echo '--- dmesg ---'; dmesg 2>&1 | tail -100"
        )
        result = self._ssh(
            instance, diagnostics_command, check=False, timeout=60
        )
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        if output:
            destination = run_dir / f"node-{index}-diagnostics.log"
            try:
                destination.write_text(output + "\n", encoding="utf-8")
                self._node_diagnostics[index] = str(destination)
                self._audit_node(
                    "diagnostics_saved",
                    index,
                    message=str(destination),
                )
            except OSError:
                pass

    def _wait_for_ssh(
        self, instance: VastInstance, index: int, progress: ProgressCallback | None
    ) -> None:
        for attempt in range(1, 31):
            if self._cancel.is_set():
                raise BurstError("Render cancelled.")
            result = self._ssh(instance, "echo ok", check=False, timeout=20)
            if result.returncode == 0:
                self._emit(progress, index, "ssh", "SSH ready", instance_id=instance.id)
                return
            time.sleep(5)
        raise BurstError(f"SSH to instance {instance.id} did not become ready.")

    def _install_blender(
        self, instance: VastInstance, index: int, progress: ProgressCallback | None
    ) -> None:
        self._emit(progress, index, "setup", "installing Blender and runtime libraries", instance_id=instance.id)
        major_minor = ".".join(self.blender_version.split(".")[:2])
        archive = f"blender-{self.blender_version}-linux-x64"
        url = (
            f"https://download.blender.org/release/Blender{major_minor}/"
            f"{archive}.tar.xz"
        )
        command = (
            "set -e\n"
            "export DEBIAN_FRONTEND=noninteractive\n"
            "apt-get update -qq\n"
            "apt-get install -y -qq --no-install-recommends "
            "libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 "
            "libsm6 libice6 libgl1 libegl1 libgomp1 rsync ca-certificates curl xvfb >/dev/null\n"
            "mkdir -p /root/blender\n"
            "if [ ! -x /root/blender/blender ]; then\n"
            f"  curl -L --fail -sS -o /root/blender.tar.xz '{url}'\n"
            "  tar -xf /root/blender.tar.xz -C /root\n"
            f"  mv /root/{archive}/* /root/blender/\n"
            f"  rm -rf /root/{archive} /root/blender.tar.xz\n"
            "fi\n"
            "/root/blender/blender -b --version | head -3\n"
        )
        result = self._ssh(instance, command, timeout=900)
        if result.returncode != 0:
            raise BurstError(f"Blender install failed: {_tail(result.stderr or result.stdout)}")
        self._emit(progress, index, "setup", "Blender ready", instance_id=instance.id)

    def _verify_upload(
        self,
        instance: VastInstance,
        index: int,
        plan,
        progress: ProgressCallback | None,
    ) -> None:
        manifest = {
            item.relative_path: {
                "bytes": item.bytes,
                "sha256": item.sha256,
            }
            for item in getattr(plan, "manifest", ()) or ()
        }
        if not manifest:
            return
        self._emit(
            progress,
            index,
            "verify",
            f"Verifying {len(manifest)} uploaded file(s)...",
            instance_id=instance.id,
        )
        with tempfile.TemporaryDirectory(prefix="openstudio_verify_") as temp_dir:
            temp = Path(temp_dir)
            manifest_path = temp / "manifest.json"
            script_path = temp / "verify.py"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            script_path.write_text(_VERIFY_SCRIPT, encoding="utf-8")
            self._scp(instance, manifest_path, "/root/os_verify_manifest.json")
            self._scp(instance, script_path, "/root/os_verify.py")
        remote_root = f"{self.work_root}/{self.production_folder}"
        result = self._ssh(
            instance,
            "python3 /root/os_verify.py /root/os_verify_manifest.json "
            f"'{remote_root}'",
            timeout=600,
        )
        payload = None
        for line in (result.stdout or "").splitlines():
            if "OSVERIFY::" in line:
                try:
                    payload = json.loads(line.split("OSVERIFY::", 1)[1])
                except ValueError:
                    payload = None
        if payload is None:
            raise BurstError(
                "Upload verification failed: no verification result from the node."
            )
        missing = list(payload.get("missing") or ())
        bad = list(payload.get("bad") or ())
        if missing or bad:
            details = []
            for item in missing[:5]:
                details.append(f"missing: {item}")
            for item in bad[:5]:
                details.append(
                    f"{item.get('reason')}: {item.get('path')} "
                    f"({item.get('actual')} vs {item.get('expected')})"
                )
            raise BurstError(
                "Upload verification failed: " + "; ".join(details)
            )
        self._emit(
            progress,
            index,
            "verify",
            f"Assets verified · {len(manifest)} file(s)",
            instance_id=instance.id,
        )

    def _preflight_assets(
        self,
        instance: VastInstance,
        index: int,
        tasks: Sequence[BurstTask],
        progress: ProgressCallback | None,
    ) -> None:
        if not tasks:
            return
        with tempfile.TemporaryDirectory(prefix="openstudio_preflight_") as temp_dir:
            script = Path(temp_dir) / "preflight.py"
            script.write_text(_PREFLIGHT_SCRIPT, encoding="utf-8")
            self._scp(instance, script, "/root/os_preflight.py")
        for task in tasks:
            remote_blend = (
                f"{self.work_root}/{self.production_folder}/{task.remote_blend}"
            )
            self._emit(
                progress,
                index,
                "verify",
                f"Preflight: {task.shot.name} libraries and images...",
                instance_id=instance.id,
                shot=task.shot.name,
                shot_path=task.shot.relative_path,
            )
            command = (
                "bash -lc \"cd '/root/openstudio' && "
                "/root/blender/blender -b --factory-startup "
                f"'{remote_blend}' --python /root/os_preflight.py\""
            )
            result = self._ssh(instance, command, timeout=600, check=False)
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            low = output.lower()
            warnings = (
                "unrecognized file format",
                "cannot find lib",
                "linked data-blocks are missing",
                "libraries and",
            )
            bad = [item for item in warnings if item in low]
            payload = None
            for line in output.splitlines():
                if "OSPREFLIGHT::" in line:
                    try:
                        payload = json.loads(line.split("OSPREFLIGHT::", 1)[1])
                    except ValueError:
                        payload = None
            missing_images = list((payload or {}).get("missing_images") or ())
            missing_libs = list((payload or {}).get("missing_libs") or ())
            if result.returncode != 0 or payload is None:
                raise BurstError(
                    f"Preflight failed for {task.shot.name}: Blender could not "
                    f"open the scene (exit {result.returncode})."
                )
            if bad or missing_images or missing_libs:
                details = list(bad)
                details.extend(f"missing image: {item}" for item in missing_images[:5])
                details.extend(f"missing library: {item}" for item in missing_libs[:5])
                raise BurstError(
                    f"Preflight failed for {task.shot.name}: "
                    + "; ".join(details[:8])
                )
            self._emit(
                progress,
                index,
                "verify",
                f"Preflight OK: {task.shot.name}",
                instance_id=instance.id,
                shot=task.shot.name,
                shot_path=task.shot.relative_path,
            )

    def _stage_project(
        self,
        instance: VastInstance,
        index: int,
        progress: ProgressCallback | None,
        tasks: Sequence[BurstTask] = (),
    ) -> None:
        exclude_names = self._plan_bake_cache_names
        plan = scan_staging_for_shots(
            self.project_root,
            self.production_folder,
            [task.shot for task in tasks],
            work_root=self.work_root,
            exclude_names=exclude_names,
        )
        if not plan.exists:
            raise BurstError(
                f"Production folder not found: "
                f"{self.project_root / self.production_folder}"
            )
        self._emit(
            progress,
            index,
            "stage",
            plan.summary,
            instance_id=instance.id,
            bytes_total=plan.bytes,
            files_total=plan.files,
        )
        uploaded_before = 0
        last_percent = -1
        last_emit = 0.0
        for entry in plan.entries:
            self._ssh(instance, f"mkdir -p '{entry.remote_path}'")

            def on_percent(percent: int, entry_bytes: int = entry.bytes) -> None:
                nonlocal uploaded_before, last_percent, last_emit
                done = uploaded_before + (entry_bytes * percent // 100)
                now = time.monotonic()
                if percent < 100 and percent == last_percent and now - last_emit < 5.0:
                    return
                if percent < 100 and percent - last_percent < 1 and now - last_emit < 5.0:
                    return
                last_percent = percent
                last_emit = now
                self._emit(
                    progress,
                    index,
                    "stage",
                    f"Uploading {percent}% · {format_bytes(done)} / "
                    f"{format_bytes(plan.bytes)}",
                    instance_id=instance.id,
                    bytes_done=done,
                    bytes_total=plan.bytes,
                    files_total=plan.files,
                    audit=False,
                )

            if entry.single_file:
                remote_parent = entry.remote_path.rsplit("/", 1)[0]
                self._ssh(instance, f"mkdir -p '{remote_parent}'")
                self._scp(instance, entry.local_path, entry.remote_path)
            else:
                self._rsync(
                    instance,
                    entry.local_path,
                    entry.remote_path,
                    extra_excludes=exclude_names,
                    on_percent=on_percent,
                    timeout_seconds=_rsync_timeout(entry.bytes),
                )
            uploaded_before += entry.bytes
        self._emit(
            progress,
            index,
            "stage",
            f"Upload complete · {format_bytes(plan.bytes)}",
            instance_id=instance.id,
            bytes_done=plan.bytes,
            bytes_total=plan.bytes,
            files_total=plan.files,
        )
        self._verify_upload(instance, index, plan, progress)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def _render_task(
        self,
        instance: VastInstance,
        task: BurstTask,
        index: int,
        progress: ProgressCallback | None,
        rendered_before: int,
        expected: int,
        temp: Path,
        blender_logs: list[str] | None = None,
    ) -> tuple[int, str]:
        shot = task.shot
        quality = shot.quality
        output_dir = f"{self.work_root}/out/{task.remote_output_subdir}"
        remote_blend = f"{self.work_root}/{self.production_folder}/{task.remote_blend}"
        fmt = image_format(quality.file_format)
        proxy_dir = (
            f"{output_dir}/.proxies" if fmt.identifier != "PNG" else ""
        )
        config = {
            "engine": quality.engine,
            "resolution_x": quality.resolution_x,
            "resolution_y": quality.resolution_y,
            "resolution_percentage": quality.resolution_percentage,
            "samples": quality.samples,
            "denoise": quality.denoise,
            "file_format": fmt.identifier,
            "color_mode": quality.color_mode,
            "color_depth": quality.color_depth,
            "media_type": fmt.media_type,
            "proxy_dir": proxy_dir,
            "output_dir": output_dir,
            "preview_dir": f"{output_dir}/.live",
            "frames": list(task.frames),
            "frame_start": min(task.frames),
            "frame_end": max(task.frames),
            "bake_particles": self.bake_particles,
            "bake_geometry_nodes": self.bake_geometry_nodes,
            "bake_hosts": sorted({
                bake.object_name
                for bake in task.shot.geometry_bakes
                if bake.object_name and not bake.hide_render
            }),
        }
        config_path = temp / f"config_{index}_{shot.name}.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        remote_config = f"/root/config_{index}_{shot.name}.json"
        self._scp(instance, config_path, remote_config)
        self._ssh(instance, f"mkdir -p '{output_dir}'")

        blender = "/root/blender/blender"
        if quality.is_eevee:
            blender = f"xvfb-run -a {blender}"
        safe_shot = "".join(
            ch if ch.isalnum() or ch in "-_" else "_" for ch in shot.name
        )
        remote_log = f"/root/openstudio-render-{index}-{safe_shot}.log"
        command = (
            f"bash -lc \"cd '{self.work_root}' && set -o pipefail; "
            f"{blender} -b --python-exit-code 1 --factory-startup '{remote_blend}' "
            f"--python /root/render_frames.py -- '{remote_config}' "
            f"2>&1 | tee '{remote_log}'\""
        )
        self._emit(
            progress,
            index,
            "render",
            f"rendering {len(task.frames)} frame(s) of {task.output_subdir}",
            frames_done=rendered_before,
            frames_total=expected,
            instance_id=instance.id,
            shot=shot.name,
            shot_path=shot.relative_path,
        )
        blender_log = None
        blender_handle = None
        if self.audit is not None:
            blender_log = self.audit.blender_log_path(self._run_id, index, shot.name)
            blender_handle = open(blender_log, "a", encoding="utf-8")
            blender_handle.write(
                f"# node {index} · {shot.name} · frames {min(task.frames)}-{max(task.frames)}\n"
            )
            blender_handle.flush()
            if blender_logs is not None:
                blender_logs.append(str(blender_log))
        self._audit_node(
            "render_task_started",
            index,
            stage="render",
            message=f"rendering {task.output_subdir}",
            frames=len(task.frames),
            blender_log=str(blender_log or ""),
        )
        process = subprocess.Popen(
            self._ssh_command(instance, command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        done = rendered_before
        tail: deque[str] = deque(maxlen=40)
        try:
            for line in process.stdout or ():
                tail.append(line.rstrip())
                if blender_handle is not None:
                    blender_handle.write(line)
                    blender_handle.flush()
                if self._cancel.is_set():
                    process.terminate()
                    break
                if "OSFRAME::" in line:
                    done += 1
                    message = line.strip().split("OSFRAME::", 1)[1]
                    frame = 0
                    live_path = ""
                    try:
                        payload = json.loads(message)
                        frame = int(payload.get("frame") or 0)
                        preview = str(payload.get("preview") or "")
                        if frame and preview:
                            live_path = self._download_live_frame(
                                instance,
                                index,
                                task,
                                frame,
                                preview,
                            )
                    except (TypeError, ValueError, BurstError):
                        live_path = ""
                    self._emit(
                        progress,
                        index,
                        "frame",
                        message,
                        frames_done=done,
                        frames_total=expected,
                        instance_id=instance.id,
                        shot=shot.name,
                        shot_path=shot.relative_path,
                        frame=frame,
                        live_frame_path=live_path,
                    )
                elif "OSBAKE::" in line:
                    self._emit(
                        progress,
                        index,
                        "bake",
                        line.strip().split("OSBAKE::", 1)[1],
                        instance_id=instance.id,
                        shot=shot.name,
                        shot_path=shot.relative_path,
                    )
                elif "OSDEVICES::" in line:
                    self._emit(
                        progress,
                        index,
                        "device",
                        line.strip().split("OSDEVICES::", 1)[1],
                        instance_id=instance.id,
                        shot=shot.name,
                        shot_path=shot.relative_path,
                    )
            process.wait(timeout=30)
        finally:
            if process.poll() is None:
                process.kill()
            if blender_handle is not None:
                blender_handle.close()
        if process.returncode != 0:
            if self.audit is not None:
                self.audit.append_node_log(
                    self._run_id,
                    index,
                    "Blender tail:\n" + "\n".join(tail),
                )
            raise BurstError(
                f"Blender failed on node {index} for {task.output_subdir} "
                f"(exit {process.returncode})."
            )
        self._audit_node(
            "render_task_finished",
            index,
            stage="render",
            message=f"rendered {task.output_subdir}",
            frames=done - rendered_before,
            blender_log=str(blender_log or ""),
        )
        return done - rendered_before, remote_log

    def _sync_task_output(
        self,
        instance: VastInstance,
        task: BurstTask,
        index: int,
        progress: ProgressCallback | None,
    ) -> None:
        self._emit(
            progress,
            index,
            "sync",
            f"syncing {task.output_subdir}",
            instance_id=instance.id,
            shot=task.shot.name,
        )
        output_root = task.output_root or self.output_root
        local = output_root / task.output_subdir
        local.mkdir(parents=True, exist_ok=True)
        remote = f"{self.work_root}/out/{task.remote_output_subdir}/"
        self._rsync(instance, remote, str(local), remote_source=True)

    def _sync_bake_cache(
        self,
        instance: VastInstance,
        task: BurstTask,
        index: int,
        progress: ProgressCallback | None,
    ) -> None:
        """Bring the particle cache back next to the local .blend."""
        shot_folder = Path(task.shot.relative_path).parent
        remote = (
            f"{self.work_root}/{self.production_folder}/"
            f"{shot_folder.as_posix().rstrip('/')}/"
        )
        local = self.project_root / self.production_folder / shot_folder
        local.mkdir(parents=True, exist_ok=True)
        self._emit(
            progress,
            index,
            "bake",
            "syncing particle cache",
            instance_id=instance.id,
        )
        try:
            self._rsync(
                instance,
                remote,
                str(local) + "/",
                remote_source=True,
                extra_excludes=("*.blend", "*.blend1", "*.blend2"),
            )
        except BurstError as error:
            self._emit(
                progress,
                index,
                "bake",
                f"cache sync skipped: {error}",
                instance_id=instance.id,
            )

    def _local_frame_path(self, task: BurstTask, frame: int) -> Path:
        extension = image_format(task.shot.quality.file_format).extension
        output_root = task.output_root or self.output_root
        return (
            output_root
            / task.output_subdir
            / f"frame_{frame:04d}.{extension}"
        )

    def _download_live_frame(
        self,
        instance: VastInstance,
        index: int,
        task: BurstTask,
        frame: int,
        remote_path: str,
    ) -> str:
        output_root = task.output_root or self.output_root
        local_dir = output_root / ".live" / self._run_id / str(index)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / f"frame_{frame:04d}.png"
        command = [
            "scp",
            "-q",
            "-i",
            str(self.ssh_key_path),
            "-P",
            str(instance.ssh_port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"root@{instance.ssh_host}:{remote_path}",
            str(local_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if result.returncode != 0 or not local_path.is_file():
            raise BurstError(
                f"Could not download live frame: "
                f"{_tail(result.stderr or result.stdout)}"
            )
        return str(local_path)

    # ------------------------------------------------------------------
    # SSH / rsync helpers
    # ------------------------------------------------------------------
    def _ssh_command(self, instance: VastInstance, remote_command: str) -> list[str]:
        return [
            "ssh",
            "-i",
            str(self.ssh_key_path),
            "-p",
            str(instance.ssh_port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=15",
            f"root@{instance.ssh_host}",
            remote_command,
        ]

    def _ssh(
        self,
        instance: VastInstance,
        remote_command: str,
        *,
        check: bool = True,
        timeout: float = 120.0,
    ) -> subprocess.CompletedProcess:
        result = subprocess.run(
            self._ssh_command(instance, remote_command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode != 0:
            raise BurstError(
                f"SSH command failed on {instance.ssh_host}: "
                f"{_tail(result.stderr or result.stdout)}"
            )
        return result

    def _scp(self, instance: VastInstance, local: Path, remote: str) -> None:
        command = [
            "scp",
            "-q",
            "-i",
            str(self.ssh_key_path),
            "-P",
            str(instance.ssh_port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            str(local),
            f"root@{instance.ssh_host}:{remote}",
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=300
        )
        if result.returncode != 0:
            raise BurstError(f"scp failed: {_tail(result.stderr or result.stdout)}")

    def _rsync(
        self,
        instance: VastInstance,
        local: Path | str,
        remote: str,
        *,
        remote_source: bool = False,
        extra_excludes: Sequence[str] = (),
        on_percent: Callable[[int], None] | None = None,
        timeout_seconds: float = 3600.0,
        attempts: int = 2,
    ) -> None:
        ssh = (
            f"ssh -i {self.ssh_key_path} -p {instance.ssh_port} "
            "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        )
        if remote_source:
            source = f"root@{instance.ssh_host}:{str(local).rstrip('/')}/"
            destination = str(remote).rstrip("/") + "/"
        else:
            source = str(local).rstrip("/") + "/"
            destination = f"root@{instance.ssh_host}:{str(remote).rstrip('/')}/"
        last_error = "rsync failed."
        for attempt in range(1, max(1, int(attempts)) + 1):
            command = ["rsync", "-az", "--partial"]
            if on_percent is not None and not remote_source:
                command.extend(["--info=progress2", "--no-inc-recursive"])
            for pattern in STAGING_EXCLUDES:
                command.extend(["--exclude", pattern])
            for pattern in extra_excludes:
                command.extend(["--exclude", pattern])
            command.extend(["-e", ssh, source, destination])

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            stdout_parts: list[str] = []
            stderr_parts: list[str] = []
            last_percent = -1

            def handle_stdout(line: str) -> None:
                nonlocal last_percent
                percent = _parse_rsync_progress(line)
                if percent is None or percent <= last_percent:
                    return
                last_percent = percent
                if on_percent is not None:
                    try:
                        on_percent(percent)
                    except Exception:  # noqa: BLE001
                        pass

            def drain(
                stream,
                sink: list[str],
                on_line: Callable[[str], None] | None = None,
            ) -> None:
                buffer = ""
                while True:
                    try:
                        chunk = os.read(stream.fileno(), 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", "replace")
                    sink.append(text)
                    if on_line is None:
                        continue
                    buffer += text
                    parts = re.split(r"[\r\n]", buffer)
                    buffer = parts.pop()
                    for part in parts:
                        on_line(part)
                if buffer and on_line is not None:
                    on_line(buffer)

            threads = [
                threading.Thread(
                    target=drain,
                    args=(process.stdout, stdout_parts, handle_stdout),
                    daemon=True,
                ),
                threading.Thread(
                    target=drain,
                    args=(process.stderr, stderr_parts),
                    daemon=True,
                ),
            ]
            for thread in threads:
                thread.start()
            try:
                returncode = process.wait(timeout=max(60.0, timeout_seconds))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=30)
                last_error = f"rsync timed out after {timeout_seconds:.0f}s."
                for thread in threads:
                    thread.join(timeout=5)
                if attempt < attempts:
                    time.sleep(5)
                    continue
                raise BurstError(
                    f"{last_error} ({attempt} attempt(s))."
                ) from None
            finally:
                for thread in threads:
                    thread.join(timeout=5)
            if returncode == 0:
                return
            stderr = "".join(stderr_parts) or "".join(stdout_parts)
            last_error = f"rsync failed: {_tail(stderr)}"
            if attempt < attempts:
                time.sleep(5)
                continue
            raise BurstError(last_error)
        raise BurstError(last_error)

    # ------------------------------------------------------------------
    # Progress helper
    # ------------------------------------------------------------------
    def _emit(
        self,
        callback: ProgressCallback | None,
        node: int,
        stage: str,
        message: str,
        *,
        frames_done: int = 0,
        frames_total: int = 0,
        instance_id: int = 0,
        gpu_name: str = "",
        region: str = "",
        price_per_hour: float = 0.0,
        offer_id: int = 0,
        shot: str = "",
        shot_path: str = "",
        assignment: tuple[tuple[str, tuple[int, ...]], ...] = (),
        ok: bool = False,
        frame: int = 0,
        live_frame_path: str = "",
        bytes_done: int = 0,
        bytes_total: int = 0,
        files_total: int = 0,
        blender_logs: tuple[str, ...] = (),
        audit: bool = True,
    ) -> None:
        self._node_stage[node] = stage
        if (
            audit
            and self.audit is not None
            and stage not in ("frame", "finished", "failed")
        ):
            self._audit_node(
                "node_progress",
                node,
                stage=stage,
                message=message,
                frames_done=frames_done,
                frames_total=frames_total,
                instance_id=instance_id,
                bytes_done=bytes_done,
                bytes_total=bytes_total,
            )
        if callback is None:
            return
        try:
            callback(
                BurstProgress(
                    node=node,
                    stage=stage,
                    message=message,
                    frames_done=frames_done,
                    frames_total=frames_total,
                    instance_id=instance_id,
                    gpu_name=gpu_name,
                    region=region,
                    price_per_hour=price_per_hour,
                    offer_id=offer_id,
                    shot=shot,
                    shot_path=shot_path,
                    assignment=assignment,
                    ok=ok,
                    frame=frame,
                    live_frame_path=live_frame_path,
                    bytes_done=bytes_done,
                    bytes_total=bytes_total,
                    files_total=files_total,
                    blender_logs=tuple(blender_logs),
                    run_id=self._run_id,
                )
            )
        except Exception:  # noqa: BLE001 - progress must never abort a render
            pass


def _rsync_timeout(byte_count: int, *, floor_seconds: float = 1800.0) -> float:
    """Allow at least a 1 MB/s transfer before declaring a timeout."""
    return max(float(floor_seconds), float(byte_count or 0) / 1_000_000.0)


def _parse_rsync_progress(line: str) -> int | None:
    """Return the percentage from an ``rsync --info=progress2`` line."""
    match = re.search(r"(\d{1,3})%", line or "")
    if match is None:
        return None
    percent = int(match.group(1))
    return percent if 0 <= percent <= 100 else None


def _tail(text: str, lines: int = 8) -> str:
    values = (text or "").strip().splitlines()
    return " | ".join(values[-lines:]) if values else "no output"
