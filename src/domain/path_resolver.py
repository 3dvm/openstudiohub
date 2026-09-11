# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/path_resolver.py
# Architectural role: Deprecated shim over NamingPolicy
# =========================================================================================

"""
DEPRECATED backward-compatibility shim.

The entity -> path rules now live in ``src.domain.production.naming.NamingPolicy``
(the single source of truth). This class adapts raw Kitsu task dicts to the
NamingPolicy and is kept only so existing callers (``env_launcher``,
``sparse_manager``) keep working until they are migrated to the typed
``Task`` entity + ``NamingPolicy`` directly.
"""

from typing import Dict, Optional

from .production.naming import NamingPolicy
from .production.value_objects import EntityType


class PathResolver:
    @staticmethod
    def get_sparse_path(task_data: Dict[str, str]) -> Optional[str]:
        if not task_data:
            return None
        entity_type = EntityType.from_raw(
            task_data.get("entity_type_name", task_data.get("entity_type", ""))
        )
        return str(
            NamingPolicy.sparse_path(
                entity_type=entity_type,
                entity_name=task_data.get("entity_name", ""),
                sequence_name=task_data.get("sequence_name", ""),
                asset_type_name=task_data.get("asset_type_name", "props"),
            )
        )

    def resolve(self, task_data: Dict[str, str]) -> Optional[str]:
        if not task_data:
            return None
        try:
            return str(
                NamingPolicy.workfile_path(
                    entity_type=EntityType.from_raw(
                        task_data.get("entity_type_name", task_data.get("entity_type", ""))
                    ),
                    entity_name=task_data.get("entity_name", ""),
                    sequence_name=task_data.get("sequence_name", ""),
                    asset_type_name=task_data.get("asset_type_name", "props"),
                    task_short_name=task_data.get(
                        "task_type_short_name", task_data.get("task_type_name", "generic")
                    ),
                    project_name=task_data.get("project_name", "project"),
                )
            )
        except ValueError:
            return None
