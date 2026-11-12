# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/render/models.py
# Architectural role: Render domain / immutable planning models
# =========================================================================================

"""Render planning value objects.

These models describe the work (shots and frames), the quality target and the
capacity plan. They are framework-free so the calculator can be unit tested
without Blender, Qt or the Vast API.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

CYCLES = "CYCLES"
EEVEE_PREFIX = "BLENDER_EEVEE"


@dataclass(frozen=True)
class RenderQuality:
    """Target render settings applied to a shot."""

    engine: str = CYCLES
    resolution_x: int = 1920
    resolution_y: int = 1080
    resolution_percentage: int = 100
    samples: int = 128
    denoise: bool = True
    file_format: str = "PNG"
    color_mode: str = "RGBA"
    color_depth: str = "8"

    @property
    def effective_width(self) -> int:
        return max(1, round(self.resolution_x * self.resolution_percentage / 100))

    @property
    def effective_height(self) -> int:
        return max(1, round(self.resolution_y * self.resolution_percentage / 100))

    @property
    def pixels(self) -> int:
        return self.effective_width * self.effective_height

    @property
    def is_eevee(self) -> bool:
        return self.engine.upper().startswith(EEVEE_PREFIX)

    def key(self) -> str:
        """Stable key used by the measured-profile store."""
        return (
            f"{self.engine.upper()}|{self.effective_width}x{self.effective_height}"
            f"|{self.samples}|{int(self.denoise)}"
        )

    def label(self) -> str:
        return (
            f"{self.engine} {self.effective_width}x{self.effective_height} "
            f"@ {self.samples} spp · {self.file_format}"
        )


@dataclass(frozen=True)
class ViewLayerInfo:
    """One scene view layer and its compositor wiring."""

    name: str
    enabled: bool = True
    render_layers_node: str = ""
    connected_to_output: bool = False
    samples: int = 0


@dataclass(frozen=True)
class FileOutputInfo:
    """A compositor File Output node."""

    name: str
    base_path: str = ""
    file_format: str = ""
    layer: str = ""


@dataclass(frozen=True)
class RenderSetup:
    """The render/compositing configuration read from a scene.

    This is the audit surface for the panel. The Hub never writes these values
    back to the ``.blend``; the final and preview settings are applied to the
    headless render in memory.
    """

    use_nodes: bool = False
    compositing_enabled: bool = False
    compositor_name: str = ""
    view_layers: tuple[ViewLayerInfo, ...] = ()
    file_outputs: tuple[FileOutputInfo, ...] = ()
    output_format: str = ""
    color_mode: str = ""
    color_depth: str = ""
    view_transform: str = ""
    look: str = ""
    camera: str = ""
    fps: float = 24.0
    film_transparent: bool = False
    motion_blur: bool = False
    denoise: bool = False
    use_sequencer: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def enabled_layers(self) -> tuple[ViewLayerInfo, ...]:
        return tuple(layer for layer in self.view_layers if layer.enabled)

    @property
    def connected_layers(self) -> tuple[ViewLayerInfo, ...]:
        return tuple(layer for layer in self.enabled_layers if layer.connected_to_output)

    @property
    def has_compositor(self) -> bool:
        return bool(self.compositing_enabled and self.compositor_name)

    @property
    def is_compositing_ready(self) -> bool:
        layers = self.enabled_layers
        return bool(
            self.use_nodes
            and self.has_compositor
            and layers
            and all(layer.connected_to_output for layer in layers)
        )

    @property
    def writes_per_layer_files(self) -> bool:
        return bool(self.file_outputs)


@dataclass(frozen=True)
class GeometryBakeInfo:
    """One simulation bake defined by a geometry-nodes modifier."""

    object_name: str = ""
    modifier_name: str = ""
    bake_mode: str = ""
    bake_target: str = ""
    directory: str = ""
    frame_start: int = 0
    frame_end: int = 0
    use_custom_range: bool = False
    hide_render: bool = False
    local_cache: bool = False
    cache_stale: bool = False
    local_cache_mtime: float = 0.0

    @property
    def cache_dir_name(self) -> str:
        name = Path(self.directory.replace("\\", "/")).name
        return name if name.startswith("blendcache_") else ""


@dataclass(frozen=True)
class ParticleCacheInfo:
    """State of one particle system point cache."""

    object_name: str = ""
    system_name: str = ""
    baked: bool = False
    use_disk_cache: bool = False
    use_library_path: bool = False


@dataclass(frozen=True)
class RenderSettings:
    """Per-project render panel settings (shared in the pipeline folder)."""

    selected_shots: tuple[str, ...] = ()
    final_quality: RenderQuality = field(
        default_factory=lambda: RenderQuality(samples=256)
    )
    preview_quality: RenderQuality = field(
        default_factory=lambda: RenderQuality(
            resolution_x=1920,
            resolution_y=1080,
            resolution_percentage=50,
            samples=32,
            denoise=True,
        )
    )
    gpu_profile: str = "rtx_4070"
    target_hours: float = 1.0
    max_price_per_hour: float = 0.13
    max_nodes: int = 0
    budget: float = 10.0
    render_backend: str = "vast"
    preview_backend: str = "local"
    task_type: str = "render"
    video_enabled: bool = True
    video_task_type: str = "render"
    video_version: str = ""
    preview_frame_mode: str = "middle"
    preview_frame: int = 0
    preview_frames: tuple[tuple[str, int], ...] = ()
    local_speed_factor: float = 8.0
    bake_geometry_nodes: bool | None = None
    min_cpu_ram_gb: float = 0.0
    preferred_region: str = "prefer_americas"
    min_inet_down_mbps: float = 100.0
    min_inet_up_mbps: float = 50.0
    fill_similar_gpus: bool = False
    similar_gpu_mode: str = "floor"
    fill_allow_less_vram: bool = False

    def preview_frame_for(self, relative_path: str) -> int | None:
        """Return the explicit preview frame for a shot, when configured."""
        for path, frame in self.preview_frames:
            if path == relative_path:
                return int(frame)
        return None

    def to_dict(self) -> dict:
        return {
            "selected_shots": list(self.selected_shots),
            "final_quality": _quality_to_dict(self.final_quality),
            "preview_quality": _quality_to_dict(self.preview_quality),
            "gpu_profile": self.gpu_profile,
            "target_hours": self.target_hours,
            "max_price_per_hour": self.max_price_per_hour,
            "max_nodes": self.max_nodes,
            "budget": self.budget,
            "render_backend": self.render_backend,
            "preview_backend": self.preview_backend,
            "task_type": self.task_type,
            "video_enabled": self.video_enabled,
            "video_task_type": self.video_task_type,
            "video_version": self.video_version,
            "preview_frame_mode": self.preview_frame_mode,
            "preview_frame": self.preview_frame,
            "preview_frames": {
                str(path): int(frame) for path, frame in self.preview_frames
            },
            "local_speed_factor": self.local_speed_factor,
            "bake_geometry_nodes": self.bake_geometry_nodes,
            "min_cpu_ram_gb": self.min_cpu_ram_gb,
            "preferred_region": self.preferred_region,
            "min_inet_down_mbps": self.min_inet_down_mbps,
            "min_inet_up_mbps": self.min_inet_up_mbps,
            "fill_similar_gpus": self.fill_similar_gpus,
            "similar_gpu_mode": self.similar_gpu_mode,
            "fill_allow_less_vram": self.fill_allow_less_vram,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "RenderSettings":
        data = data or {}
        return cls(
            selected_shots=tuple(str(item) for item in data.get("selected_shots") or ()),
            final_quality=_quality_from_dict(
                data.get("final_quality"), RenderQuality(samples=256)
            ),
            preview_quality=_quality_from_dict(
                data.get("preview_quality"),
                RenderQuality(
                    resolution_percentage=50, samples=32, denoise=True
                ),
            ),
            gpu_profile=str(data.get("gpu_profile") or "rtx_4070"),
            target_hours=float(data.get("target_hours") or 1.0),
            max_price_per_hour=float(data.get("max_price_per_hour") or 0.13),
            max_nodes=int(data.get("max_nodes") or 0),
            budget=float(data.get("budget") or 10.0),
            render_backend=str(data.get("render_backend") or "vast"),
            preview_backend=str(data.get("preview_backend") or "local"),
            task_type=str(data.get("task_type") or "render"),
            video_enabled=bool(data.get("video_enabled", True)),
            video_task_type=str(data.get("video_task_type") or "render"),
            video_version=str(data.get("video_version") or ""),
            preview_frame_mode=str(data.get("preview_frame_mode") or "middle"),
            preview_frame=int(data.get("preview_frame") or 0),
            preview_frames=_preview_frames_from_dict(data.get("preview_frames")),
            local_speed_factor=float(data.get("local_speed_factor") or 8.0),
            bake_geometry_nodes=(
                bool(data["bake_geometry_nodes"])
                if data.get("bake_geometry_nodes") is not None
                else None
            ),
            min_cpu_ram_gb=float(data.get("min_cpu_ram_gb") or 0.0),
            preferred_region=str(data.get("preferred_region") or "prefer_americas"),
            min_inet_down_mbps=float(data.get("min_inet_down_mbps") or 100.0),
            min_inet_up_mbps=float(data.get("min_inet_up_mbps") or 50.0),
            fill_similar_gpus=bool(data.get("fill_similar_gpus", False)),
            similar_gpu_mode=(
                str(data.get("similar_gpu_mode") or "floor")
                if str(data.get("similar_gpu_mode") or "floor") in ("floor", "ceiling")
                else "floor"
            ),
            fill_allow_less_vram=bool(data.get("fill_allow_less_vram", False)),
        )


def _quality_to_dict(quality: RenderQuality) -> dict:
    return {
        "engine": quality.engine,
        "resolution_x": quality.resolution_x,
        "resolution_y": quality.resolution_y,
        "resolution_percentage": quality.resolution_percentage,
        "samples": quality.samples,
        "denoise": quality.denoise,
        "file_format": quality.file_format,
        "color_mode": quality.color_mode,
        "color_depth": quality.color_depth,
    }


def _quality_from_dict(data: dict | None, fallback: RenderQuality) -> RenderQuality:
    data = data or {}
    return RenderQuality(
        engine=str(data.get("engine") or fallback.engine),
        resolution_x=int(data.get("resolution_x") or fallback.resolution_x),
        resolution_y=int(data.get("resolution_y") or fallback.resolution_y),
        resolution_percentage=int(
            data.get("resolution_percentage") or fallback.resolution_percentage
        ),
        samples=int(data.get("samples") or fallback.samples),
        denoise=bool(data.get("denoise", fallback.denoise)),
        file_format=str(data.get("file_format") or fallback.file_format),
        color_mode=str(data.get("color_mode") or fallback.color_mode),
        color_depth=str(data.get("color_depth") or fallback.color_depth),
    )


def _preview_frames_from_dict(data) -> tuple[tuple[str, int], ...]:
    if not isinstance(data, dict):
        return ()
    entries: list[tuple[str, int]] = []
    for path, frame in data.items():
        try:
            value = int(frame)
        except (TypeError, ValueError):
            continue
        text = str(path or "").strip()
        if text:
            entries.append((text, value))
    return tuple(sorted(entries))


@dataclass(frozen=True)
class DependencyIssue:
    """One missing or non-project file referenced by a render shot."""

    path: str
    kind: str
    status: str  # external | missing | outside_production
    owner: str = ""
    blocking: bool = True


@dataclass(frozen=True)
class RenderShot:
    """One renderable shot and its measured (or estimated) cost."""

    name: str
    blend_path: Path
    relative_path: str
    sequence: str
    quality: RenderQuality
    frame_start: int
    frame_end: int
    frame_step: int = 1
    frames_override: int | None = None
    object_count: int = 0
    mesh_count: int = 0
    library_count: int = 0
    geometry_node_objects: int = 0
    has_camera: bool = True
    task_type: str = ""
    task_id: str = ""
    blend_hash: str = ""
    measured_seconds: float | None = None
    local_measured_seconds: float | None = None
    measurement_stale: bool = False
    measurement_scaled: bool = False
    measurement_source_gpu: str = ""
    setup: RenderSetup | None = None
    geometry_bakes: tuple[GeometryBakeInfo, ...] = ()
    particle_caches: tuple[ParticleCacheInfo, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = ()
    dependency_issues: tuple[DependencyIssue, ...] = ()
    dependencies_audited: bool = False

    @property
    def frames(self) -> int:
        if self.frames_override is not None:
            return max(0, int(self.frames_override))
        if self.frame_end < self.frame_start:
            return 0
        step = max(1, self.frame_step)
        return ((self.frame_end - self.frame_start) // step) + 1

    @property
    def is_ready(self) -> bool:
        """A shot must have a camera and real geometry to be worth rendering."""
        return (
            self.has_camera
            and self.frames > 0
            and self.object_count > 10
            and self.mesh_count > 0
        )

    def with_quality(
        self,
        quality: RenderQuality,
        measured_seconds: float | None = None,
    ) -> "RenderShot":
        return replace(
            self,
            quality=quality,
            measured_seconds=measured_seconds,
        )


@dataclass(frozen=True)
class RenderPlan:
    """Capacity result for a target wall-clock duration."""

    shots: tuple[RenderShot, ...]
    skipped: tuple[str, ...]
    unmeasured: tuple[str, ...]
    gpu_profile: str
    target_seconds: float
    utilization: float
    setup_seconds: float
    price_per_hour: float
    total_gpu_seconds: float
    required_nodes: int
    estimated_wall_seconds: float
    estimated_cost: float
    confidence: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_frames(self) -> int:
        return sum(shot.frames for shot in self.shots)

    @property
    def target_hours(self) -> float:
        return self.target_seconds / 3600.0

    @property
    def estimated_wall_hours(self) -> float:
        return self.estimated_wall_seconds / 3600.0
