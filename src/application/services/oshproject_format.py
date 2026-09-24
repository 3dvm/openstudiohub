# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/oshproject_format.py
# Architectural role: Application service / .oshproject format + zip codec
# =========================================================================================

"""Reader/writer for the ``.oshproject`` interchange archive.

An ``.oshproject`` is a versioned ZIP that carries a Kitsu project's production
data (metadata), non-VCS files and, optionally, an embedded SVN dump. It NEVER
contains secrets: no passwords, tokens or SSH keys.

This module is intentionally free of any Kitsu/gazu or business logic: it only
knows how to validate a manifest, stream entries with checksums, and extract
defensively. ``kitsu_export_service``/``kitsu_import_service`` orchestrate it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

FORMAT_VERSION = 1
SUPPORTED_FORMAT_VERSIONS: Tuple[int, ...] = (1,)
ARCHIVE_EXTENSION = ".oshproject"
MANIFEST_NAME = "manifest.json"

# Archive layout (relative to the ZIP root). Kept here so every consumer agrees.
KITSU_DIR = "kitsu"
STUDIO_DIR = "kitsu/studio"
ENTITIES_DIR = "kitsu/entities"
MEDIA_PREVIEWS_DIR = "media/previews"
MEDIA_ATTACHMENTS_DIR = "media/attachments"
FILES_DIR = "files"
VCS_DIR = "vcs"
SVN_DUMP_NAME = "vcs/svn.dump.gz"

_CHUNK = 1 << 20


class ManifestError(Exception):
    """Raised when a manifest is missing, malformed or from an unsupported version."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def human_bytes(value) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def default_archive_name(project_name: str, when: Optional[datetime] = None) -> str:
    """``<folder_name>_<YYYYmmdd>.oshproject`` (folder name is repo-normalized)."""
    folder = (project_name or "project").strip().lower().replace(" ", "-")
    stamp = (when or datetime.now()).strftime("%Y%m%d")
    return f"{folder}_{stamp}{ARCHIVE_EXTENSION}"


def unique_path(path: Path) -> Path:
    """Return ``path`` if free, else a ``_2``, ``_3``... suffixed sibling."""
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def file_size(path: Path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def directory_size(path: Path) -> int:
    """Best-effort recursive size; missing paths count as zero."""
    total = 0
    root = Path(path)
    if not root.exists():
        return 0
    for item in root.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
def build_manifest(
    *,
    project: dict,
    blueprint: dict,
    inclusion: dict,
    vcs: dict,
    counts: dict,
    source_kitsu_url: str = "",
    app_version: str = "",
    exported_at: Optional[str] = None,
    sizes: Optional[dict] = None,
    checksums: Optional[dict] = None,
) -> dict:
    """Assemble the manifest dict. Checksums/sizes are filled by the writer."""
    return {
        "format_version": FORMAT_VERSION,
        "app_version": str(app_version or ""),
        "exported_at": exported_at or datetime.now().isoformat(timespec="seconds"),
        "source_kitsu_url": str(source_kitsu_url or ""),
        "project": dict(project or {}),
        "blueprint": dict(blueprint or {}),
        "inclusion": dict(inclusion or {}),
        "vcs": dict(vcs or {}),
        "counts": dict(counts or {}),
        "sizes": dict(sizes or {}),
        "checksums": dict(checksums or {}),
    }


def validate_manifest(data) -> dict:
    """Validate a parsed manifest defensively and return it."""
    if not isinstance(data, dict):
        raise ManifestError("Manifest is not a JSON object.")

    version = data.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ManifestError("Manifest 'format_version' is missing or not an integer.")
    if version not in SUPPORTED_FORMAT_VERSIONS:
        raise ManifestError(
            f"Unsupported .oshproject format version {version}; "
            f"this Hub supports {SUPPORTED_FORMAT_VERSIONS}."
        )
    if not isinstance(data.get("project"), dict):
        raise ManifestError("Manifest 'project' section is missing or malformed.")
    if not isinstance(data.get("checksums", {}), dict):
        raise ManifestError("Manifest 'checksums' section is malformed.")
    return data


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------
class OshProjectWriter:
    """Streams entries into a temporary ZIP, then atomically renames it.

    Expected usage::

        with OshProjectWriter(dest) as writer:
            writer.add_json("kitsu/project.json", {...})
            writer.add_file("media/previews/x.png", src)
            writer.write_manifest(manifest)   # last entry; injects checksums/sizes
    """

    def __init__(self, archive_path: Path) -> None:
        self.archive_path = Path(archive_path)
        self._temp_path: Optional[Path] = None
        self._zip: Optional[zipfile.ZipFile] = None
        self._entries: List[dict] = []

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "OshProjectWriter":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.abort()

    def open(self) -> None:
        self.archive_path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            dir=str(self.archive_path.parent), suffix=".oshproject.tmp", delete=False
        )
        handle.close()
        self._temp_path = Path(handle.name)
        self._zip = zipfile.ZipFile(
            self._temp_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        )

    # -- entries -----------------------------------------------------------
    def _record(self, arcname: str, size: int, digest: str) -> None:
        self._entries.append({"path": arcname, "size": int(size), "sha256": digest})

    def add_bytes(self, arcname: str, data: bytes) -> None:
        arcname = self._clean(arcname)
        digest = hashlib.sha256(data).hexdigest()
        self._zip.writestr(arcname, data)
        self._record(arcname, len(data), digest)

    def add_json(self, arcname: str, obj) -> None:
        payload = json.dumps(obj, indent=4, ensure_ascii=False, default=str).encode("utf-8")
        self.add_bytes(arcname, payload)

    def add_text(self, arcname: str, text: str) -> None:
        self.add_bytes(arcname, text.encode("utf-8"))

    def add_file(self, arcname: str, source_path: Path, progress: Optional[Callable[[int], None]] = None) -> None:
        arcname = self._clean(arcname)
        source_path = Path(source_path)
        digest = hashlib.sha256()
        size = 0
        with open(source_path, "rb") as source, self._zip.open(arcname, "w", force_zip64=True) as dest:
            while True:
                chunk = source.read(_CHUNK)
                if not chunk:
                    break
                dest.write(chunk)
                digest.update(chunk)
                size += len(chunk)
                if progress is not None:
                    progress(size)
        self._record(arcname, size, digest.hexdigest())

    def add_directory(self, arcname_prefix: str, source_dir: Path, progress=None) -> int:
        """Recursively add ``source_dir`` under ``arcname_prefix``. Returns bytes."""
        source_dir = Path(source_dir)
        if not source_dir.is_dir():
            return 0
        total = 0
        for item in sorted(source_dir.rglob("*")):
            if not item.is_file():
                continue
            relative = item.relative_to(source_dir).as_posix()
            arcname = f"{arcname_prefix.rstrip('/')}/{relative}"
            self.add_file(arcname, item, progress=progress)
            total += file_size(item)
        return total

    def write_manifest(self, manifest: dict) -> dict:
        """Write the manifest with checksums/sizes injected (must be last)."""
        checksums = {entry["path"]: entry["sha256"] for entry in self._entries}
        sizes = self.compute_sizes()
        manifest = dict(manifest)
        manifest["checksums"] = checksums
        manifest["sizes"] = sizes
        self.add_json(MANIFEST_NAME, manifest)
        return manifest

    # -- derived data ------------------------------------------------------
    def entries(self) -> List[dict]:
        return list(self._entries)

    def total_bytes(self) -> int:
        return sum(entry["size"] for entry in self._entries)

    def compute_sizes(self) -> Dict[str, int]:
        """Approximate per-category byte totals (labelled approximate in the UI)."""
        sizes = {
            "kitsu": 0,
            "media_previews": 0,
            "media_attachments": 0,
            "files_pipeline": 0,
            "files_shared": 0,
            "files_other": 0,
            "vcs_dump": 0,
            "manifest": 0,
        }
        for entry in self._entries:
            path = entry["path"]
            if path == MANIFEST_NAME:
                sizes["manifest"] += entry["size"]
            elif path.startswith("media/previews/"):
                sizes["media_previews"] += entry["size"]
            elif path.startswith("media/attachments/"):
                sizes["media_attachments"] += entry["size"]
            elif path.startswith("files/pipeline/"):
                sizes["files_pipeline"] += entry["size"]
            elif path.startswith("files/shared/"):
                sizes["files_shared"] += entry["size"]
            elif path.startswith("files/"):
                sizes["files_other"] += entry["size"]
            elif path.startswith("vcs/"):
                sizes["vcs_dump"] += entry["size"]
            else:
                sizes["kitsu"] += entry["size"]
        sizes["total"] = sum(sizes.values())
        sizes["approximate"] = True
        return sizes

    # -- finalization ------------------------------------------------------
    def commit(self) -> Path:
        if self._zip is not None:
            self._zip.close()
            self._zip = None
        if self._temp_path is not None:
            os.replace(self._temp_path, self.archive_path)
            self._temp_path = None
        return self.archive_path

    def abort(self) -> None:
        try:
            if self._zip is not None:
                self._zip.close()
        except Exception:  # noqa: BLE001
            pass
        self._zip = None
        if self._temp_path is not None:
            try:
                self._temp_path.unlink()
            except OSError:
                pass
            self._temp_path = None

    @staticmethod
    def _clean(arcname: str) -> str:
        arcname = str(arcname).replace("\\", "/").lstrip("/")
        if ".." in Path(arcname).parts:
            raise ValueError(f"Illegal archive path: {arcname}")
        return arcname


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------
class OshProjectReader:
    """Defensive ``.oshproject`` reader (validation + safe extraction)."""

    def __init__(self, archive_path: Path) -> None:
        self.archive_path = Path(archive_path)
        self._zip = zipfile.ZipFile(self.archive_path, "r")
        self._manifest: Optional[dict] = None

    def __enter__(self) -> "OshProjectReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._zip.close()
        except Exception:  # noqa: BLE001
            pass

    # -- manifest ----------------------------------------------------------
    def read_manifest(self) -> dict:
        if self._manifest is not None:
            return self._manifest
        try:
            raw = self._zip.read(MANIFEST_NAME)
        except KeyError as error:
            raise ManifestError("This file is not a valid .oshproject (missing manifest.json).") from error
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise ManifestError(f"Manifest is not valid JSON: {error}") from error
        self._manifest = validate_manifest(data)
        return self._manifest

    def names(self) -> List[str]:
        return self._zip.namelist()

    def has_entry(self, arcname: str) -> bool:
        return arcname in self._zip.namelist()

    # -- checksums ---------------------------------------------------------
    def verify_checksums(self, progress: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, List[str]]:
        manifest = self.read_manifest()
        expected = manifest.get("checksums") or {}
        mismatches: List[str] = []
        total = len(expected)
        for index, (arcname, digest) in enumerate(expected.items(), start=1):
            if not self.has_entry(arcname):
                mismatches.append(arcname)
                continue
            actual = hashlib.sha256()
            with self._zip.open(arcname, "r") as handle:
                for chunk in iter(lambda: handle.read(_CHUNK), b""):
                    actual.update(chunk)
            if actual.hexdigest() != digest:
                mismatches.append(arcname)
            if progress is not None:
                progress(index, total)
        return (not mismatches), mismatches

    def read_json(self, arcname: str):
        try:
            return json.loads(self._zip.read(arcname).decode("utf-8"))
        except KeyError:
            return None

    # -- extraction --------------------------------------------------------
    def safe_members(self) -> Iterable[zipfile.ZipInfo]:
        root = Path(self.archive_path).resolve().parent
        for info in self._zip.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise ManifestError(f"Archive contains an unsafe path: {info.filename}")
            yield info

    def extract_to(self, dest_dir: Path, progress: Optional[Callable[[str], None]] = None) -> Path:
        """Extract every member into ``dest_dir`` (created if needed)."""
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        root = dest_dir.resolve()
        for info in self.safe_members():
            member = (dest_dir / info.filename).resolve()
            if not str(member).startswith(str(root)):
                raise ManifestError(f"Archive member escapes destination: {info.filename}")
            self._zip.extract(info, dest_dir)
            if progress is not None:
                progress(info.filename)
        return dest_dir

    def extract_entry_to_temp(self, arcname: str) -> Path:
        """Extract a single member to a temp file and return its path."""
        handle = tempfile.NamedTemporaryFile(delete=False)
        try:
            with self._zip.open(arcname, "r") as source:
                shutil.copyfileobj(source, handle)
        finally:
            handle.close()
        return Path(handle.name)


# ---------------------------------------------------------------------------
# gzip helpers for the embedded SVN dump
# ---------------------------------------------------------------------------
def gzip_path(source_path: Path, dest_path: Path, progress: Optional[Callable[[int], None]] = None) -> Path:
    """Stream-compress ``source_path`` into ``dest_path`` (atomic on completion)."""
    source_path = Path(source_path)
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp = dest_path.with_suffix(dest_path.suffix + ".tmp")
    written = 0
    with open(source_path, "rb") as source, gzip.open(temp, "wb") as dest:
        while True:
            chunk = source.read(_CHUNK)
            if not chunk:
                break
            dest.write(chunk)
            written += len(chunk)
            if progress is not None:
                progress(written)
    os.replace(temp, dest_path)
    return dest_path


def gunzip_path(source_path: Path, dest_path: Path, progress: Optional[Callable[[int], None]] = None) -> Path:
    """Stream-decompress ``source_path`` into ``dest_path`` (atomic on completion)."""
    source_path = Path(source_path)
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp = dest_path.with_suffix(dest_path.suffix + ".tmp")
    written = 0
    with gzip.open(source_path, "rb") as source, open(temp, "wb") as dest:
        while True:
            chunk = source.read(_CHUNK)
            if not chunk:
                break
            dest.write(chunk)
            written += len(chunk)
            if progress is not None:
                progress(written)
    os.replace(temp, dest_path)
    return dest_path
