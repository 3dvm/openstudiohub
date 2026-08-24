# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/addon_parser.py
# Rol Arquitectónico: Add-on Metadata Extractor (Manifest & Legacy Scanner)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0
# =========================================================================================

"""
Scans and parses Blender add-on archives (.zip).
Extracts compatibility metadata by analyzing either the modern 'blender_manifest.toml' 
(Blender 4.2+ extensions) or the legacy 'bl_info' dictionary in '__init__.py'.
Performs safe parsing via Regex without executing external code.
"""

import zipfile
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

class AddonParser:
    @staticmethod
    def parse_zip(zip_path: Path) -> Dict[str, Any]:
        """
        Inspects a zip file in memory to extract Blender add-on metadata.
        Returns a dictionary with standard keys: 'is_valid', 'name', 'version', 'min_blender_version'.
        """
        default_response = {
            "is_valid": False,
            "name": "Unknown Add-on",
            "version": "0.0.0",
            "min_blender_version": "0.0.0",
            "type": "unknown"
        }

        if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
            return default_response

        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                file_list = zf.namelist()
                
                # 1. Search for modern Extension Manifest (Blender 4.2+)
                manifest_files = [f for f in file_list if f.endswith('blender_manifest.toml')]
                if manifest_files:
                    # Sort to get the shallowest file (root level preferred)
                    manifest_files.sort(key=lambda x: x.count('/'))
                    content = zf.read(manifest_files[0]).decode('utf-8', errors='ignore')
                    return AddonParser._parse_toml_manifest(content)

                # 2. Search for Legacy bl_info (Pre 4.2)
                init_files = [f for f in file_list if f.endswith('__init__.py')]
                if init_files:
                    # Sort to get the shallowest __init__.py
                    init_files.sort(key=lambda x: x.count('/'))
                    content = zf.read(init_files[0]).decode('utf-8', errors='ignore')
                    return AddonParser._parse_legacy_bl_info(content)

        except Exception as e:
            print(f"[ADDON PARSER] Error inspecting zip '{zip_path.name}': {e}")
            
        return default_response

    @staticmethod
    def _parse_toml_manifest(content: str) -> Dict[str, Any]:
        """Extracts metadata from a blender_manifest.toml using regex."""
        name_match = re.search(r'name\s*=\s*"([^"]+)"', content)
        version_match = re.search(r'version\s*=\s*"([^"]+)"', content)
        blender_min_match = re.search(r'blender_version_min\s*=\s*"([^"]+)"', content)

        name = name_match.group(1) if name_match else "Unknown Extension"
        version = version_match.group(1) if version_match else "1.0.0"
        min_blender = blender_min_match.group(1) if blender_min_match else "4.2.0"

        return {
            "is_valid": bool(name_match and version_match),
            "name": name,
            "version": version,
            "min_blender_version": min_blender,
            "type": "manifest"
        }

    @staticmethod
    def _parse_legacy_bl_info(content: str) -> Dict[str, Any]:
        """
        Safely extracts bl_info metadata from an __init__.py file using regex
        to prevent execution of untrusted code via eval() or ast.literal_eval().
        """
        # Find the bl_info block (rudimentary but effective for standardized files)
        bl_info_match = re.search(r'bl_info\s*=\s*\{([^}]+)\}', content, re.DOTALL)
        
        if not bl_info_match:
            return {
                "is_valid": False,
                "name": "Unknown Legacy Add-on",
                "version": "0.0.0",
                "min_blender_version": "0.0.0",
                "type": "legacy"
            }

        bl_info_text = bl_info_match.group(1)

        # Regex for values
        name_match = re.search(r'"name"\s*:\s*["\']([^"\']+)["\']', bl_info_text)
        
        # Versions in legacy are tuples: (3, 0, 0)
        version_match = re.search(r'"version"\s*:\s*\(\s*([0-9]+)\s*,\s*([0-9]+)\s*(?:,\s*([0-9]+)\s*)?\)', bl_info_text)
        blender_match = re.search(r'"blender"\s*:\s*\(\s*([0-9]+)\s*,\s*([0-9]+)\s*(?:,\s*([0-9]+)\s*)?\)', bl_info_text)

        name = name_match.group(1) if name_match else "Unknown Add-on"
        
        version = "1.0.0"
        if version_match:
            v_parts = [p for p in version_match.groups() if p is not None]
            version = ".".join(v_parts)

        min_blender = "2.80.0"
        if blender_match:
            b_parts = [p for p in blender_match.groups() if p is not None]
            min_blender = ".".join(b_parts)

        return {
            "is_valid": True,
            "name": name,
            "version": version,
            "min_blender_version": min_blender,
            "type": "legacy"
        }

    @staticmethod
    def is_compatible(addon_min_version: str, target_blender_version: str) -> bool:
        """
        Compares version strings (e.g., '4.2.0' vs '4.5') to determine compatibility.
        Returns True if the target Blender version is >= the add-on's minimum requirement.
        """
        try:
            def parse_version(v: str) -> Tuple[int, ...]:
                # Extract only numeric parts, ignore alphas like 'b', 'alpha'
                clean_v = re.sub(r'[^0-9.]', '', v)
                return tuple(int(x) for x in clean_v.split('.') if x.isdigit())

            addon_tuple = parse_version(addon_min_version)
            target_tuple = parse_version(target_blender_version)

            # Pad tuples to identical length for safe comparison
            max_len = max(len(addon_tuple), len(target_tuple))
            addon_tuple = addon_tuple + (0,) * (max_len - len(addon_tuple))
            target_tuple = target_tuple + (0,) * (max_len - len(target_tuple))

            return target_tuple >= addon_tuple
        except Exception:
            # Fallback for parsing errors: Leave it to TD judgment
            return True
