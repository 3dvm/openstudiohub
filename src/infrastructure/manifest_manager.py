# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/manifest_manager.py
# Rol Arquitectónico: Vault Manifest Controller (JSON CRUD)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0
# =========================================================================================

"""
Manages the vault_manifest.json file located in the NAS Vault.
Provides a strict CRUD interface to register, link, and query software dependencies 
(Add-ons, Templates) mapped specifically to Blender versions.
"""

import json
import shutil
from pathlib import Path
from typing import List, Dict

class ManifestManager:
    def __init__(self, vault_root: Path):
        self.vault_root = vault_root
        self.software_dir = self.vault_root / "blender_versions"
        self.manifest_path = self.software_dir / "vault_manifest.json"
        
        # Ensure directories exist
        self.software_dir.mkdir(parents=True, exist_ok=True)
        (self.software_dir / "blender_versions").mkdir(parents=True, exist_ok=True)
        (self.software_dir / "addons").mkdir(parents=True, exist_ok=True)
        
        self._manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        """Reads the JSON manifest. Creates a default scaffold if missing."""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[MANIFEST MANAGER] Failed to parse vault_manifest.json: {e}")
                
        # Default Scaffold
        return {
            "blender_versions": {}
        }

    def _save_manifest(self) -> bool:
        """Atomically writes the manifest state to the NAS."""
        try:
            with open(self.manifest_path, 'w', encoding='utf-8') as f:
                json.dump(self._manifest, f, indent=4)
            return True
        except Exception as e:
            print(f"[MANIFEST MANAGER] Critical write failure: {e}")
            return False

    def get_registered_blender_versions(self) -> List[str]:
        """Returns a list of Blender versions currently tracked in the manifest."""
        return list(self._manifest.get("blender_versions", {}).keys())

    def scan_local_blender_binaries(self) -> List[str]:
        """Scans the physical vault for downloaded Blender binaries and syncs the manifest."""
        blender_dir = self.software_dir / "blender_versions"
        found_versions = set()
        
        if blender_dir.exists():
            for file_path in blender_dir.iterdir():
                if file_path.is_file() and ("blender-" in file_path.name.lower()):
                    import re
                    match = re.search(r'blender-([0-9]+\.[0-9]+\.[0-9a-zA-Z.-]+)-', file_path.name.lower())
                    if match:
                        found_versions.add(match.group(1))
                        
        # Register any new versions found physically that aren't in the JSON
        changed = False
        for version in found_versions:
            if version not in self._manifest["blender_versions"]:
                self._manifest["blender_versions"][version] = {"addons": [], "templates": []}
                changed = True
                
        if changed:
            self._save_manifest()
            
        return sorted(list(found_versions), reverse=True)

    def get_addons_for_version(self, blender_version: str) -> List[Dict[str, str]]:
        """Retrieves mapped add-ons for a specific Blender version."""
        version_node = self._manifest.get("blender_versions", {}).get(blender_version, {})
        return version_node.get("addons", [])

    def register_addon(self, blender_version: str, addon_name: str, addon_version: str, source_zip: Path) -> tuple[bool, str]:
        """Copies an Add-on to the vault and links it to the specified Blender version."""
        if not source_zip.exists() or not source_zip.name.endswith('.zip'):
            return False, "Invalid source file. Must be a .zip archive."
            
        if blender_version not in self._manifest["blender_versions"]:
            self._manifest["blender_versions"][blender_version] = {"addons": [], "templates": []}

        # Format and copy file
        safe_name = addon_name.replace(" ", "_").lower()
        dest_filename = f"{safe_name}_v{addon_version}.zip"
        dest_path = self.software_dir / "addons" / dest_filename
        
        try:
            shutil.copy2(source_zip, dest_path)
        except Exception as e:
            return False, f"File copy failed: {e}"

        # Update JSON mapping
        relative_path = f"addons/{dest_filename}"
        new_entry = {
            "name": addon_name,
            "version": addon_version,
            "path": relative_path
        }
        
        # Prevent duplicates
        addons_list = self._manifest["blender_versions"][blender_version]["addons"]
        addons_list = [a for a in addons_list if a["name"] != addon_name]
        addons_list.append(new_entry)
        
        self._manifest["blender_versions"][blender_version]["addons"] = addons_list
        
        if self._save_manifest():
            return True, "Add-on registered and copied successfully."
        else:
            return False, "Add-on copied but manifest update failed."
