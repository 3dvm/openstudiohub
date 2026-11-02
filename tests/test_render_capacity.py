"""Unit tests for the render capacity calculator."""

from dataclasses import replace
from pathlib import Path

from src.domain.render.capacity import (
    GPU_PROFILES,
    RenderCapacityCalculator,
    default_seconds_per_frame,
    scale_seconds_for_gpu,
)
from src.domain.render.models import RenderQuality, RenderShot


def _shot(name="sh010", frames=96, measured=40.5, ready=True, geometry_nodes=0):
    return RenderShot(
        name=name,
        blend_path=Path(f"/project/{name}.blend"),
        relative_path=f"pro/shots/sq010/{name}/{name}-layout.blend",
        sequence="sq010",
        quality=RenderQuality(
            engine="CYCLES", resolution_x=1920, resolution_y=1080, samples=256
        ),
        frame_start=101,
        frame_end=100 + frames,
        object_count=639 if ready else 4,
        mesh_count=625 if ready else 1,
        geometry_node_objects=geometry_nodes,
        has_camera=True,
        measured_seconds=measured,
    )


def test_default_seconds_scale_with_resolution_and_samples():
    full = RenderQuality(samples=256)
    half = RenderQuality(resolution_percentage=50, samples=128)
    eevee = RenderQuality(engine="BLENDER_EEVEE", samples=64)

    assert default_seconds_per_frame(full) == 60.0
    assert default_seconds_per_frame(half) == 7.5
    assert default_seconds_per_frame(eevee) == 0.75
    assert default_seconds_per_frame(full, geometry_node_objects=4) == 120.0


def test_one_hour_target_needs_two_nodes_for_the_measured_shot():
    plan = RenderCapacityCalculator().plan(
        [_shot()],
        target_hours=1,
        gpu_profile="rtx_3090",
        price_per_hour=0.15,
        budget=12.0,
    )

    assert plan.total_frames == 96
    assert plan.total_gpu_seconds == 96 * 40.5
    assert plan.required_nodes == 2
    assert plan.estimated_wall_seconds < 3600
    assert plan.confidence == "measured"
    assert plan.estimated_cost < 1.0


def test_two_hour_target_needs_one_node_for_the_measured_shot():
    plan = RenderCapacityCalculator().plan(
        [_shot()],
        target_hours=2,
        gpu_profile="rtx_3090",
        price_per_hour=0.15,
    )

    assert plan.required_nodes == 1
    assert plan.estimated_wall_seconds < 7200


def test_full_project_frames_scale_the_node_count():
    shots = [_shot("sh010", frames=792, measured=40.5)]
    one_hour = RenderCapacityCalculator().plan(
        shots, target_hours=1, gpu_profile="rtx_3090", price_per_hour=0.15
    )
    two_hours = RenderCapacityCalculator().plan(
        shots, target_hours=2, gpu_profile="rtx_3090", price_per_hour=0.15
    )

    assert one_hour.required_nodes == 13
    assert two_hours.required_nodes == 6


def test_empty_placeholder_shots_are_skipped():
    plan = RenderCapacityCalculator().plan(
        [_shot("sh010"), _shot("sh020", frames=144, measured=None, ready=False)],
        target_hours=1,
        gpu_profile="rtx_3090",
        price_per_hour=0.15,
    )

    assert [shot.name for shot in plan.shots] == ["sh010"]
    assert plan.skipped == ("sh020",)
    assert any("not ready" in warning for warning in plan.warnings)


def test_unmeasured_shots_use_the_conservative_default():
    plan = RenderCapacityCalculator().plan(
        [_shot(measured=None)],
        target_hours=1,
        gpu_profile="rtx_3090",
        price_per_hour=0.15,
    )

    assert plan.confidence == "estimated"
    assert plan.unmeasured == ("sh010",)
    assert plan.total_gpu_seconds == 96 * 60.0
    assert any("no benchmark" in warning for warning in plan.warnings)


def test_max_nodes_and_budget_warnings():
    plan = RenderCapacityCalculator().plan(
        [_shot(frames=792)],
        target_hours=1,
        gpu_profile="rtx_3090",
        price_per_hour=0.15,
        max_nodes=2,
        budget=0.01,
    )

    assert plan.required_nodes == 2
    assert any("Capped at 2" in warning for warning in plan.warnings)
    assert any("exceeds the budget" in warning for warning in plan.warnings)
    assert plan.estimated_wall_seconds > 3600


def test_budget_gpu_profiles_are_available():
    assert {"rtx_4070", "rtx_3080", "rtx_3070"} <= set(GPU_PROFILES)
    assert GPU_PROFILES["rtx_4070"].vram_gb == 12
    assert GPU_PROFILES["rtx_3080"].vram_gb == 10
    assert GPU_PROFILES["rtx_3070"].vram_gb == 8
    assert GPU_PROFILES["rtx_4070"].vast_gpu_name == "RTX_4070"


def test_seconds_scale_from_the_3090_reference():
    assert scale_seconds_for_gpu(38.9, "rtx_3090", "rtx_3090") == 38.9
    assert round(scale_seconds_for_gpu(38.9, "rtx_3090", "rtx_3070"), 2) == 59.85
    assert round(scale_seconds_for_gpu(38.9, "rtx_3090", "rtx_4070"), 2) == 48.62
    assert round(scale_seconds_for_gpu(38.9, "rtx_3090", "rtx_4090"), 2) == 25.10


def test_unmeasured_shot_uses_the_slower_budget_gpu_factor():
    shot = _shot(measured=None)
    fast = RenderCapacityCalculator().plan(
        [shot], target_hours=1, gpu_profile="rtx_3090", price_per_hour=0.1
    )
    budget = RenderCapacityCalculator().plan(
        [shot], target_hours=1, gpu_profile="rtx_3070", price_per_hour=0.1
    )
    assert budget.total_gpu_seconds > fast.total_gpu_seconds


def test_scaled_measurement_is_flagged_as_estimated():
    shot = _shot(measured=48.6)
    shot = replace(shot, measurement_scaled=True, measurement_source_gpu="rtx_3090")
    plan = RenderCapacityCalculator().plan(
        [shot], target_hours=1, gpu_profile="rtx_4070", price_per_hour=0.126
    )
    assert plan.confidence == "estimated"
    assert any("another GPU" in warning for warning in plan.warnings)
