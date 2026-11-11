"""Tests for the node-side geometry bake policy."""

from dataclasses import replace
from pathlib import Path

from src.domain.render.bakes import (
    DEFAULT_GN_BAKE_MIN_CPU_RAM_GB,
    bake_geometry_nodes_effective,
    min_cpu_ram_gb_effective,
)
from src.domain.render.models import (
    GeometryBakeInfo,
    RenderQuality,
    RenderSettings,
    RenderShot,
)


def _shot(*, local_cache=False, stale=False, bakes=True):
    return RenderShot(
        name="sh040",
        blend_path=Path("/project/sh040.blend"),
        relative_path="pro/shots/sq010/sh040/sh040-layout.blend",
        sequence="sq010",
        quality=RenderQuality(),
        frame_start=1,
        frame_end=2,
        geometry_bakes=(
            (
                GeometryBakeInfo(
                    object_name="seeds_host",
                    local_cache=local_cache,
                    cache_stale=stale,
                ),
            )
            if bakes
            else ()
        ),
    )


def test_bake_checkbox_follows_the_local_cache_state():
    assert bake_geometry_nodes_effective(RenderSettings(), [_shot()]) is True
    assert bake_geometry_nodes_effective(RenderSettings(), [_shot(local_cache=True)]) is False
    assert (
        bake_geometry_nodes_effective(
            RenderSettings(), [_shot(local_cache=True, stale=True)]
        )
        is True
    )


def test_explicit_bake_setting_wins():
    assert (
        bake_geometry_nodes_effective(
            RenderSettings(bake_geometry_nodes=False), [_shot()]
        )
        is False
    )


def test_node_bake_auto_raises_the_ram_floor():
    settings = RenderSettings()
    shots = [_shot(local_cache=True, stale=True)]

    assert (
        min_cpu_ram_gb_effective(settings, shots)
        == DEFAULT_GN_BAKE_MIN_CPU_RAM_GB
    )
    assert min_cpu_ram_gb_effective(settings, [_shot(local_cache=True)]) == 0.0
    assert min_cpu_ram_gb_effective(settings, [_shot(bakes=False)]) == 0.0


def test_configured_ram_floor_wins():
    settings = RenderSettings(min_cpu_ram_gb=32.0)

    assert min_cpu_ram_gb_effective(settings, [_shot()]) == 32.0


def test_bake_off_keeps_the_ram_floor_at_zero():
    settings = RenderSettings(bake_geometry_nodes=False)

    assert min_cpu_ram_gb_effective(settings, [_shot()]) == 0.0
