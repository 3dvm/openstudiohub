# =====================================================================================
# OPENSTUDIOHUB
# Module: tests/test_oshproject_format.py
# =====================================================================================

"""Unit tests for the .oshproject format/codec (no network)."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.application.services.oshproject_format import (
    FORMAT_VERSION,
    ManifestError,
    OshProjectReader,
    OshProjectWriter,
    build_manifest,
    default_archive_name,
    gzip_path,
    gunzip_path,
    human_bytes,
    unique_path,
    validate_manifest,
)


def _manifest() -> dict:
    return build_manifest(
        project={"name": "Neon"},
        blueprint={"project_name": "Neon", "topography_signature": {"vfs_svn": "svn"}},
        inclusion={"media": True, "shared": False, "embed_svn_dump": False},
        vcs={"server_id": "default", "server_url": "svn://localhost"},
        counts={"tasks": 3},
        source_kitsu_url="http://localhost:8080",
        app_version="0.7.0",
    )


def test_build_and_validate_manifest():
    manifest = _manifest()
    assert manifest["format_version"] == FORMAT_VERSION
    assert validate_manifest(manifest) is manifest


def test_unsupported_format_version_is_rejected():
    manifest = _manifest()
    manifest["format_version"] = 999
    with pytest.raises(ManifestError):
        validate_manifest(manifest)


def test_missing_project_section_is_rejected():
    with pytest.raises(ManifestError):
        validate_manifest({"format_version": 1})


def test_writer_reader_roundtrip_with_checksums(tmp_path: Path):
    archive = tmp_path / "bundle.oshproject"
    with OshProjectWriter(archive) as writer:
        writer.add_json("kitsu/project.json", {"name": "Neon"})
        writer.add_text("files/pipeline/notes.txt", "hello")
        writer.add_bytes("media/previews/1/x.png", b"\x89PNG")
        manifest = writer.write_manifest(_manifest())

    assert archive.exists()
    # The manifest cannot checksum itself: 3 payload entries.
    assert len(manifest["checksums"]) == 3

    with OshProjectReader(archive) as reader:
        read = reader.read_manifest()
        assert read["format_version"] == FORMAT_VERSION
        ok, mismatches = reader.verify_checksums()
        assert ok, mismatches
        assert reader.read_json("kitsu/project.json") == {"name": "Neon"}


def test_writer_computes_categories(tmp_path: Path):
    archive = tmp_path / "bundle.oshproject"
    with OshProjectWriter(archive) as writer:
        writer.add_json("kitsu/project.json", {"name": "Neon"})
        writer.add_bytes("media/previews/1/x.png", b"a" * 10)
        writer.add_bytes("media/attachments/2/y.png", b"b" * 20)
        writer.add_text("files/pipeline/a.txt", "c" * 30)
        writer.add_text("files/shared/b.txt", "d" * 40)
        writer.add_bytes("vcs/svn.dump.gz", b"e" * 50)
        sizes = writer.compute_sizes()
    assert sizes["media_previews"] == 10
    assert sizes["media_attachments"] == 20
    assert sizes["files_pipeline"] == 30
    assert sizes["files_shared"] == 40
    assert sizes["vcs_dump"] == 50
    assert sizes["approximate"] is True
    assert sizes["total"] == sum(sizes[k] for k in sizes if k not in ("total", "approximate"))


def test_checksum_mismatch_detected(tmp_path: Path):
    archive = tmp_path / "bundle.oshproject"
    with OshProjectWriter(archive) as writer:
        writer.add_text("files/pipeline/a.txt", "hello")
        writer.write_manifest(_manifest())

    # Corrupt the stored payload without touching the manifest's checksum.
    import zipfile

    broken = tmp_path / "broken.oshproject"
    with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(broken, "w") as dest:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "files/pipeline/a.txt":
                data = b"tampered"
            dest.writestr(info, data)

    with OshProjectReader(broken) as reader:
        ok, mismatches = reader.verify_checksums()
    assert not ok
    assert "files/pipeline/a.txt" in mismatches


def test_writer_rejects_unsafe_paths(tmp_path: Path):
    archive = tmp_path / "bundle.oshproject"
    with pytest.raises(ValueError):
        with OshProjectWriter(archive) as writer:
            writer.add_bytes("../evil.txt", b"x")


def test_missing_manifest_is_rejected(tmp_path: Path):
    archive = tmp_path / "empty.oshproject"
    with OshProjectWriter(archive) as writer:
        writer.add_text("files/pipeline/a.txt", "hello")

    with OshProjectReader(archive) as reader:
        with pytest.raises(ManifestError):
            reader.read_manifest()


def test_gzip_roundtrip(tmp_path: Path):
    source = tmp_path / "svn.dump"
    source.write_bytes(b"dump-content" * 100)
    gz = gzip_path(source, tmp_path / "svn.dump.gz")
    assert gz.exists()
    out = gunzip_path(gz, tmp_path / "restored.dump")
    assert out.read_bytes() == source.read_bytes()


def test_archive_name_and_unique_path(tmp_path: Path):
    name = default_archive_name("My Project", when=datetime(2026, 9, 23))
    assert name == "my-project_20260923.oshproject"

    existing = tmp_path / "a.oshproject"
    existing.write_text("x")
    assert unique_path(existing).name == "a_2.oshproject"


def test_human_bytes():
    assert human_bytes(0) == "0.0 B"
    assert human_bytes(1536).startswith("1.5")
