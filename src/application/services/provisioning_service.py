# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/provisioning_service.py
# Architectural role: Application service / add-on registration step
# =========================================================================================

"""Provisioning service.

The shared "validate + register" step previously duplicated across the two
Studio-Tools fetchers (``StudioToolsFetchWorker`` and
``StudioToolsPackagerWorker``). ``register_addon`` copies the zip into the
vault, so callers must NOT copy it again.
"""

from typing import Any, Dict, Optional, Tuple

from src.domain.addon_parser import AddonParser


class ProvisioningService:
    @staticmethod
    def register_if_compatible(
        manifest_manager,
        parsed: Dict[str, Any],
        current_version: str,
        addon_zip_path: Any,
        description: str = "",
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Register a parsed add-on if it is valid and compatible.

        Returns ``(success, entry_dict)`` where ``entry_dict`` matches the shape
        the settings UI (``TabSoftware``) expects.
        """
        if not parsed.get("is_valid"):
            return False, None
        if not AddonParser.is_compatible(parsed["min_blender_version"], current_version):
            return False, None

        addon_name = parsed["name"]
        addon_version = parsed["version"]

        ok, _ = manifest_manager.register_addon(
            blender_version=current_version,
            addon_name=addon_name,
            addon_version=addon_version,
            source_zip=addon_zip_path,
            description=description,
        )
        if not ok:
            return False, None

        desc = description or "Blender Studio Tool"
        entry = {
            "version": addon_version,
            "description": desc[:60] + "..." if len(desc) > 60 else desc,
            "mandatory": False,
            "requires": [],
        }
        return True, entry
