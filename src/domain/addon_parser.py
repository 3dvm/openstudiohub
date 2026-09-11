# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/addon_parser.py
# Architectural role: Deprecated shim over src.domain.vault.addon
# =========================================================================================

"""DEPRECATED shim.

The real parsing logic now lives in ``src.domain.vault.addon`` and the version
comparison in ``src.domain.vault.compatibility.CompatibilityPolicy``. This
class keeps the legacy ``AddonParser`` API so existing consumers
(``git_packager``, ``widget_software``, ``provisioning_workers``) keep working.
"""

from pathlib import Path
from typing import Any, Dict

from .vault.addon import parse_zip as _parse_zip
from .vault.compatibility import CompatibilityPolicy


class AddonParser:
    @staticmethod
    def parse_zip(zip_path: Path) -> Dict[str, Any]:
        meta = _parse_zip(zip_path)
        return {
            "is_valid": meta.is_valid,
            "name": meta.name,
            "version": meta.version,
            "min_blender_version": meta.min_blender_version,
            "type": meta.type,
        }

    @staticmethod
    def is_compatible(addon_min_version: str, target_blender_version: str) -> bool:
        return CompatibilityPolicy.is_compatible(addon_min_version, target_blender_version)
