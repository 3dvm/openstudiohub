# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/vault/manifest.py
# Architectural role: Vault aggregate (software inventory manifest)
# =========================================================================================

"""The canonical vault manifest aggregate.

One schema, one location: the software inventory is keyed by Blender version,
with ``addons`` and ``templates`` categories (each a dict keyed by name). This
replaces the two previously divergent schemas (``VaultManager`` vs
``ManifestManager``).

Raw file format (``vault_manifest.json``):

    {
      "<version>": {
        "blender_version": "<version>",
        "categories": {
          "addons":    { "<name>": {"version": ..., "description": ..., "mandatory": ..., "requires": []} },
          "templates": { "<name>": {"version": ..., "description": ..., "mandatory": ..., "requires": []} }
        }
      }
    }

Internally the aggregate holds the *normalized* form
``{version: {"addons": {...}, "templates": {...}}}``.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class VaultManifest:
    versions: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "VaultManifest":
        versions: Dict[str, Dict[str, Any]] = {}
        for key, val in (raw or {}).items():
            if not isinstance(val, dict):
                continue
            version = str(val.get("blender_version") or key).lstrip("vV ").strip()
            categories = val.get("categories") if "categories" in val else val
            if isinstance(categories, dict):
                versions[version] = categories
        return cls(versions=versions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            version: {"blender_version": version, "categories": categories}
            for version, categories in self.versions.items()
        }

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def registered_versions(self) -> List[str]:
        return list(self.versions.keys())

    def get_addons(self, version: str) -> Dict[str, Any]:
        return self.versions.get(version, {}).get("addons", {})

    def get_templates(self, version: str) -> Dict[str, Any]:
        return self.versions.get(version, {}).get("templates", {})

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    def ensure_version(self, version: str) -> None:
        self.versions.setdefault(version, {"addons": {}, "templates": {}})

    def add_addon(
        self,
        version: str,
        name: str,
        addon_version: str,
        description: str = "",
        mandatory: bool = False,
        requires: List[str] = None,
    ) -> None:
        self.ensure_version(version)
        self.versions[version].setdefault("addons", {})[name] = {
            "version": addon_version,
            "description": description,
            "mandatory": mandatory,
            "requires": list(requires or []),
        }
