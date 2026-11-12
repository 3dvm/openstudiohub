# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/render/capacity.py
# Architectural role: Render domain / capacity calculator
# =========================================================================================

"""Calculate how many GPU nodes are needed to finish a render by a deadline.

The model is intentionally conservative:

* every node pays a fixed setup cost (boot, Blender install, asset staging);
* a utilization factor covers scheduling gaps and uneven frame chunks;
* shots without a measured seconds-per-frame value use a conservative default
  based on resolution, samples and engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.domain.render.models import RenderPlan, RenderQuality, RenderShot

DEFAULT_UTILIZATION = 0.85
DEFAULT_SETUP_SECONDS = 600.0
_BASE_SECONDS_AT_1080P_128 = 30.0
_REFERENCE_PIXELS = 1920 * 1080
_GEOMETRY_NODE_FACTOR = 2.0
_EEVEE_FACTOR = 0.05


@dataclass(frozen=True)
class GpuProfile:
    """Marketplace-independent GPU class used by the planner."""

    key: str
    label: str
    vram_gb: int
    vast_gpu_name: str
    relative_speed: float = 1.0


GPU_PROFILES: dict[str, GpuProfile] = {
    "rtx_3090": GpuProfile("rtx_3090", "RTX 3090 24 GB", 24, "RTX_3090", 1.00),
    "rtx_4090": GpuProfile("rtx_4090", "RTX 4090 24 GB", 24, "RTX_4090", 1.55),
    "rtx_a6000": GpuProfile("rtx_a6000", "RTX A6000 48 GB", 48, "A6000", 1.00),
    "rtx_4070": GpuProfile("rtx_4070", "RTX 4070 12 GB", 12, "RTX_4070", 0.80),
    "rtx_3080": GpuProfile("rtx_3080", "RTX 3080 10 GB", 10, "RTX_3080", 0.80),
    "rtx_3070": GpuProfile("rtx_3070", "RTX 3070 8 GB", 8, "RTX_3070", 0.65),
}


def gpu_relative_speed(gpu_profile: str) -> float:
    profile = GPU_PROFILES.get(gpu_profile)
    return profile.relative_speed if profile is not None else 1.0


def similar_gpu_profiles(
    base_profile: str,
    mode: str = "floor",
    *,
    allow_less_vram: bool = False,
) -> tuple[str, ...]:
    """Return profiles considered similar to ``base_profile``.

    ``floor`` accepts the selected GPU or faster; ``ceiling`` accepts the
    selected GPU or slower. Host VRAM must cover the selected profile unless
    ``allow_less_vram`` explicitly relaxes that safety rule.
    """
    base = GPU_PROFILES.get(base_profile)
    if base is None:
        return ()
    direction = (mode or "floor").strip().lower()
    if direction not in ("floor", "ceiling"):
        direction = "floor"
    profiles = []
    for key, profile in GPU_PROFILES.items():
        if key == base_profile:
            continue
        if not allow_less_vram and profile.vram_gb < base.vram_gb:
            continue
        if direction == "floor":
            if profile.relative_speed < base.relative_speed:
                continue
        else:
            if profile.relative_speed > base.relative_speed:
                continue
        profiles.append((key, profile))
    profiles.sort(key=lambda item: (item[1].relative_speed, item[1].label))
    return tuple(key for key, _profile in profiles)


def slowest_gpu_profile(profiles) -> str:
    """Return the profile with the lowest relative speed."""
    keys = [str(key) for key in profiles if key in GPU_PROFILES]
    if not keys:
        return ""
    return min(keys, key=lambda key: GPU_PROFILES[key].relative_speed)


def scale_seconds_for_gpu(
    seconds: float,
    source_gpu: str,
    target_gpu: str,
) -> float:
    """Scale a measured time from one GPU class to another."""
    source_speed = max(0.1, gpu_relative_speed(source_gpu))
    target_speed = max(0.1, gpu_relative_speed(target_gpu))
    return float(seconds) * source_speed / target_speed


def default_seconds_per_frame(
    quality: RenderQuality,
    geometry_node_objects: int = 0,
) -> float:
    """Conservative fallback when a shot has not been benchmarked.

    Calibrated against a real RTX 3090 benchmark of a 1080p/128 sspp Cycles
    scene (29.5 s/frame) and a 1080p/256 spp scene (38.9 s/frame). The fallback
    deliberately overshoots (60 s for 1080p/256) so an unmeasured shot does not
    under-provision the farm. The calculator scales this reference for the
    target GPU class.
    """
    sample_factor = max(0.1, quality.samples / 128.0)
    pixel_factor = max(0.05, quality.pixels / _REFERENCE_PIXELS)
    seconds = _BASE_SECONDS_AT_1080P_128 * pixel_factor * sample_factor
    if quality.is_eevee:
        seconds *= _EEVEE_FACTOR
    if geometry_node_objects > 0:
        seconds *= _GEOMETRY_NODE_FACTOR
    return max(0.2, seconds)


class RenderCapacityCalculator:
    """Turn a set of shots and a deadline into nodes, ETA and cost."""

    def __init__(
        self,
        *,
        utilization: float = DEFAULT_UTILIZATION,
        setup_seconds: float = DEFAULT_SETUP_SECONDS,
    ) -> None:
        if not 0.0 < utilization <= 1.0:
            raise ValueError("utilization must be between 0 and 1")
        if setup_seconds < 0:
            raise ValueError("setup_seconds cannot be negative")
        self.utilization = float(utilization)
        self.setup_seconds = float(setup_seconds)

    def plan(
        self,
        shots: list[RenderShot] | tuple[RenderShot, ...],
        *,
        target_hours: float,
        gpu_profile: str,
        price_per_hour: float,
        max_nodes: int = 0,
        budget: float = 0.0,
        measured_speed_factor: float = 1.0,
    ) -> RenderPlan:
        if target_hours <= 0:
            raise ValueError("target_hours must be greater than zero")

        ready = [shot for shot in shots if shot.is_ready]
        skipped = tuple(shot.name for shot in shots if not shot.is_ready)
        unmeasured = tuple(
            shot.name for shot in ready if shot.measured_seconds is None
        )
        geometry_heavy = tuple(
            shot.name for shot in ready if shot.geometry_node_objects > 0
        )
        stale = tuple(shot.name for shot in ready if shot.measurement_stale)
        scaled = tuple(shot.name for shot in ready if shot.measurement_scaled)
        target_speed = max(0.1, gpu_relative_speed(gpu_profile))
        measured_factor = max(0.1, float(measured_speed_factor or 1.0))

        total_seconds = 0.0
        for shot in ready:
            seconds = shot.measured_seconds
            if seconds is None:
                seconds = default_seconds_per_frame(
                    shot.quality, shot.geometry_node_objects
                ) / target_speed
            else:
                seconds = float(seconds) * measured_factor
            total_seconds += shot.frames * max(0.0, float(seconds))

        target_seconds = float(target_hours) * 3600.0
        available = max(60.0, target_seconds - self.setup_seconds)
        uncapped_nodes = (
            0
            if total_seconds <= 0
            else max(1, math.ceil(total_seconds / (available * self.utilization)))
        )
        required_nodes = uncapped_nodes
        if max_nodes > 0:
            required_nodes = min(required_nodes, max_nodes)

        if required_nodes > 0:
            estimated_wall = self.setup_seconds + (
                total_seconds / (required_nodes * self.utilization)
            )
        else:
            estimated_wall = 0.0

        estimated_cost = (
            required_nodes * (estimated_wall / 3600.0) * max(0.0, price_per_hour)
        )

        warnings: list[str] = []
        if skipped:
            warnings.append(
                f"{len(skipped)} shot(s) are not ready and will be skipped: "
                + ", ".join(skipped)
            )
        if unmeasured:
            warnings.append(
                f"{len(unmeasured)} shot(s) have no benchmark; using a conservative "
                "estimate: " + ", ".join(unmeasured)
            )
        if geometry_heavy:
            warnings.append(
                "Shots with geometry nodes may be heavier than the estimate: "
                + ", ".join(geometry_heavy)
            )
        if stale:
            warnings.append(
                "Using a benchmark from a previous .blend version for: "
                + ", ".join(stale)
            )
        if scaled:
            warnings.append(
                "Estimating times from a benchmark of another GPU for: "
                + ", ".join(scaled)
            )
        if max_nodes > 0 and uncapped_nodes > required_nodes:
            warnings.append(
                f"Capped at {required_nodes} node(s); the deadline may be missed "
                f"(uncapped estimate: {uncapped_nodes})."
            )
        if total_seconds > 0 and estimated_wall > target_seconds:
            warnings.append(
                "Estimated wall time exceeds the target deadline."
            )
        if budget > 0 and estimated_cost > budget:
            warnings.append(
                f"Estimated cost ({estimated_cost:.2f}) exceeds the budget "
                f"({budget:.2f})."
            )

        if stale:
            confidence = "stale"
        elif scaled or unmeasured:
            confidence = "estimated"
        else:
            confidence = "measured"
        return RenderPlan(
            shots=tuple(ready),
            skipped=skipped,
            unmeasured=unmeasured,
            gpu_profile=gpu_profile,
            target_seconds=target_seconds,
            utilization=self.utilization,
            setup_seconds=self.setup_seconds,
            price_per_hour=max(0.0, price_per_hour),
            total_gpu_seconds=total_seconds,
            required_nodes=required_nodes,
            estimated_wall_seconds=estimated_wall,
            estimated_cost=estimated_cost,
            confidence=confidence,
            warnings=tuple(warnings),
        )
