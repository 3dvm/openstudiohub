"""Unit tests for direct Vast burst planning (no instances are created)."""

from pathlib import Path

from src.domain.render.capacity import RenderCapacityCalculator
from src.domain.render.models import RenderQuality, RenderShot
from src.infrastructure.render.burst import RenderBurstRunner


class FakeProvider:
    pass


def _runner() -> RenderBurstRunner:
    return RenderBurstRunner(
        FakeProvider(),
        project_root=Path("/project"),
        output_root=Path("/project/03_render"),
        ssh_key_path=Path("/tmp/key"),
        production_folder="02_archivos_de_produccion",
        blender_version="5.2.3",
    )


def _shot(name="sh010", frames=96, start=101):
    return RenderShot(
        name=name,
        blend_path=Path(f"/project/pro/shots/sq010/{name}/{name}-layout.blend"),
        relative_path=f"pro/shots/sq010/{name}/{name}-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=256),
        frame_start=start,
        frame_end=start + frames - 1,
        object_count=639,
        mesh_count=625,
        has_camera=True,
        measured_seconds=40.5,
    )


def test_assign_splits_frames_contiguously_across_nodes():
    shot = _shot()
    assignments = _runner()._assign([shot], 2)

    assert len(assignments) == 2
    assert [len(tasks[0].frames) for tasks in assignments] == [48, 48]
    assert assignments[0][0].frames[0] == 101
    assert assignments[1][0].frames[0] == 149
    assert assignments[0][0].output_subdir == "shots/sq010/sh010.render"


def test_assign_groups_multiple_shots_on_one_node():
    first = _shot("sh010", frames=10, start=101)
    second = _shot("sh020", frames=10, start=101)
    assignments = _runner()._assign([first, second], 1)

    assert len(assignments) == 1
    assert [task.shot.name for task in assignments[0]] == ["sh010", "sh020"]


def test_assign_skips_placeholder_shots():
    placeholder = RenderShot(
        name="sh020",
        blend_path=Path("/project/pro/shots/sq010/sh020/sh020-layout.blend"),
        relative_path="pro/shots/sq010/sh020/sh020-layout.blend",
        sequence="sq010",
        quality=RenderQuality(engine="BLENDER_EEVEE"),
        frame_start=101,
        frame_end=244,
        object_count=4,
        mesh_count=1,
        has_camera=True,
    )

    assert _runner()._assign([placeholder], 2) == []


def test_plan_matches_the_p0005_benchmark():
    plan = RenderCapacityCalculator().plan(
        [_shot()],
        target_hours=1,
        gpu_profile="rtx_3090",
        price_per_hour=0.15,
    )

    assert plan.required_nodes == 2
    assert plan.total_frames == 96
    assert plan.total_gpu_seconds == 3888
    assert plan.estimated_wall_seconds < 3600
    assert plan.estimated_cost < 0.5
