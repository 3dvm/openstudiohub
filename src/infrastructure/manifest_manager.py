# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/manifest_manager.py
# Architectural role: Vault manifest manager (facade over VaultManifestRepository)
# =========================================================================================

"""Vault manifest manager (provisioning-side facade).

Uses the same canonical ``VaultManifest`` schema/location as ``VaultManager``,
so programmatic add-on registration (provisioning workers, git packager) writes
into the exact manifest the settings UI reads. Kept as a thin facade so its
existing consumers (``widget_software``, ``provisioning_workers``,
``git_packager``) keep their API.
"""

import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from src.domain.vault.manifest import VaultManifest
from src.infrastructure.vault_manifest_repository import FileVaultManifestRepository


class ManifestManager:
    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root
        self.software_dir = self.vault_root / "blender_versions"
        self.addons_dir = self.vault_root / "addons"
        self._repo = FileVaultManifestRepository(vault_root)
        self._manifest = self._repo.load()

        self.software_dir.mkdir(parents=True, exist_ok=True)
        self.addons_dir.mkdir(parents=True, exist_ok=True)

    @property
    def manifest_path(self) -> Path:
        return self._repo.path()

    def _save(self) -> bool:
        return self._repo.save(self._manifest)

    def get_registered_blender_versions(self) -> List[str]:
        return self._manifest.registered_versions()

    def scan_local_blender_binaries(self) -> List[str]:
        """Scan the canonical blender dir and sync new versions into the manifest."""
        found = set()
        if self.software_dir.exists():
            for file_path in self.software_dir.iterdir():
                if file_path.is_file() and "blender-" in file_path.name.lower():
                    # Capture the numeric version only (e.g. "5.1.2" from
                    # "blender-5.1.2-linux-x64.tar.xz"); the previous regex was
                    # over-greedy and included the OS/arch suffix.
                    match = re.search(r"blender-([0-9]+\.[0-9]+(?:\.[0-9]+)?)", file_path.name.lower())
                    if match:
                        found.add(match.group(1))

        changed = False
        for version in found:
            if version not in self._manifest.versions:
                self._manifest.ensure_version(version)
                changed = True
        if changed:
            self._save()

        return sorted(found, reverse=True)

    def get_addons_for_version(self, blender_version: str) -> List[Dict[str, str]]:
        """Return the addons mapped to a Blender version as a list of dicts."""
        addons = self._manifest.get_addons(blender_version)
        return [
            {
                "name": name,
                "version": entry.get("version", ""),
                "description": entry.get("description", ""),
                "mandatory": entry.get("mandatory", False),
                "requires": entry.get("requires", []),
            }
            for name, entry in addons.items()
        ]

    def register_addon(
        self,
        blender_version: str,
        addon_name: str,
        addon_version: str,
        source_zip: Path,
        description: str = "",
        mandatory: bool = False,
        requires: Optional[List[str]] = None,
    ) -> tuple[bool, str]:
        """Copy an add-on into the vault and link it to a Blender version."""
        if not source_zip.exists() or not source_zip.name.endswith(".zip"):
            return False, "Invalid source file. Must be a .zip archive."

        safe_name = addon_name.replace(" ", "_").lower()
        dest_filename = f"{safe_name}_v{addon_version}.zip"
        dest_path = self.addons_dir / dest_filename

        try:
            shutil.copy2(source_zip, dest_path)
        except Exception as error:  # noqa: BLE001
            return False, f"File copy failed: {error}"

        self._manifest.add_addon(blender_version, addon_name, addon_version, description, mandatory, requires)
        if self._save():
            return True, "Add-on registered and copied successfully."
        return False, "Add-on copied but manifest update failed."
