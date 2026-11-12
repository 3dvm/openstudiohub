"""Tests for the Vast staging manifest (no instances are created)."""

from src.infrastructure.render.staging import (
    STAGING_EXCLUDES,
    bake_cache_names,
    scan_staging,
)


def test_scan_staging_skips_rsync_excludes(tmp_path):
    project = tmp_path / "project"
    production = project / "02_archivos_de_produccion"
    (production / "pro" / "shots").mkdir(parents=True)
    (production / "pro" / "shots" / "a.blend").write_bytes(b"x" * 10)
    (production / "pro" / "shots" / "a.blend1").write_bytes(b"y" * 99)
    (production / "pro" / "shots" / "a.crash.txt").write_bytes(b"z" * 50)
    (production / ".svn").mkdir()
    (production / ".svn" / "pristine").write_bytes(b"p" * 70)
    (production / "__pycache__").mkdir()
    (production / "__pycache__" / "cache.pyc").write_bytes(b"c" * 30)
    (production / "pro" / "shots" / "b.png").write_bytes(b"b" * 5)

    plan = scan_staging(project, "02_archivos_de_produccion")

    assert plan.exists
    assert plan.files == 2
    assert plan.bytes == 15
    assert plan.images == (("pro/shots/b.png", 5),)
    manifest = {item.relative_path: item for item in plan.manifest}
    assert "pro/shots/a.blend" in manifest
    assert len(manifest["pro/shots/a.blend"].sha256) == 64
    assert manifest["pro/shots/a.blend"].bytes == 10
    assert plan.entries[0].remote_path == "/root/openstudio/02_archivos_de_produccion"
    assert "2 file(s)" in plan.summary
    assert "15 B" in plan.summary
    assert ".svn" in STAGING_EXCLUDES


def test_scan_staging_reports_missing_production_folder(tmp_path):
    plan = scan_staging(tmp_path, "02_archivos_de_produccion")

    assert not plan.exists
    assert plan.files == 0
    assert plan.bytes == 0
    assert plan.entries == ()


def test_scan_staging_uses_a_custom_work_root(tmp_path):
    production = tmp_path / "svn"
    production.mkdir()
    (production / "file.bin").write_bytes(b"1234")

    plan = scan_staging(tmp_path, "svn", work_root="/opt/openstudio/")

    assert plan.entries[0].remote_path == "/opt/openstudio/svn"


def test_scan_staging_excludes_only_the_given_bake_names(tmp_path):
    from pathlib import Path

    from src.domain.render.models import GeometryBakeInfo, RenderQuality, RenderShot

    project = tmp_path / "project"
    production = project / "svn"
    shot_dir = production / "pro" / "shots" / "sq010" / "sh040"
    shot_dir.mkdir(parents=True)
    (shot_dir / "sh040-layout.blend").write_bytes(b"b" * 10)
    gn_cache = shot_dir / "blendcache_sh040_seeds"
    gn_cache.mkdir()
    (gn_cache / "blob").write_bytes(b"g" * 100)
    particle_cache = shot_dir / "blendcache_sh040_particles"
    particle_cache.mkdir()
    (particle_cache / "cache").write_bytes(b"p" * 50)

    shot = RenderShot(
        name="sh040",
        blend_path=shot_dir / "sh040-layout.blend",
        relative_path="pro/shots/sq010/sh040/sh040-layout.blend",
        sequence="sq010",
        quality=RenderQuality(),
        frame_start=1,
        frame_end=2,
        geometry_bakes=(
            GeometryBakeInfo(
                object_name="seeds_host",
                directory="//blendcache_sh040_seeds",
            ),
        ),
    )

    plan = scan_staging(
        project, "svn", exclude_names=bake_cache_names((shot,))
    )

    assert plan.files == 2
    assert plan.bytes == 60
    assert plan.files == 2


def test_scan_staging_for_shots_skips_unselected_shots(tmp_path):
    from src.domain.render.models import RenderQuality, RenderShot
    from src.infrastructure.render.staging import scan_staging_for_shots

    project = tmp_path / "project"
    production = project / "02_archivos_de_produccion"
    selected = production / "pro" / "shots" / "sq010" / "sh040"
    other = production / "pro" / "shots" / "sq010" / "sh060"
    assets = production / "pro" / "assets"
    selected.mkdir(parents=True)
    other.mkdir(parents=True)
    assets.mkdir(parents=True)
    (selected / "sh040-layout.blend").write_bytes(b"a" * 10)
    (other / "sh060-layout.blend").write_bytes(b"b" * 1000)
    (assets / "asset.blend").write_bytes(b"c" * 20)
    (assets / "asset.blend1").write_bytes(b"d" * 500)
    dependency = production / "pro" / "lib" / "rig.blend"
    dependency.parent.mkdir(parents=True)
    dependency.write_bytes(b"e" * 30)

    shot = RenderShot(
        name="sh040",
        blend_path=selected / "sh040-layout.blend",
        relative_path="pro/shots/sq010/sh040/sh040-layout.blend",
        sequence="sq010",
        quality=RenderQuality(),
        frame_start=1,
        frame_end=2,
        dependencies=(
            "02_archivos_de_produccion/pro/lib/rig.blend",
            "02_archivos_de_produccion/pro/assets/asset.blend",
        ),
    )

    plan = scan_staging_for_shots(
        project, "02_archivos_de_produccion", [shot]
    )

    assert plan.exists
    assert plan.files == 3
    assert plan.bytes == 60
    assert {entry.label for entry in plan.entries} == {
        "pro/assets/asset.blend",
        "pro/lib/rig.blend",
        "pro/shots/sq010/sh040",
    }
    assert sum(1 for entry in plan.entries if entry.single_file) == 2


def test_scan_staging_for_shots_passes_bake_excludes(tmp_path):
    from src.domain.render.models import RenderQuality, RenderShot
    from src.infrastructure.render.staging import scan_staging_for_shots

    project = tmp_path / "project"
    production = project / "svn"
    shot_dir = production / "pro" / "shots" / "sq010" / "sh040"
    shot_dir.mkdir(parents=True)
    (shot_dir / "shot.blend").write_bytes(b"a" * 10)
    cache = shot_dir / "blendcache_seeds"
    cache.mkdir()
    (cache / "blob").write_bytes(b"b" * 100)

    shot = RenderShot(
        name="sh040",
        blend_path=shot_dir / "shot.blend",
        relative_path="pro/shots/sq010/sh040/shot.blend",
        sequence="sq010",
        quality=RenderQuality(),
        frame_start=1,
        frame_end=2,
    )

    plan = scan_staging_for_shots(
        project,
        "svn",
        [shot],
        exclude_names=("blendcache_seeds",),
    )

    assert plan.files == 1
    assert plan.bytes == 10
