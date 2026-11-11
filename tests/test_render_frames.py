"""Tests for benchmark frame selection from the scene range."""

from pathlib import Path

from src.domain.render.frames import (
    benchmark_frames,
    representative_frames,
    scene_frames,
)
from src.domain.render.models import RenderQuality, RenderShot


def _shot(frame_start=401, frame_end=732, frame_step=1):
    return RenderShot(
        name="sh040",
        blend_path=Path("/project/sh040-layout.blend"),
        relative_path="pro/shots/sq010/sh040/sh040-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=128),
        frame_start=frame_start,
        frame_end=frame_end,
        frame_step=frame_step,
        object_count=20,
        mesh_count=10,
        has_camera=True,
    )


def test_representative_frames_keeps_small_sets_intact():
    assert representative_frames([10, 11]) == [10, 11]
    assert representative_frames([]) == []
    assert representative_frames([9, 3, 5]) == [3, 5, 9]


def test_scene_frames_honors_the_scene_step():
    assert scene_frames(_shot(1, 10, 2)) == (1, 3, 5, 7, 9)


def test_benchmark_uses_the_scene_range_when_nothing_is_approved():
    selection = benchmark_frames(_shot())

    assert selection.frames == (401, 567, 732)
    assert selection.range_start == 401
    assert selection.range_end == 732
    assert selection.save_to_render is True


def test_benchmark_skips_approved_frames_inside_the_scene_range():
    selection = benchmark_frames(_shot(), approved={401})

    assert selection.pending[0] == 402
    assert selection.pending[-1] == 732
    assert selection.frames == (402, 567, 732)
    assert 401 not in selection.frames


def test_fully_approved_shot_samples_the_whole_scene_range():
    selection = benchmark_frames(_shot(101, 110), approved=set(range(101, 111)))

    assert selection.pending == ()
    assert selection.frames == (101, 106, 110)
    assert selection.save_to_render is False
    assert selection.from_pending is False


def test_benchmark_selection_follows_the_scene_range_not_the_shot_length():
    selection = benchmark_frames(_shot(1001, 1032))

    assert selection.frames[0] == 1001
    assert selection.frames[-1] == 1032
    assert selection.range_start == 1001
    assert selection.range_end == 1032
