"""Tests for the local render scan cache and probe serialization."""

import json
from pathlib import Path

from src.domain.render.models import (
    FileOutputInfo,
    RenderSetup,
    ViewLayerInfo,
)
from src.infrastructure.render.probe import RenderProbeResult
from src.infrastructure.render.scan_cache import (
    CachedProbe,
    RenderScanCache,
    SCAN_CACHE_SCHEMA,
)


def _probe_result() -> RenderProbeResult:
    setup = RenderSetup(
        use_nodes=True,
        compositing_enabled=True,
        compositor_name="Comp",
        view_layers=(
            ViewLayerInfo(
                name="ViewLayer",
                enabled=True,
                render_layers_node="RL",
                connected_to_output=True,
                samples=64,
            ),
        ),
        file_outputs=(
            FileOutputInfo(
                name="Output",
                base_path="//out",
                file_format="PNG",
                layer="ViewLayer",
            ),
        ),
        output_format="PNG",
        color_mode="RGBA",
        color_depth="8",
        view_transform="AgX",
        look="None",
        camera="Camera",
        fps=24.0,
        film_transparent=False,
        motion_blur=False,
        denoise=True,
        use_sequencer=False,
    )
    return RenderProbeResult(
        engine="CYCLES",
        resolution_x=1920,
        resolution_y=1080,
        resolution_percentage=100,
        samples=128,
        denoise=True,
        frame_start=401,
        frame_end=732,
        frame_step=1,
        object_count=120,
        mesh_count=110,
        library_count=2,
        geometry_node_objects=3,
        has_camera=True,
        libraries=("//asset.blend",),
        images=("//tex.png",),
        output_path="//out",
        file_format="PNG",
        setup=setup,
    )


def test_probe_result_survives_a_dict_roundtrip():
    result = _probe_result()

    restored = RenderProbeResult.from_dict(result.to_dict())

    assert restored == result


def test_scan_cache_roundtrip(tmp_path):
    cache = RenderScanCache(tmp_path / "local" / "render_scan_cache.json")
    entries = {
        "pro/shots/sq010/a/a-layout.blend": CachedProbe(
            size=10,
            mtime_ns=20,
            blend_hash="abc",
            probe=_probe_result().to_dict(),
            task_type="layout",
            task_id="task-1",
        )
    }

    cache.save(entries, blender_version="5.2.3")
    loaded = cache.load()

    assert loaded.blender_version == "5.2.3"
    assert loaded.entries.keys() == entries.keys()
    entry = loaded.entries["pro/shots/sq010/a/a-layout.blend"]
    assert entry.size == 10
    assert entry.task_type == "layout"
    assert entry.task_id == "task-1"
    assert RenderProbeResult.from_dict(entry.probe) == _probe_result()


def test_scan_cache_ignores_other_schemas_and_garbage(tmp_path):
    path = tmp_path / "render_scan_cache.json"
    path.write_text(
        json.dumps({"schema": SCAN_CACHE_SCHEMA + 1, "files": {}}),
        encoding="utf-8",
    )
    assert RenderScanCache(path).load().entries == {}

    path.write_text("not json", encoding="utf-8")
    assert RenderScanCache(path).load().entries == {}


def test_scan_cache_for_project_uses_the_local_folder(tmp_path):
    cache = RenderScanCache.for_project(tmp_path, "06_conf_LOCAL")

    assert cache.path == tmp_path / "06_conf_LOCAL" / "render_scan_cache.json"
