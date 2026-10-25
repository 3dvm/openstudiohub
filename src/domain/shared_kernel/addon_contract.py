# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/shared_kernel/addon_contract.py
# Architectural role: Shared Kernel / Add-on configuration contract (SPEC)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. All rights reserved.
# License: GNU General Public License v3.0 (GPLv3)
# =========================================================================================

"""Typed model for the per-add-on configuration stored in ``project_init.json``.

Historically every add-on was configured by hard-coded code inside the DCC-side
scripts (``bootstrap.py`` / ``headless_builder.py``). This module defines the
*declarative* contract that replaces that coupling: a mapping of
``addon_name -> AddonConfiguration`` describing which add-ons are active, the
static settings they receive, and the behaviors the project wants applied.

The contract is intentionally add-on agnostic. Secrets and per-launch context
(host, user, password, project/entity ids) are **not** stored here; they keep
travelling through :mod:`env_contract` as RAM-only environment variables. The
generated ``cfg_<addon>.py`` scripts merge both sources at launch time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

# Top-level key inside ``project_init.json`` that holds the configuration.
ADDON_CONFIGURATION_KEY = "addon_configuration"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_addon_name(name: str) -> str:
    """Canonical, filesystem-safe id for an add-on.

    Blueprints may store either module keys (``openstudio_toolkit``) or display
    names (``Blender Kitsu``). The slug unifies both so template resolution and
    generated file names always match (``blender_kitsu``).
    """
    return _SLUG_RE.sub("_", (name or "").strip().lower()).strip("_")


@dataclass
class AddonConfiguration:
    """Declarative configuration for a single add-on within a project.

    ``settings`` holds static, serializable values (folder names, toggles...).
    ``behaviors`` is an ordered list of capability names the generated script
    must apply (``activate``, ``authenticate``, ``override_vfs_root``...).
    """

    name: str = ""
    enabled: bool = True
    module_match: str = ""
    settings: Dict[str, Any] = field(default_factory=dict)
    behaviors: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, name: str, data: Optional[Mapping[str, Any]]) -> "AddonConfiguration":
        data = data or {}
        return cls(
            name=name,
            enabled=bool(data.get("enabled", True)),
            module_match=str(data.get("module_match") or name),
            settings=dict(data.get("settings") or {}),
            behaviors=list(data.get("behaviors") or []),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "module_match": self.module_match,
            "settings": self.settings,
            "behaviors": self.behaviors,
        }


def parse_addon_configuration(raw: Optional[Mapping[str, Any]]) -> Dict[str, AddonConfiguration]:
    """Parse the raw ``addon_configuration`` mapping from ``project_init.json``."""
    result: Dict[str, AddonConfiguration] = {}
    for name, data in (raw or {}).items():
        if isinstance(data, AddonConfiguration):
            result[name] = data
        elif isinstance(data, Mapping):
            result[name] = AddonConfiguration.from_dict(name, data)
    return result


def serialize_addon_configuration(
    configuration: Optional[Mapping[str, AddonConfiguration]],
) -> Dict[str, Any]:
    """Serialize a typed configuration mapping back to JSON-friendly dicts."""
    return {
        name: config.to_dict()
        for name, config in (configuration or {}).items()
        if isinstance(config, AddonConfiguration)
    }


# Fallback declarative schema per known add-on. Used by the UI when the vault
# manifest does not carry its own ``config_schema``/``default_config`` entry.
DEFAULT_ADDON_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "blender_kitsu": {
        "config_schema": {
            "version_control": {"type": "bool", "default": True, "label": "Enable version control"},
            "shot_dir_name": {"type": "str", "default": "shots", "label": "Shots folder"},
            "asset_dir_name": {"type": "str", "default": "assets", "label": "Assets folder"},
            "seq_dir_name": {"type": "str", "default": "strips", "label": "Sequences folder"},
            "edit_dir_name": {"type": "str", "default": "edit", "label": "Edit folder"},
            "playblast_subdir": {"type": "str", "default": "edit/footage", "label": "Playblast footage"},
        },
        "default_config": {
            "behaviors": [
                "activate",
                "configure",
                "authenticate",
                "set_active_project",
                "override_vfs_root",
                "persist_on_load",
            ]
        },
    },
    "openstudio_toolkit": {
        "config_schema": {},
        "default_config": {"behaviors": ["activate"]},
    },
}


def resolve_addon_entry(addon_name: str, manifest_entry: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Merge a manifest add-on entry over the built-in schema catalog.

    Manifest values take precedence; catalog defaults fill the gaps. This keeps
    the UI form available even for vaults created before the schema existed.
    """
    catalog = DEFAULT_ADDON_SCHEMAS.get(addon_name) or {}
    return {**catalog, **(manifest_entry or {})}


def default_addon_configuration(dependencies: Optional[Mapping[str, Any]]) -> Dict[str, AddonConfiguration]:
    """Derive an enabled skeleton config from legacy ``dependencies.addons``.

    Backwards compatibility: projects created before the add-on contract existed
    only stored ``dependencies={"addons": {"blender_kitsu": "1.5.0"}}``. This
    lets them keep working; the generated templates fall back to their own
    defaults when ``settings``/``behaviors`` are empty.
    """
    addons = (dependencies or {}).get("addons") or {}
    if not isinstance(addons, Mapping):
        return {}
    return {
        name: AddonConfiguration(name=name, module_match=slugify_addon_name(name))
        for name in addons.keys()
    }
