# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/vault/integrity.py
# Architectural role: Vault domain service / manifest integrity audit
# =========================================================================================

"""Vault manifest integrity audit.

Reconciles the *declared* software inventory (``vault_manifest.json``) against
the *actual* assets on disk, so the settings UI can surface drift and offer
safe repairs (register downloaded Blender versions, re-download missing
assets, drop dead entries...).

This module is pure: it only reads the filesystem and the in-memory manifest
mapping. Applying fixes to the manifest is done through the small helpers at
the bottom; downloading/re-packaging is orchestrated by the UI layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .addon import parse_zip

BINARY_EXTENSIONS = ("tar.xz", "tar.bz2", "zip", "dmg")

_BINARY_RE = re.compile(
    r"^blender-(\d+(?:\.\d+)+)-([a-z]+)-([a-z0-9_]+)\.(tar\.xz|tar\.bz2|zip|dmg)$",
    re.IGNORECASE,
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_COMPACT_RE = re.compile(r"[^a-z0-9]+")
_VERSION_SUFFIX_RE = re.compile(r"[-_ ]?v?\d+(?:\.\d+)*$", re.IGNORECASE)

# Local add-ons that are packaged from a source folder rather than downloaded.
LOCAL_PACKAGED_ADDONS = {"openstudio_toolkit"}


def slugify(name: str) -> str:
    return _SLUG_RE.sub("_", (name or "").strip().lower()).strip("_")


def _compact(name: str) -> str:
    return _COMPACT_RE.sub("", (name or "").strip().lower())


def _filename_keys(filename: str) -> set:
    """Match keys for an archive filename, ignoring its trailing version."""
    stem = _VERSION_SUFFIX_RE.sub("", Path(filename).stem)
    return _name_keys(stem)


def _name_keys(value: str) -> set:
    """Both snake_case and compact match keys (``contact_sheet``/``contactsheet``)."""
    return {key for key in (slugify(value), _compact(value)) if key}


def parse_binary_filename(filename: str) -> Optional[Dict[str, str]]:
    """Parse ``blender-<version>-<os>-<arch>.<ext>`` into its parts."""
    match = _BINARY_RE.match(filename or "")
    if not match:
        return None
    version, os_name, arch, ext = match.groups()
    return {"version": version, "os": os_name.lower(), "arch": arch.lower(), "ext": ext.lower()}


def base_version(version: str) -> str:
    """Return the Blender.org release folder fragment (``5.2.1`` -> ``5.2``)."""
    parts = [p for p in str(version).split(".") if p]
    return ".".join(parts[:2]) if len(parts) >= 2 else str(version)


@dataclass(frozen=True)
class BinaryAsset:
    version: str
    os: str
    arch: str
    ext: str
    filename: str
    path: Path
    size: int


@dataclass(frozen=True)
class AddonAsset:
    name: str
    version: str
    filename: str
    path: Path
    valid: bool
    description: str = ""


@dataclass
class VaultIntegrityReport:
    vault_root: Path
    registered_versions: List[str] = field(default_factory=list)
    disk_binaries: List[BinaryAsset] = field(default_factory=list)
    addon_files: List[AddonAsset] = field(default_factory=list)
    template_dirs: List[str] = field(default_factory=list)

    # Binaries
    unregistered_binaries: List[BinaryAsset] = field(default_factory=list)
    missing_binaries: List[str] = field(default_factory=list)
    misplaced_binaries: List[Path] = field(default_factory=list)

    # Add-ons / templates
    orphan_addons: List[AddonAsset] = field(default_factory=list)
    missing_addon_files: List[Tuple[str, str, str]] = field(default_factory=list)
    addon_version_mismatches: List[Tuple[str, str, str, str]] = field(default_factory=list)
    broken_requires: List[Tuple[str, str, str]] = field(default_factory=list)
    invalid_addon_files: List[AddonAsset] = field(default_factory=list)
    missing_templates: List[Tuple[str, str]] = field(default_factory=list)
    orphan_templates: List[str] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return any(
            (
                self.unregistered_binaries,
                self.missing_binaries,
                self.misplaced_binaries,
                self.orphan_addons,
                self.missing_addon_files,
                self.addon_version_mismatches,
                self.broken_requires,
                self.invalid_addon_files,
                self.missing_templates,
                self.orphan_templates,
            )
        )

    @property
    def fixable_count(self) -> int:
        """Number of findings the UI can repair automatically/with one click."""
        return (
            len(self.unregistered_binaries)
            + len([v for v in self.missing_binaries])  # re-download or delete
            + len(self.misplaced_binaries)
            + len(self.missing_addon_files)
            + len(self.addon_version_mismatches)
        )

    def summary(self) -> str:
        return (
            f"{len(self.registered_versions)} versions · "
            f"{len(self.disk_binaries)} binaries · "
            f"{len(self.addon_files)} add-on archives · "
            f"{self.fixable_count} fixable / "
            f"{len(self.missing_templates) + len(self.orphan_templates) + len(self.broken_requires) + len(self.orphan_addons)} to review"
        )


class VaultIntegrityAuditor:
    def __init__(self, vault_root: Path) -> None:
        self.vault_root = Path(vault_root)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    @property
    def binaries_dir(self) -> Path:
        return self.vault_root / "blender_versions"

    @property
    def addons_dir(self) -> Path:
        return self.vault_root / "addons"

    @property
    def templates_dir(self) -> Path:
        return self.vault_root / "project_templates"

    def _scan_binaries(self) -> List[BinaryAsset]:
        assets: List[BinaryAsset] = []
        if not self.binaries_dir.exists():
            return assets
        for path in sorted(self.binaries_dir.iterdir()):
            if not path.is_file():
                continue
            info = parse_binary_filename(path.name)
            if not info:
                continue
            assets.append(
                BinaryAsset(
                    version=info["version"],
                    os=info["os"],
                    arch=info["arch"],
                    ext=info["ext"],
                    filename=path.name,
                    path=path,
                    size=path.stat().st_size,
                )
            )
        return assets

    def _scan_misplaced_binaries(self) -> List[Path]:
        misplaced: List[Path] = []
        if not self.vault_root.exists():
            return misplaced
        for path in sorted(self.vault_root.iterdir()):
            if path.is_file() and parse_binary_filename(path.name):
                misplaced.append(path)
        return misplaced

    def _scan_addons(self) -> List[AddonAsset]:
        assets: List[AddonAsset] = []
        if not self.addons_dir.exists():
            return assets
        for path in sorted(self.addons_dir.rglob("*.zip")):
            if not path.is_file():
                continue
            meta = parse_zip(path)
            assets.append(
                AddonAsset(
                    name=meta.name,
                    version=meta.version,
                    filename=path.name,
                    path=path,
                    valid=meta.is_valid,
                    description=meta.description,
                )
            )
        return assets

    def _scan_template_dirs(self) -> List[str]:
        if not self.templates_dir.exists():
            return []
        return sorted(d.name for d in self.templates_dir.iterdir() if d.is_dir())

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def audit(self, manifest_versions: Dict[str, Any]) -> VaultIntegrityReport:
        manifest_versions = manifest_versions or {}
        registered = list(manifest_versions.keys())

        report = VaultIntegrityReport(vault_root=self.vault_root, registered_versions=registered)
        report.disk_binaries = self._scan_binaries()
        report.misplaced_binaries = self._scan_misplaced_binaries()
        report.addon_files = self._scan_addons()
        report.template_dirs = self._scan_template_dirs()

        self._audit_binaries(report)
        self._audit_addons(report, manifest_versions)
        self._audit_templates(report, manifest_versions)
        return report

    def _audit_binaries(self, report: VaultIntegrityReport) -> None:
        disk_versions = {asset.version for asset in report.disk_binaries}
        registered = set(report.registered_versions)

        report.unregistered_binaries = [
            asset for asset in report.disk_binaries if asset.version not in registered
        ]
        report.missing_binaries = [
            version for version in report.registered_versions if version not in disk_versions
        ]

    def _audit_addons(self, report: VaultIntegrityReport, manifest_versions: Dict[str, Any]) -> None:
        by_key: Dict[str, List[AddonAsset]] = {}
        for asset in report.addon_files:
            for key in _name_keys(asset.name) | _filename_keys(asset.filename):
                by_key.setdefault(key, []).append(asset)

        referenced_paths: set = set()

        for version, categories in manifest_versions.items():
            if not isinstance(categories, dict):
                continue
            addons = categories.get("addons")
            if not isinstance(addons, dict):
                continue

            version_keys: set = set()
            for addon_name in addons:
                version_keys |= _name_keys(addon_name)

            for name, entry in addons.items():
                if not isinstance(entry, dict):
                    continue

                matched: Optional[AddonAsset] = None
                ref_path = entry.get("path")
                if ref_path:
                    candidate = self.vault_root / str(ref_path)
                    if candidate.exists():
                        referenced_paths.add(candidate)
                        matched = next((a for a in report.addon_files if a.path == candidate), None)

                if matched is None:
                    lookup_keys = _name_keys(name)
                    if ref_path:
                        lookup_keys |= _filename_keys(Path(ref_path).name)
                    for key in lookup_keys:
                        candidates = by_key.get(key)
                        if candidates:
                            matched = candidates[0]
                            referenced_paths.add(matched.path)
                            break

                if matched is None:
                    report.missing_addon_files.append((version, name, str(ref_path or "")))
                    continue

                manifest_v = entry.get("version")
                if manifest_v and matched.version and str(manifest_v) != str(matched.version):
                    report.addon_version_mismatches.append(
                        (version, name, str(manifest_v), str(matched.version))
                    )

                for requirement in entry.get("requires") or []:
                    if requirement not in addons and not (_name_keys(requirement) & version_keys):
                        report.broken_requires.append((version, name, str(requirement)))

        report.orphan_addons = [
            asset for asset in report.addon_files if asset.path not in referenced_paths
        ]
        report.invalid_addon_files = [asset for asset in report.addon_files if not asset.valid]

    def _audit_templates(self, report: VaultIntegrityReport, manifest_versions: Dict[str, Any]) -> None:
        dirs = set(report.template_dirs)
        referenced: set = set()

        for version, categories in manifest_versions.items():
            if not isinstance(categories, dict):
                continue
            templates = categories.get("templates")
            if not isinstance(templates, dict):
                continue

            for name, entry in templates.items():
                if name in dirs:
                    referenced.add(name)
                    continue
                entry_path = entry.get("path") if isinstance(entry, dict) else None
                if entry_path and (self.vault_root / str(entry_path)).exists():
                    referenced.add(name)
                    continue
                report.missing_templates.append((version, name))

        report.orphan_templates = sorted(d for d in dirs if d not in referenced)


# ----------------------------------------------------------------------
# Fix helpers (mutate the in-memory ``{version: {categories}}`` mapping)
# ----------------------------------------------------------------------
def register_disk_versions(manifest_versions: Dict[str, Any], report: VaultIntegrityReport) -> List[str]:
    """Add every unregistered downloaded Blender version to the manifest."""
    added: List[str] = []
    for asset in report.unregistered_binaries:
        if asset.version not in manifest_versions:
            manifest_versions[asset.version] = {"addons": {}, "templates": {}}
            added.append(asset.version)
    return added


def remove_version(manifest_versions: Dict[str, Any], version: str) -> bool:
    if version in manifest_versions:
        del manifest_versions[version]
        return True
    return False
