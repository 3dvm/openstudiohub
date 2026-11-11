"""Unit tests for benchmark frame selection and render-folder output."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from src.domain.render.models import RenderQuality, RenderSettings, RenderShot
from src.interfaces.qt.workers.render_workers import (
    RenderBenchmarkWorker,
    _representative_frames,
)


class FakeFrameState:
    def __init__(self, approved):
        self.approved = set(approved)

    def approved_frames(self):
        return set(self.approved)


class FakeRunner:
    def __init__(self):
        self.shots = []

    def run(self, shots, plan, progress=None):
        self.shots = list(plan.shots)
        for shot in self.shots:
            if progress is not None:
                progress(
                    SimpleNamespace(
                        stage="frame",
                        message=json.dumps(
                            {"frame": shot.frame_start, "seconds": 40.0}
                        ),
                        shot=shot.name,
                    )
                )
        return SimpleNamespace(ok=True, message="benchmark ok")


class FakeService:
    def __init__(self, approved):
        self.approved = set(approved)
        self.output_root = None
        self.plan_shots = []
        self.measurements = []
        self.runner = FakeRunner()

    def frame_state_store(self, _root, _shot, _task_type="render"):
        return FakeFrameState(self.approved)

    def plan(self, _root, *, shots, **_kwargs):
        self.plan_shots = list(shots)
        return SimpleNamespace(
            shots=tuple(shots), required_nodes=1, estimated_cost=0.0
        )

    def benchmark_estimate(
        self, _root, shot, *, gpu_profile="rtx_3090", price_per_hour=0.0, budget=0.0
    ):
        from src.domain.render.frames import benchmark_frames

        selection = benchmark_frames(shot, self.approved)
        shots = [
            replace(
                shot,
                frame_start=frame,
                frame_end=frame,
                frame_step=1,
                measured_seconds=None,
                measurement_stale=False,
            )
            for frame in selection.frames
        ]
        self.plan_shots = list(shots)
        return SimpleNamespace(
            selection=selection,
            plan=SimpleNamespace(
                shots=tuple(shots),
                required_nodes=1,
                estimated_cost=0.0,
                gpu_profile=gpu_profile,
            ),
            staging=SimpleNamespace(bytes=0, files=0, entries=()),
        )

    def render_root(self, root):
        return Path(root) / "03_render"

    def build_burst_runner(self, _root, _plan, *, output_root=None, **_kwargs):
        self.output_root = Path(output_root)
        return self.runner

    def record_measurement(
        self, _root, shot, gpu_profile, seconds, *, gpu_label=""
    ):
        self.measurements.append((shot.name, gpu_profile, seconds, gpu_label))


def _shot() -> RenderShot:
    return RenderShot(
        name="sh010",
        blend_path=Path("/project/sh010.blend"),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=128),
        frame_start=101,
        frame_end=110,
        object_count=20,
        mesh_count=10,
        has_camera=True,
    )


def _settings() -> RenderSettings:
    return RenderSettings(gpu_profile="rtx_3080", max_price_per_hour=0.2)


def _offer():
    return SimpleNamespace(price_per_hour=0.2, gpu_name="RTX 3080")


def test_representative_frames_sample_the_pending_range():
    assert _representative_frames(range(101, 111)) == [101, 106, 110]
    assert _representative_frames([104]) == [104]
    assert _representative_frames([]) == []


def test_benchmark_writes_pending_frames_to_the_render_folder(tmp_path):
    service = FakeService(approved={101, 102})
    worker = RenderBenchmarkWorker(
        service, tmp_path, _shot(), _settings(), _offer()
    )
    finished = []
    worker.benchmark_finished.connect(
        lambda name, median: finished.append((name, median))
    )

    worker.run()

    assert service.output_root == tmp_path / "03_render"
    planned_frames = sorted(shot.frame_start for shot in service.plan_shots)
    assert planned_frames == [103, 107, 110]
    assert all(shot.frame_start == shot.frame_end for shot in service.plan_shots)
    assert service.measurements == [("sh010", "rtx_3080", 40.0, "RTX 3080")]
    assert finished and finished[0][0] == "sh010"


def test_fully_approved_shot_benchmarks_into_the_temp_folder(tmp_path):
    service = FakeService(approved=set(range(101, 111)))
    worker = RenderBenchmarkWorker(
        service, tmp_path, _shot(), _settings(), _offer()
    )

    worker.run()

    assert service.output_root is not None
    assert ".benchmarks" in service.output_root.parts
    assert sorted(shot.frame_start for shot in service.plan_shots) == [101, 106, 110]
    assert service.measurements == [("sh010", "rtx_3080", 40.0, "RTX 3080")]
