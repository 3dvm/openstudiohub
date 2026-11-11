# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/scan_cache.py
# Architectural role: Render infrastructure / shot scan cache
# =========================================================================================

"""Persist probe results so the render panel opens without re-running Blender.

The cache lives inside the project's local folder (``vfs_local``) so it survives
sessions and stays out of the SVN working copy. Each entry stores the file
signature (size, mtime and blend hash) plus the probe payload; the scan reuses
an entry only while the signature and Blender version still match.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCAN_CACHE_FILENAME = "render_scan_cache.json"
SCAN_CACHE_SCHEMA = 1


@dataclass(frozen=True)
class CachedProbe:
    size: int
    mtime_ns: int
    blend_hash: str
    probe: dict
    task_type: str = ""
    task_id: str = ""

    def to_dict(self) -> dict:
        return {
            "size": int(self.size),
            "mtime_ns": int(self.mtime_ns),
            "blend_hash": self.blend_hash,
            "probe": self.probe,
            "task_type": self.task_type,
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CachedProbe":
        probe = data.get("probe")
        if not isinstance(probe, dict):
            raise ValueError("invalid probe payload")
        return cls(
            size=int(data.get("size") or 0),
            mtime_ns=int(data.get("mtime_ns") or 0),
            blend_hash=str(data.get("blend_hash") or ""),
            probe=probe,
            task_type=str(data.get("task_type") or ""),
            task_id=str(data.get("task_id") or ""),
        )


@dataclass
class ScanCacheData:
    entries: dict[str, CachedProbe] = field(default_factory=dict)
    blender_version: str = ""
    generated_at: str = ""


class RenderScanCache:
    """Read and write ``render_scan_cache.json`` for one project."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @classmethod
    def for_project(cls, project_root: Path | str, vfs_local: str) -> "RenderScanCache":
        folder = str(vfs_local or "").strip() or "local"
        return cls(Path(project_root) / folder / SCAN_CACHE_FILENAME)

    def load(self) -> ScanCacheData:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ScanCacheData()
        if not isinstance(data, dict):
            return ScanCacheData()
        if int(data.get("schema") or 0) != SCAN_CACHE_SCHEMA:
            return ScanCacheData()
        raw_files = data.get("files")
        if not isinstance(raw_files, dict):
            return ScanCacheData()
        entries: dict[str, CachedProbe] = {}
        for relative_path, payload in raw_files.items():
            if not isinstance(payload, dict):
                continue
            try:
                entries[str(relative_path)] = CachedProbe.from_dict(payload)
            except (TypeError, ValueError):
                continue
        return ScanCacheData(
            entries=entries,
            blender_version=str(data.get("blender_version") or ""),
            generated_at=str(data.get("generated_at") or ""),
        )

    def save(self, entries: dict[str, CachedProbe], *, blender_version: str) -> None:
        payload = {
            "schema": SCAN_CACHE_SCHEMA,
            "blender_version": str(blender_version or ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "files": {
                relative_path: entry.to_dict()
                for relative_path, entry in sorted(entries.items())
            },
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError:
            return
