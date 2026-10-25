"""Unit tests for the Blender binary locator."""

from pathlib import Path

import pytest

from src.infrastructure.sandbox.blender_locator import BlenderLocator


def _make_archive(build_dir: Path, version: str = "5.2.0") -> Path:
    root = build_dir / BlenderLocator.archive_folder_name(version)
    exe = root / BlenderLocator.relative_executable()
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    return exe


def test_resolve_returns_archive_root_executable(tmp_path):
    build_dir = tmp_path / "blender-build"
    expected = _make_archive(build_dir)

    # A decoy directory named "blender" nested inside the archive used to win
    # the old `sorted(glob("**/blender"))[0]` selection.
    decoy = (
        build_dir
        / BlenderLocator.archive_folder_name("5.2.0")
        / "5.2"
        / "scripts"
        / "addons_core"
        / "io_scene_gltf2"
        / "blender"
    )
    decoy.mkdir(parents=True)

    assert BlenderLocator.resolve(build_dir) == expected


def test_resolve_accepts_version(tmp_path):
    build_dir = tmp_path / "blender-build"
    expected = _make_archive(build_dir, "5.2.1")

    assert BlenderLocator.resolve(build_dir, version="5.2.1") == expected


def test_resolve_raises_when_missing(tmp_path):
    build_dir = tmp_path / "blender-build"
    build_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        BlenderLocator.resolve(build_dir)


def test_resolve_raises_when_version_missing(tmp_path):
    build_dir = tmp_path / "blender-build"
    build_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        BlenderLocator.resolve(build_dir, version="9.9.9")
