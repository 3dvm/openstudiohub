# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/production/naming.py
# Architectural role: Production domain service / NamingPolicy
# =========================================================================================

"""Single source of truth for entity -> filesystem path rules.

Historically these rules were copy-pasted across five modules (PathResolver,
ProductionManager, env_launcher, api_queries workers, and headless_builder),
each drifting slightly. ``NamingPolicy`` consolidates them so there is exactly
one place that knows the studio's "Semantic Topography" convention.

Conventions (unified):
  * shots   -> pro/shots/<sequence>/<shot>/<shot>-<task>.blend
  * assets  -> pro/assets/<asset_type>/<asset>/<asset_type>-<asset>-<task>.blend
  * storyboard -> edit/storyboards/<sequence>-storyboard.blend
  * edit    -> edit/<project>-edit.blend

Names are slugified (lowercase, spaces -> underscores). This intentionally
unifies the previously inconsistent per-module casing/separator behavior.
"""

import re

from .value_objects import EntityType, FilePath


class NamingPolicy:
    @staticmethod
    def slug(name: str) -> str:
        return (name or "").strip().lower().replace(" ", "_")

    @staticmethod
    def sanitize_name(raw: str) -> str:
        """Lowercase + underscores and strip non-alphanumeric (Kitsu name sanitization)."""
        if not raw:
            return ""
        name = raw.lower().replace(" ", "_")
        name = re.sub(r"[^a-z0-9_\-]", "", name)
        return re.sub(r"_+", "_", name)

    @staticmethod
    def project_slug(name: str) -> str:
        return (name or "project").strip().lower().replace(" ", "-")

    @staticmethod
    def normalize_task_name(raw: str) -> str:
        name = (raw or "").strip().lower()
        if "anim" in name:
            return "anim"
        if "model" in name:
            return "model"
        return name or "generic"

    # ------------------------------------------------------------------
    # Structural directories
    # ------------------------------------------------------------------
    @staticmethod
    def shot_dir(sequence_name: str, shot_name: str) -> str:
        return f"pro/shots/{NamingPolicy.slug(sequence_name)}/{NamingPolicy.slug(shot_name)}"

    @staticmethod
    def asset_dir(asset_type_name: str, asset_name: str) -> str:
        asset_type = NamingPolicy.slug(asset_type_name or "props")
        return f"pro/assets/{asset_type}/{NamingPolicy.slug(asset_name)}"

    # ------------------------------------------------------------------
    # Sparse-checkout directory (jailing)
    # ------------------------------------------------------------------
    @staticmethod
    def sparse_path(
        entity_type: EntityType,
        entity_name: str,
        sequence_name: str = "",
        asset_type_name: str = "props",
    ) -> FilePath:
        if entity_type == EntityType.SHOT:
            if not sequence_name or not entity_name:
                raise ValueError("Shot metadata incomplete: missing sequence_name.")
            return FilePath(NamingPolicy.shot_dir(sequence_name, entity_name))
        if entity_type == EntityType.ASSET:
            if not entity_name:
                raise ValueError("Asset metadata incomplete: missing entity_name.")
            return FilePath(NamingPolicy.asset_dir(asset_type_name, entity_name))
        raise ValueError(f"Unsupported entity type for sparse path: {entity_type}")

    # ------------------------------------------------------------------
    # Work files
    # ------------------------------------------------------------------
    @staticmethod
    def shot_path(sequence_name: str, shot_name: str, task_short_name: str) -> str:
        task = NamingPolicy.normalize_task_name(task_short_name)
        return f"{NamingPolicy.shot_dir(sequence_name, shot_name)}/{NamingPolicy.slug(shot_name)}-{task}.blend"

    @staticmethod
    def asset_path(asset_type_name: str, asset_name: str, task_short_name: str) -> str:
        asset_type = NamingPolicy.slug(asset_type_name or "props")
        task = NamingPolicy.normalize_task_name(task_short_name)
        return (
            f"{NamingPolicy.asset_dir(asset_type_name, asset_name)}/"
            f"{asset_type}-{NamingPolicy.slug(asset_name)}-{task}.blend"
        )

    @staticmethod
    def storyboard_path(sequence_name: str) -> str:
        return f"edit/storyboards/{NamingPolicy.slug(sequence_name)}-storyboard.blend"

    @staticmethod
    def edit_path(project_name: str) -> str:
        return f"edit/{NamingPolicy.project_slug(project_name)}-edit.blend"

    @staticmethod
    def workfile_path(
        entity_type: EntityType,
        entity_name: str,
        sequence_name: str = "",
        asset_type_name: str = "props",
        task_short_name: str = "generic",
        project_name: str = "project",
    ) -> FilePath:
        task = NamingPolicy.normalize_task_name(task_short_name)

        if entity_type == EntityType.SEQUENCE or task == "storyboard":
            return FilePath(NamingPolicy.storyboard_path(entity_name or sequence_name))
        if task == "edit" or entity_type == EntityType.EDIT:
            return FilePath(NamingPolicy.edit_path(project_name))
        if entity_type == EntityType.SHOT:
            if not sequence_name or not entity_name:
                raise ValueError("Shot metadata incomplete: missing sequence_name.")
            return FilePath(NamingPolicy.shot_path(sequence_name, entity_name, task))
        if entity_type == EntityType.ASSET:
            if not entity_name:
                raise ValueError("Asset metadata incomplete: missing entity_name.")
            return FilePath(NamingPolicy.asset_path(asset_type_name, entity_name, task))
        raise ValueError(f"Unsupported entity type for workfile path: {entity_type}")
