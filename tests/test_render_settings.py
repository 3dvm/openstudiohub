"""Unit tests for render setup and shared render settings."""

from pathlib import Path

from src.domain.render.image_formats import IMAGE_FORMATS, image_extension
from src.domain.render.models import (
    RenderQuality,
    RenderSettings,
    RenderSetup,
    RenderShot,
    ViewLayerInfo,
)
from src.infrastructure.render.settings import RenderSettingsStore


def test_render_settings_round_trip(tmp_path):
    store = RenderSettingsStore(tmp_path / "render_settings.json")
    settings = RenderSettings(
        selected_shots=("pro/shots/sq010/sh010/sh010-layout.blend",),
        final_quality=RenderQuality(samples=128),
        gpu_profile="rtx_4090",
        target_hours=2.0,
        render_backend="local",
        preview_backend="local",
        video_task_type="render",
        local_speed_factor=6.0,
    )
    store.save(settings)

    loaded = RenderSettingsStore(store.path).load()

    assert loaded.selected_shots == settings.selected_shots
    assert loaded.final_quality.samples == 128
    assert loaded.gpu_profile == "rtx_4090"
    assert loaded.target_hours == 2.0
    assert loaded.render_backend == "local"
    assert loaded.local_speed_factor == 6.0
    assert loaded.final_quality.file_format == "PNG"


def test_image_formats_cover_blender_still_formats_and_default_png():
    identifiers = {item.identifier for item in IMAGE_FORMATS}

    assert "PNG" in identifiers
    assert "OPEN_EXR" in identifiers
    assert "TIFF" in identifiers
    assert "OPEN_EXR_MULTILAYER" in identifiers
    assert "FFMPEG" not in identifiers
    assert image_extension("OPEN_EXR") == "exr"
    assert image_extension("TIFF") == "tif"


def test_final_quality_round_trips_image_format(tmp_path):
    store = RenderSettingsStore(tmp_path / "render_settings.json")
    settings = RenderSettings(
        final_quality=RenderQuality(
            file_format="OPEN_EXR", color_mode="RGBA", color_depth="32"
        )
    )
    store.save(settings)

    loaded = RenderSettingsStore(store.path).load()

    assert loaded.final_quality.file_format == "OPEN_EXR"
    assert loaded.final_quality.color_mode == "RGBA"
    assert loaded.final_quality.color_depth == "32"


def test_setup_readiness_requires_every_layer_connected():
    setup = RenderSetup(
        use_nodes=True,
        compositing_enabled=True,
        compositor_name="Compositor Nodes",
        view_layers=(
            ViewLayerInfo("BG", connected_to_output=True),
            ViewLayerInfo("dev", connected_to_output=True),
        ),
    )
    assert setup.is_compositing_ready
    assert not setup.writes_per_layer_files

    disconnected = RenderSetup(
        use_nodes=True,
        compositing_enabled=True,
        compositor_name="Compositor Nodes",
        view_layers=(
            ViewLayerInfo("BG", connected_to_output=True),
            ViewLayerInfo("dev", connected_to_output=False),
        ),
    )
    assert not disconnected.is_compositing_ready


def test_shot_with_quality_preserves_setup_and_stale_flag():
    setup = RenderSetup(use_nodes=True, compositing_enabled=True, compositor_name="C")
    shot = RenderShot(
        name="sh010",
        blend_path=Path("/project/sh010.blend"),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=256),
        frame_start=101,
        frame_end=196,
        object_count=639,
        mesh_count=625,
        has_camera=True,
        measured_seconds=40.5,
        measurement_stale=True,
        setup=setup,
    )

    changed = shot.with_quality(RenderQuality(samples=128), measured_seconds=29.5)

    assert changed.quality.samples == 128
    assert changed.measured_seconds == 29.5
    assert changed.measurement_stale is True
    assert changed.setup is setup


def test_preview_frames_round_trip_per_shot(tmp_path):
    store = RenderSettingsStore(tmp_path / "render_settings.json")
    settings = RenderSettings(
        preview_frames=(
            ("pro/shots/sq010/070/070-layout.blend", 150),
            ("pro/shots/sq010/sh020/sh020-layout.blend", 222),
        )
    )
    store.save(settings)

    loaded = RenderSettingsStore(store.path).load()

    assert loaded.preview_frame_for("pro/shots/sq010/070/070-layout.blend") == 150
    assert loaded.preview_frame_for("pro/shots/sq010/sh020/sh020-layout.blend") == 222
    assert loaded.preview_frame_for("missing") is None
