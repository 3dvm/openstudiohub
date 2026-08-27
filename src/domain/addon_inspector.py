# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/addon_inspector.py
# Architectural role: Deprecated shim over src.domain.vault.addon
# =========================================================================================

"""DEPRECATED shim.

The real parsing logic now lives in ``src.domain.vault.addon`` and the version
comparison in ``src.domain.vault.compatibility.CompatibilityPolicy``. This
class keeps the legacy ``AddonInspector`` API (used by ``manifest_editor``).
"""

from pathlib import Path
from typing import Any, Dict

from .vault import addon as _addon
from .vault.compatibility import CompatibilityPolicy
from .vault.value_objects import SemVer


class AddonInspector:
    @staticmethod
    def _to_dict(meta: _addon.AddonMetadata) -> Dict[str, Any]:
        name = meta.name.lower().replace(" ", "_") if meta.type == "legacy" else meta.name
        return {
            "name": name or "unknown_addon",
            "version": meta.version,
            "description": meta.description or "Custom loaded addon",
            "blender_min": tuple(SemVer.parse(meta.min_blender_version).padded(3)),
        }

    @staticmethod
    def parse_manifest_content(content: str, is_toml: bool) -> dict:
        meta = _addon.parse_toml(content) if is_toml else _addon.parse_legacy_bl_info(content)
        return AddonInspector._to_dict(meta)

    @staticmethod
    def inspect_zip(zip_path: Path) -> dict:
        meta = _addon.parse_zip(zip_path)
        if meta.type == "unknown":
            return {}
        return AddonInspector._to_dict(meta)

    @staticmethod
    def inspect_directory(dir_path: Path) -> dict:
        meta = _addon.parse_directory(dir_path)
        if meta.type == "unknown":
            return {}
        return AddonInspector._to_dict(meta)

    @staticmethod
    def is_compatible(min_version_tuple: tuple, target_v_str: str) -> bool:
        return CompatibilityPolicy.is_compatible(min_version_tuple, target_v_str)
