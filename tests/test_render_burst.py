"""Unit tests for direct Vast burst planning (no instances are created)."""

from dataclasses import replace
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


def test_assign_skips_existing_and_approved_frames(tmp_path):
    from src.infrastructure.render.frame_state import RenderFrameStateStore

    shot = _shot("sh010", frames=10, start=101)
    output_root = tmp_path / "03_render"
    output = output_root / "shots" / "sq010" / "sh010.render"
    output.mkdir(parents=True)
    (output / "frame_0101.png").write_bytes(b"x")
    RenderFrameStateStore(output).approve(102)
    runner = RenderBurstRunner(
        FakeProvider(),
        project_root=tmp_path,
        output_root=output_root,
        ssh_key_path=Path("/tmp/key"),
        production_folder="02_archivos_de_produccion",
        blender_version="5.2.3",
        skip_existing=True,
    )

    assignments = runner._assign([shot], 1)

    assert [task.frames for task in assignments[0]] == [(103, 104, 105, 106, 107, 108, 109, 110)]



def test_runner_has_no_canary_and_audits_nodes_individually(tmp_path):
    from src.infrastructure.render.burst import NodeResult
    from src.infrastructure.render.run_audit import RenderRunAuditLogger

    audit = RenderRunAuditLogger(tmp_path / "audit" / "render_runs.jsonl")
    runner = RenderBurstRunner(
        FakeProvider(),
        project_root=tmp_path,
        output_root=tmp_path / "03_render",
        ssh_key_path=Path("/tmp/key"),
        production_folder="02_archivos_de_produccion",
        blender_version="5.2.3",
        audit=audit,
        run_id="rnode",
    )
    result = NodeResult(
        node=2,
        instance_id=55,
        ok=True,
        message="completed",
        frames_done=10,
        frames_expected=10,
        wall_seconds=1.0,
        cost=0.01,
        stage="validate",
        gpu_name="RTX 4090",
        region="US",
        price_per_hour=0.5,
        duration_ms=1000,
    )

    assert not hasattr(runner, "canary")
    runner._write_node_summary(2, result)

    summary = audit.run_dir("rnode") / "node-2.json"
    assert summary.is_file()
    assert '"gpu_name": "RTX 4090"' in summary.read_text(encoding="utf-8")


def test_remote_logs_and_diagnostics_are_saved_before_destroy(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    from src.infrastructure.render.run_audit import RenderRunAuditLogger

    audit = RenderRunAuditLogger(tmp_path / "audit" / "render_runs.jsonl")
    runner = RenderBurstRunner(
        FakeProvider(),
        project_root=tmp_path,
        output_root=tmp_path / "03_render",
        ssh_key_path=Path("/tmp/key"),
        production_folder="02_archivos_de_produccion",
        blender_version="5.2.3",
        audit=audit,
        run_id="rremote",
    )

    def fake_ssh(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, "blender output\n", "")

    monkeypatch.setattr(runner, "_ssh", fake_ssh)

    runner._capture_remote_artifacts(
        SimpleNamespace(), 1, ["/root/openstudio-render-1-sh010.log"]
    )

    run_dir = audit.run_dir("rremote")
    assert (run_dir / "node-1-remote-openstudio-render-1-sh010.log").is_file()
    assert (run_dir / "node-1-diagnostics.log").is_file()


def test_failed_boot_reports_every_assigned_frame_as_missing(tmp_path):
    from types import SimpleNamespace

    from src.infrastructure.render.burst import BurstTask

    class FailingProvider:
        def create_instance(self, *_args, **_kwargs):
            raise RuntimeError("instance disappeared")

    shot = _shot("sh010", frames=4, start=101)
    runner = RenderBurstRunner(
        FailingProvider(),
        project_root=tmp_path,
        output_root=tmp_path / "03_render",
        ssh_key_path=Path("/tmp/key"),
        production_folder="02_archivos_de_produccion",
        blender_version="5.2.3",
    )
    task = BurstTask(shot=shot, frames=(101, 102), output_subdir="shots/sq010/sh010.render")
    offer = SimpleNamespace(
        id=1,
        gpu_name="RTX 3090",
        geolocation="US",
        price_per_hour=0.4,
    )

    result = runner._run_node(0, [task], offer, None)

    assert result.ok is False
    assert result.missing == (101, 102)


def test_assign_skips_approved_frames_without_retry(tmp_path):
    from src.infrastructure.render.frame_state import RenderFrameStateStore

    shot = _shot("sh010", frames=10, start=101)
    output_root = tmp_path / "03_render"
    output = output_root / "shots" / "sq010" / "sh010.render"
    output.mkdir(parents=True)
    state = RenderFrameStateStore(output)
    state.approve(102)
    state.approve(105)
    runner = RenderBurstRunner(
        FakeProvider(),
        project_root=tmp_path,
        output_root=output_root,
        ssh_key_path=Path("/tmp/key"),
        production_folder="02_archivos_de_produccion",
        blender_version="5.2.3",
        skip_existing=False,
    )

    assignments = runner._assign([shot], 1)

    assert [task.frames for task in assignments[0]] == [
        (101, 103, 104, 106, 107, 108, 109, 110)
    ]


def test_assign_keeps_existing_unapproved_frames_without_retry(tmp_path):
    shot = _shot("sh010", frames=10, start=101)
    output_root = tmp_path / "03_render"
    output = output_root / "shots" / "sq010" / "sh010.render"
    output.mkdir(parents=True)
    (output / "frame_0101.png").write_bytes(b"x")
    runner = RenderBurstRunner(
        FakeProvider(),
        project_root=tmp_path,
        output_root=output_root,
        ssh_key_path=Path("/tmp/key"),
        production_folder="02_archivos_de_produccion",
        blender_version="5.2.3",
        skip_existing=False,
    )

    assignments = runner._assign([shot], 1)

    assert [task.frames for task in assignments[0]] == [
        tuple(range(101, 111))
    ]


def test_render_script_flushes_progress_markers():
    from src.infrastructure.render.burst import _RENDER_SCRIPT

    lines = _RENDER_SCRIPT.splitlines()
    for index, line in enumerate(lines):
        if "OSFRAME::" in line or "OSDEVICES::" in line or "OSBAKE::" in line:
            window = "\n".join(lines[index : index + 12])
            assert "flush=True" in window, line


def test_assign_keeps_whole_shots_on_one_node_each():
    first = _shot("070", frames=10, start=101)
    second = _shot("sh020", frames=10, start=101)
    first = replace(first, measured_seconds=40.0)
    second = replace(second, measured_seconds=40.0)

    assignments = _runner()._assign([first, second], 2)

    assert len(assignments) == 2
    by_shot = {
        task.shot.name: task.frames
        for tasks in assignments
        for task in tasks
    }
    assert by_shot["070"] == tuple(range(101, 111))
    assert by_shot["sh020"] == tuple(range(101, 111))
    assert all(len(tasks) == 1 for tasks in assignments)


def test_assign_does_not_split_a_shot_that_fits_one_instance():
    from types import SimpleNamespace

    shot = replace(_shot("070", frames=20, start=101), measured_seconds=40.0)
    plan = SimpleNamespace(
        target_seconds=3600.0,
        setup_seconds=600.0,
        utilization=0.85,
    )

    assignments = _runner()._assign([shot], 2, plan)

    assert len(assignments[0]) == 1
    assert assignments[0][0].frames == tuple(range(101, 121))
    assert assignments[1] == []


def test_assign_splits_a_shot_that_exceeds_one_instance():
    from types import SimpleNamespace

    shot = replace(_shot("070", frames=100, start=101), measured_seconds=40.0)
    plan = SimpleNamespace(
        target_seconds=3600.0,
        setup_seconds=600.0,
        utilization=0.85,
    )

    assignments = _runner()._assign([shot], 2, plan)

    assert [len(tasks[0].frames) for tasks in assignments] == [50, 50]
    assert assignments[0][0].frames[0] == 101
    assert assignments[1][0].frames[0] == 151


def test_parse_rsync_progress_reads_the_percentage():
    from src.infrastructure.render.burst import _parse_rsync_progress

    assert (
        _parse_rsync_progress(" 36,759,344,911  45%   12.34MB/s    0:01:02")
        == 45
    )
    assert _parse_rsync_progress(" 1,234,567 100%   1.00GB/s    0:00:36") == 100
    assert _parse_rsync_progress("sent 123 bytes  received 45 bytes") is None
    assert _parse_rsync_progress("") is None


def test_tasks_can_use_a_per_shot_output_root(tmp_path):
    shot = _shot("sh010")
    runner = RenderBurstRunner(
        FakeProvider(),
        project_root=Path("/project"),
        output_root=Path("/project/03_render"),
        ssh_key_path=Path("/tmp/key"),
        production_folder="02_archivos_de_produccion",
        blender_version="5.2.3",
        output_roots={shot.relative_path: tmp_path / "benchmarks"},
    )

    task = runner._task(shot, [101])

    assert task.output_root == tmp_path / "benchmarks"


def test_variants_of_one_shot_get_distinct_remote_outputs():
    first = replace(
        _shot("sh040"),
        relative_path="pro/shots/sq010/sh040/sh040-layout.blend",
        blend_path=Path("/project/pro/shots/sq010/sh040/sh040-layout.blend"),
    )
    second = replace(
        _shot("sh040"),
        relative_path="pro/shots/sq010/sh040/sh040-layout_seeds-v7.blend",
        blend_path=Path(
            "/project/pro/shots/sq010/sh040/sh040-layout_seeds-v7.blend"
        ),
    )
    runner = _runner()

    first_task = runner._task(first, [101])
    second_task = runner._task(second, [101])

    assert first_task.output_subdir == second_task.output_subdir
    assert first_task.remote_output_subdir != second_task.remote_output_subdir


def test_rsync_timeout_scales_with_the_upload_size():
    from src.infrastructure.render.burst import _rsync_timeout

    assert _rsync_timeout(0) == 1800.0
    assert _rsync_timeout(400_000_000) == 1800.0
    assert _rsync_timeout(9_400_000_000) == 9400.0


def test_render_script_contains_the_geometry_bake_step():
    from src.infrastructure.render.burst import _RENDER_SCRIPT

    assert "simulation_nodes_cache_bake" in _RENDER_SCRIPT
    assert "bake_geometry_nodes" in _RENDER_SCRIPT
    assert "OSBAKE::gn:start" in _RENDER_SCRIPT


def test_bake_cache_names_only_returns_blendcache_directories():
    from src.domain.render.models import GeometryBakeInfo
    from src.infrastructure.render.staging import bake_cache_names

    shot = replace(
        _shot("sh040"),
        geometry_bakes=(
            GeometryBakeInfo(object_name="seeds", directory="//blendcache_sh040_seeds"),
            GeometryBakeInfo(object_name="textures", directory="//textures"),
            GeometryBakeInfo(object_name="missing", directory=""),
        ),
    )

    assert bake_cache_names((shot,)) == ("blendcache_sh040_seeds",)


def test_run_does_not_silently_reduce_nodes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import pytest

    from src.infrastructure.render.burst import BurstError, BurstTask

    key = tmp_path / "key"
    key.write_text("key", encoding="utf-8")
    runner = RenderBurstRunner(
        FakeProvider(),
        project_root=tmp_path,
        output_root=tmp_path / "03_render",
        ssh_key_path=key,
        production_folder="02_archivos_de_produccion",
        blender_version="5.2.3",
    )
    shot = _shot()
    task = BurstTask(
        shot=shot,
        frames=(101,),
        output_subdir="shots/sq010/sh010.render",
    )
    monkeypatch.setattr(
        runner,
        "_assign",
        lambda *args, **kwargs: [[task], [task]],
    )
    monkeypatch.setattr(
        runner.provider,
        "choose_offers",
        lambda *args, **kwargs: [SimpleNamespace(id=1, price_per_hour=0.1)],
        raising=False,
    )
    monkeypatch.setattr(runner.provider, "balance", lambda: 10.0, raising=False)
    plan = SimpleNamespace(
        required_nodes=2,
        shots=(shot,),
        gpu_profile="rtx_3080",
        price_per_hour=0.1,
        estimated_cost=0.1,
    )

    with pytest.raises(BurstError, match="Only 1 Vast.ai offer"):
        runner.run([shot], plan)
