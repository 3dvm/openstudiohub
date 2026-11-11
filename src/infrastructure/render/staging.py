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


@dataclass(frozen=True)
class StagingPlan:
    """Everything the node needs before rendering."""

    entries: tuple[StagingEntry, ...] = field(default_factory=tuple)
    files: int = 0
    bytes: int = 0
    exists: bool = False

    @property
    def summary(self) -> str:
        return (
            f"Uploading {self.files:,} file(s) · {format_bytes(self.bytes)} "
            "to the node"
        )


def _is_excluded(name: str, patterns=STAGING_EXCLUDES) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _scan_folder(root: Path) -> tuple[int, int]:
    files = 0
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if _is_excluded(entry.name):
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


def scan_staging(
    project_root: Path | str,
    production_folder: str,
    *,
    work_root: str = "/root/openstudio",
) -> StagingPlan:
    """Scan the production folder with the same rules as the rsync upload."""
    production_folder = str(production_folder or "").strip()
    if not production_folder:
        return StagingPlan()
    local = Path(project_root) / production_folder
    if not local.is_dir():
        return StagingPlan()
    files, size = _scan_folder(local)
    entry = StagingEntry(
        label=production_folder,
        local_path=local,
        remote_path=f"{work_root.rstrip('/')}/{production_folder}",
        files=files,
        bytes=size,
    )
    return StagingPlan(entries=(entry,), files=files, bytes=size, exists=True)
