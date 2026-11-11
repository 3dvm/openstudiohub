# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/render/frames.py
# Architectural role: Render domain / benchmark frame selection
# =========================================================================================

"""Frame selection for benchmarks.

A benchmark measures representative frames of the shot's *scene* range, which is
read from the ``.blend`` by the probe. Frames already approved are skipped so a
benchmark never overwrites reviewed work; when every frame is approved the
selection falls back to the whole scene range and the frames are written to the
temporary ``.benchmarks`` folder instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.render.models import RenderShot


@dataclass(frozen=True)
class BenchmarkFrameSelection:
    """Frames chosen by a benchmark and the scene range they came from."""

    frames: tuple[int, ...]
    range_start: int
    range_end: int
    step: int
    pending: tuple[int, ...]

    @property
    def from_pending(self) -> bool:
        return bool(self.frames) and bool(self.pending)

    @property
    def save_to_render(self) -> bool:
        return bool(self.pending)


def representative_frames(frames, limit: int = 3) -> list[int]:
    """Pick up to ``limit`` representative frames from an ordered frame set."""
    ordered = sorted({int(frame) for frame in frames or ()})
    if not ordered:
        return []
    if len(ordered) <= limit:
        return ordered
    middle = len(ordered) // 2
    if limit == 1:
        return [ordered[middle]]
    if limit == 2:
        return [ordered[0], ordered[-1]]
    return sorted({ordered[0], ordered[middle], ordered[-1]})


def scene_frames(shot: RenderShot) -> tuple[int, ...]:
    """Every frame in the shot's scene range, honoring its scene step."""
    if shot.frame_end < shot.frame_start:
        return ()
    step = max(1, int(shot.frame_step or 1))
    return tuple(range(int(shot.frame_start), int(shot.frame_end) + 1, step))


def benchmark_frames(
    shot: RenderShot,
    approved=(),
) -> BenchmarkFrameSelection:
    """Choose the frames a benchmark will measure from the scene range."""
    frames = scene_frames(shot)
    approved_set = {int(frame) for frame in approved or ()}
    pending = tuple(frame for frame in frames if frame not in approved_set)
    chosen = representative_frames(pending)
    if not chosen:
        chosen = representative_frames(frames)
    return BenchmarkFrameSelection(
        frames=tuple(chosen),
        range_start=int(shot.frame_start),
        range_end=int(shot.frame_end),
        step=max(1, int(shot.frame_step or 1)),
        pending=pending,
    )
