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
from pathlib import Path
from typing import Any, Dict, List, Optional

# Category entry fields carried over when migrating legacy list-based add-ons.
_ENTRY_FIELDS = ("version", "description", "mandatory", "requires", "path", "config_schema", "default_config")


def needs_migration(raw: Optional[Dict[str, Any]]) -> bool:
    """Whether ``raw`` uses a legacy schema requiring canonicalization.

    Two legacy shapes are recognized:

    * the pre-unification ``{"blender_versions": {<version>: {...}}}`` wrapper;
    * categories stored as *lists* of ``{"name": ..., "version": ...}`` dicts.
    """
    if not isinstance(raw, dict):
        return False
    if isinstance(raw.get("blender_versions"), dict):
        return True
    for val in raw.values():
        if not isinstance(val, dict):
            continue
        categories = val.get("categories") if "categories" in val else val
        if isinstance(categories, dict) and any(isinstance(items, list) for items in categories.values()):
            return True
    return False


def _entry_name(entry: Dict[str, Any], fallback: str) -> str:
    name = entry.get("name") or entry.get("id")
    if name:
        return str(name)
    path = entry.get("path")
    if path:
        return Path(str(path)).stem
    return fallback


def _normalize_category(items: Any) -> Dict[str, Any]:
    """Coerce a category block into the canonical ``{name: entry}`` mapping."""
    if isinstance(items, dict):
        return {name: entry for name, entry in items.items() if isinstance(entry, dict)}
    if isinstance(items, list):
        normalized: Dict[str, Any] = {}
        for index, entry in enumerate(items):
            if not isinstance(entry, dict):
                continue
            name = _entry_name(entry, f"item_{index}")
            normalized[name] = {field_name: entry[field_name] for field_name in _ENTRY_FIELDS if field_name in entry}
        return normalized
    return {}


@dataclass
class VaultManifest:
    versions: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "VaultManifest":
        raw = raw or {}
        if isinstance(raw.get("blender_versions"), dict):
            raw = raw["blender_versions"]

        versions: Dict[str, Dict[str, Any]] = {}
        for key, val in raw.items():
            if not isinstance(val, dict):
                continue
            version = str(val.get("blender_version") or key).lstrip("vV ").strip()
            categories = val.get("categories") if "categories" in val else val
            if isinstance(categories, dict):
                versions[version] = {
                    category: _normalize_category(items)
                    for category, items in categories.items()
                }
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
        config_schema: Dict[str, Any] = None,
        default_config: Dict[str, Any] = None,
    ) -> None:
        self.ensure_version(version)
        entry: Dict[str, Any] = {
            "version": addon_version,
            "description": description,
            "mandatory": mandatory,
            "requires": list(requires or []),
        }
        if config_schema is not None:
            entry["config_schema"] = dict(config_schema)
        if default_config is not None:
            entry["default_config"] = dict(default_config)
        self.versions[version].setdefault("addons", {})[name] = entry
