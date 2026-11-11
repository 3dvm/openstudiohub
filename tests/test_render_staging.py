"""Tests for the Vast staging manifest (no instances are created)."""

from src.infrastructure.render.staging import (
    STAGING_EXCLUDES,
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
