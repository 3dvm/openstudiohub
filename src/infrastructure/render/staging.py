# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/staging.py
# Architectural role: Render infrastructure / Vast staging manifest
# =========================================================================================

"""Measure what a Vast burst uploads before it starts.

Only the production folder (``topography.vfs_svn``) is staged: briefs and the
shared folder are not required to render. The scan mirrors the rsync excludes so
the advertised size matches what is actually transferred.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from src.domain.render.formatting import format_bytes

STAGING_EXCLUDES = (
    ".svn",
    "*.blend1",
    "*.blend2",
    "*.crash.txt",
    "__pycache__",
)


@dataclass(frozen=True)
class StagingEntry:
    """One local folder uploaded to the node."""

    label: str
    local_path: Path
    remote_path: str
    files: int = 0
    bytes: int = 0
    single_file: bool = False


@dataclass(frozen=True)
class StagingFile:
    """One exact file expected on the node, with its local digest."""

    relative_path: str
    bytes: int
    sha256: str = ""


@dataclass(frozen=True)
class StagingPlan:
    """Everything the node needs before rendering."""

    entries: tuple[StagingEntry, ...] = field(default_factory=tuple)
    files: int = 0
    bytes: int = 0
    exists: bool = False
    images: tuple[tuple[str, int], ...] = ()
    manifest: tuple[StagingFile, ...] = ()

    @property
    def summary(self) -> str:
        return (
            f"Uploading {self.files:,} file(s) · {format_bytes(self.bytes)} "
            "to the node"
        )


def bake_cache_names(shots) -> tuple[str, ...]:
    """Return the cache directory names produced by geometry-node bakes."""
    names: set[str] = set()
    for shot in shots or ():
        for bake in getattr(shot, "geometry_bakes", ()) or ():
            name = getattr(bake, "cache_dir_name", "")
            if name:
                names.add(str(name))
    return tuple(sorted(names))


def _is_excluded(name: str, patterns=STAGING_EXCLUDES, exclude_names=()) -> bool:
    if name in exclude_names:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


_IMAGE_SUFFIXES = (
    ".exr",
    ".hdr",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".tx",
    ".rat",
)


def _scan_folder(root: Path, exclude_names=()) -> tuple[int, int]:
    files = 0
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if _is_excluded(entry.name, exclude_names=exclude_names):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            files += 1
                            total += int(entry.stat(follow_symlinks=False).st_size)
                    except OSError:
                        continue
        except OSError:
            continue
    return files, total


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _collect_files(
    root: Path,
    *,
    exclude_names=(),
    relative_to: Path | None = None,
) -> list[StagingFile]:
    files: list[StagingFile] = []
    base = relative_to or root
    if root.is_file():
        try:
            size = int(root.stat().st_size)
        except OSError:
            return []
        try:
            label = root.relative_to(base).as_posix()
        except ValueError:
            label = root.name
        return [
            StagingFile(
                relative_path=label,
                bytes=size,
                sha256=_sha256(root),
            )
        ]
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if _is_excluded(entry.name, exclude_names=exclude_names):
                        continue
                    try:
                        path = Path(entry.path)
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            size = int(entry.stat(follow_symlinks=False).st_size)
                            try:
                                label = path.relative_to(base).as_posix()
                            except ValueError:
                                label = path.name
                            files.append(
                                StagingFile(
                                    relative_path=label,
                                    bytes=size,
                                    sha256=_sha256(path),
                                )
                            )
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(files, key=lambda item: item.relative_path)


def _collect_images(
    root: Path,
    *,
    exclude_names=(),
    relative_to: Path | None = None,
) -> list[tuple[str, int]]:
    images: list[tuple[str, int]] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if _is_excluded(entry.name, exclude_names=exclude_names):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            path = Path(entry.path)
                            if path.suffix.lower() not in _IMAGE_SUFFIXES:
                                continue
                            base = relative_to or root
                            try:
                                label = path.relative_to(base).as_posix()
                            except ValueError:
                                label = path.name
                            images.append((label, int(entry.stat().st_size)))
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(images)


def scan_staging(
    project_root: Path | str,
    production_folder: str,
    *,
    work_root: str = "/root/openstudio",
    exclude_names=(),
) -> StagingPlan:
    """Scan the whole production folder with the rsync exclude rules."""
    production_folder = str(production_folder or "").strip()
    if not production_folder:
        return StagingPlan()
    local = Path(project_root) / production_folder
    if not local.is_dir():
        return StagingPlan()
    exclude_names = tuple(str(name) for name in exclude_names or () if name)
    files, size = _scan_folder(local, exclude_names=exclude_names)
    images = _collect_images(local, exclude_names=exclude_names)
    manifest = _collect_files(local, exclude_names=exclude_names)
    entry = StagingEntry(
        label=production_folder,
        local_path=local,
        remote_path=f"{work_root.rstrip('/')}/{production_folder}",
        files=files,
        bytes=size,
    )
    return StagingPlan(
        entries=(entry,),
        files=files,
        bytes=size,
        exists=True,
        images=tuple(images),
        manifest=tuple(manifest),
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _merge_roots(roots: list[Path]) -> list[Path]:
    """Drop roots already covered by a parent root."""
    ordered = sorted({path.resolve() for path in roots}, key=lambda item: len(str(item)))
    kept: list[Path] = []
    for root in ordered:
        if any(_inside(root, parent) for parent in kept):
            continue
        kept.append(root)
    return kept


def scan_staging_for_shots(
    project_root: Path | str,
    production_folder: str,
    shots,
    *,
    work_root: str = "/root/openstudio",
    exclude_names=(),
) -> StagingPlan:
    """Stage only the selected shots, project assets and their dependencies.

    The production folder can be much larger than the files a node needs: other
    shots, their bake caches and unrelated assets do not have to be uploaded.
    """
    production_folder = str(production_folder or "").strip()
    if not production_folder:
        return StagingPlan()
    project = Path(project_root)
    local = project / production_folder
    if not local.is_dir():
        return StagingPlan()
    targets = list(shots or ())
    if not targets:
        return scan_staging(
            project_root,
            production_folder,
            work_root=work_root,
            exclude_names=exclude_names,
        )
    roots: list[Path] = []
    for shot in targets:
        blend = Path(getattr(shot, "blend_path", "") or "")
        if blend and _inside(blend.parent, local):
            roots.append(blend.parent)
    needs_asset_fallback = False
    dependency_files: list[Path] = []
    for shot in targets:
        dependencies = tuple(getattr(shot, "dependencies", ()) or ())
        if not dependencies and int(getattr(shot, "library_count", 0) or 0) > 0:
            needs_asset_fallback = True
        for dependency in dependencies:
            path = project / str(dependency)
            if path.is_file() and _inside(path, local):
                dependency_files.append(path)
    if needs_asset_fallback:
        assets = local / "pro" / "assets"
        if assets.is_dir():
            roots.append(assets)
    roots = _merge_roots(roots)
    if not roots and not dependency_files:
        return scan_staging(
            project_root,
            production_folder,
            work_root=work_root,
            exclude_names=exclude_names,
        )
    exclude_names = tuple(str(name) for name in exclude_names or () if name)
    entries: list[StagingEntry] = []
    images: list[tuple[str, int]] = []
    manifest: list[StagingFile] = []
    total_files = 0
    total_bytes = 0
    for root in roots:
        files, size = _scan_folder(root, exclude_names=exclude_names)
        images.extend(
            _collect_images(
                root,
                exclude_names=exclude_names,
                relative_to=local,
            )
        )
        manifest.extend(
            _collect_files(
                root,
                exclude_names=exclude_names,
                relative_to=local,
            )
        )
        relative = root.relative_to(local.resolve()).as_posix()
        entries.append(
            StagingEntry(
                label=relative,
                local_path=root,
                remote_path=(
                    f"{work_root.rstrip('/')}/{production_folder}/{relative}"
                ),
                files=files,
                bytes=size,
            )
        )
        total_files += files
        total_bytes += size
    single_files: dict[str, Path] = {}
    for path in dependency_files:
        resolved = path.resolve()
        if any(_inside(resolved, root) for root in roots):
            continue
        try:
            relative = resolved.relative_to(local.resolve()).as_posix()
        except ValueError:
            continue
        single_files.setdefault(relative, resolved)
    for relative, path in sorted(single_files.items()):
        try:
            size = int(path.stat().st_size)
        except OSError:
            continue
        entries.append(
            StagingEntry(
                label=relative,
                local_path=path,
                remote_path=(
                    f"{work_root.rstrip('/')}/{production_folder}/{relative}"
                ),
                files=1,
                bytes=size,
                single_file=True,
            )
        )
        total_files += 1
        total_bytes += size
        if path.suffix.lower() in _IMAGE_SUFFIXES:
            images.append((relative, size))
        manifest.extend(
            _collect_files(
                path,
                exclude_names=exclude_names,
                relative_to=local,
            )
        )
    return StagingPlan(
        entries=tuple(entries),
        files=total_files,
        bytes=total_bytes,
        exists=True,
        images=tuple(sorted(images)),
        manifest=tuple(sorted(manifest, key=lambda item: item.relative_path)),
    )
