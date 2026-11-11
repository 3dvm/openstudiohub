"""Tests for task-filtered scans and the Blender probe cache."""

import json
from pathlib import Path

from src.application.services.render_service import RenderService
from src.domain.render.models import RenderSetup
from src.infrastructure.render.probe import BlenderProbe, RenderProbeResult


def _probe_result() -> RenderProbeResult:
    return RenderProbeResult(
        engine="CYCLES",
        resolution_x=1920,
        resolution_y=1080,
        resolution_percentage=100,
        samples=128,
        denoise=True,
        frame_start=101,
        frame_end=110,
        frame_step=1,
        object_count=120,
        mesh_count=110,
        library_count=0,
        geometry_node_objects=0,
        has_camera=True,
        libraries=(),
        images=(),
        output_path="//out",
        file_format="PNG",
        setup=RenderSetup(
            use_nodes=True,
            compositing_enabled=True,
            compositor_name="Comp",
            output_format="PNG",
            color_mode="RGBA",
            color_depth="8",
            view_transform="AgX",
            look="None",
            camera="Camera",
            fps=24.0,
        ),
    )


def _project(tmp_path: Path) -> Path:
    pipeline = tmp_path / "pipeline"
    pipeline.mkdir()
    (pipeline / "project_init.json").write_text(
        json.dumps(
            {
                "project_name": "p",
                "blender_version": "5.2.3",
                "topography_signature": {
                    "vfs_svn": "svn",
                    "vfs_shared": "shared",
                    "vfs_local": "local",
                    "vfs_pipeline": "pipeline",
                },
            }
        ),
        encoding="utf-8",
    )
    shots = tmp_path / "svn" / "pro" / "shots" / "sq010"
    (shots / "a").mkdir(parents=True)
    (shots / "b").mkdir(parents=True)
    (shots / "a" / "a-layout.blend").write_bytes(b"a" * 10)
    (shots / "b" / "b-comp.blend").write_bytes(b"b" * 10)
    return tmp_path


def _service(monkeypatch) -> RenderService:
    service = RenderService()
    monkeypatch.setattr(
        service,
        "resolve_blender",
        lambda root, blueprint: Path("/bin/true"),
    )
    return service


def test_scan_filters_by_task_and_reuses_the_cache(tmp_path, monkeypatch):
    project = _project(tmp_path)
    service = _service(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        BlenderProbe,
        "probe",
        lambda self, path: calls.append(str(path)) or _probe_result(),
    )
    task_files = {
        "pro/shots/sq010/a/a-layout.blend": {
            "task_type": "layout",
            "task_id": "task-1",
        }
    }

    first = service.scan_shots(project, task_files=task_files)

    assert [shot.name for shot in first] == ["a"]
    assert first[0].task_type == "layout"
    assert first[0].task_id == "task-1"
    assert len(calls) == 1
    assert (project / "local" / "render_scan_cache.json").is_file()

    second = service.scan_shots(project, task_files=task_files)

    assert len(calls) == 1
    assert [shot.relative_path for shot in second] == [
        shot.relative_path for shot in first
    ]

    cached = service.cached_shots(project)

    assert cached is not None
    assert [shot.name for shot in cached] == ["a"]
    assert cached[0].task_type == "layout"
    assert len(calls) == 1


def test_scan_reprobes_changed_files_and_honors_force(tmp_path, monkeypatch):
    project = _project(tmp_path)
    service = _service(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        BlenderProbe,
        "probe",
        lambda self, path: calls.append(str(path)) or _probe_result(),
    )
    task_files = {
        "pro/shots/sq010/a/a-layout.blend": {"task_type": "layout"},
    }
    service.scan_shots(project, task_files=task_files)
    assert len(calls) == 1

    blend = project / "svn" / "pro" / "shots" / "sq010" / "a" / "a-layout.blend"
    blend.write_bytes(b"changed" * 20)
    service.scan_shots(project, task_files=task_files)
    assert len(calls) == 2

    service.scan_shots(project, task_files=task_files, force=True)
    assert len(calls) == 3


def test_scan_without_tasks_is_empty_and_keeps_the_cache(tmp_path, monkeypatch):
    project = _project(tmp_path)
    service = _service(monkeypatch)
    monkeypatch.setattr(
        BlenderProbe,
        "probe",
        lambda self, path: _probe_result(),
    )
    task_files = {
        "pro/shots/sq010/a/a-layout.blend": {"task_type": "layout"},
    }
    service.scan_shots(project, task_files=task_files)

    shots = service.scan_shots(project, task_files={}, save_cache=False)

    assert shots == []
    cached = service.cached_shots(project)
    assert cached is not None
    assert [shot.name for shot in cached] == ["a"]
