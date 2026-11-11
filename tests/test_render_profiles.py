"""Unit tests for the measured render profile store."""

from src.infrastructure.render.profiles import RenderProfileStore


def test_profile_round_trip(tmp_path):
    path = tmp_path / "render_profiles.json"
    store = RenderProfileStore(path)
    store.set(
        "pro/shots/sq010/sh010/sh010-layout.blend",
        "rtx_3090",
        "CYCLES|1920x1080|256|1",
        40.5,
        blend_hash="abc",
        gpu_label="RTX 3090",
    )
    store.save()

    reloaded = RenderProfileStore(path)
    assert (
        reloaded.get(
            "pro/shots/sq010/sh010/sh010-layout.blend",
            "rtx_3090",
            "CYCLES|1920x1080|256|1",
            blend_hash="abc",
        )
        == 40.5
    )


def test_profile_is_invalidated_when_the_blend_changes(tmp_path):
    store = RenderProfileStore(tmp_path / "render_profiles.json")
    store.set("shot.blend", "rtx_3090", "CYCLES|1920x1080|256|1", 40.5, blend_hash="old")

    assert (
        store.get(
            "shot.blend",
            "rtx_3090",
            "CYCLES|1920x1080|256|1",
            blend_hash="new",
        )
        is None
    )


def test_missing_profile_returns_none(tmp_path):
    store = RenderProfileStore(tmp_path / "render_profiles.json")
    assert store.get("shot.blend", "rtx_3090", "CYCLES|1920x1080|256|1") is None


def test_profile_entry_includes_metadata_and_keeps_local_references_separate(
    tmp_path,
):
    store = RenderProfileStore(tmp_path / "render_profiles.json")
    store.set("shot.blend", "rtx_3080", "CYCLES|1920x1080|128|1", 25.0)
    store.set("shot.blend", "local", "CYCLES|1920x1080|128|1", 160.0)

    remote = store.entry("shot.blend", "rtx_3080", "CYCLES|1920x1080|128|1")
    local = store.entry("shot.blend", "local", "CYCLES|1920x1080|128|1")

    assert remote is not None and remote["seconds"] == 25.0
    assert local is not None and local["seconds"] == 160.0
    assert store.get("shot.blend", "rtx_3080", "CYCLES|1920x1080|128|1") == 25.0
