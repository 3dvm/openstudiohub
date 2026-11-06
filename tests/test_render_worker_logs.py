"""Local render worker writes a dedicated Blender log per shot."""

from pathlib import Path

from src.domain.render.models import RenderQuality, RenderSettings, RenderShot
from src.infrastructure.render.local import LocalRenderReport
from src.infrastructure.render.run_audit import RenderRunAuditLogger
from src.interfaces.qt.workers.render_workers import LocalRenderWorker


class FakeRunner:
    def __init__(self) -> None:
        self.log_paths = []

    def render(self, *_args, log_path=None, **_kwargs):
        self.log_paths.append(log_path)
        if log_path is not None:
            Path(log_path).write_text("OSFRAME::{}\n", encoding="utf-8")
        return LocalRenderReport(
            ok=True,
            message="rendered",
            output_dir=Path(_args[3]),
            frames_expected=2,
            frames_rendered=2,
            seconds=(1.0, 1.0),
            missing=(),
        )


class FakeService:
    def __init__(self, output_dir: Path, runner: FakeRunner) -> None:
        self.output_dir = output_dir
        self.runner = runner

    def shot_output_dir(self, _root, _shot, _task_type="render"):
        return self.output_dir

    def local_runner(self, _root):
        return self.runner


def _shot() -> RenderShot:
    return RenderShot(
        name="sh010",
        blend_path=Path("/project/sh010.blend"),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=128),
        frame_start=101,
        frame_end=102,
        object_count=20,
        mesh_count=10,
        has_camera=True,
    )


def test_local_worker_writes_blender_log_and_node_summary(qapp, tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    runner = FakeRunner()
    logger = RenderRunAuditLogger(tmp_path / "audit" / "render_runs.jsonl")
    worker = LocalRenderWorker(
        FakeService(output, runner),
        tmp_path,
        [_shot()],
        RenderSettings(task_type="render"),
        audit=logger,
        run_id="rlocal",
    )

    worker.run()

    assert runner.log_paths and runner.log_paths[0] is not None
    assert Path(runner.log_paths[0]).name == "node-local-sh010-blender.log"
    assert logger.node_log_path("rlocal", "local-sh010").is_file()
    assert (logger.run_dir("rlocal") / "node-local-sh010.json").is_file()
