# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/production/entities.py
# Architectural role: Production entities (typed Kitsu projections)
# =========================================================================================

"""Production entities.

These are typed projections of Kitsu's production schema. Kitsu remains the
System of Record; ``*_from_kitsu_dict`` factories are the single translation
boundary where the raw dict is converted into the domain model.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .value_objects import EntityType, FilePath
from .naming import NamingPolicy


@dataclass
class Project:
    id: str = ""
    name: str = ""

    @classmethod
    def from_kitsu_dict(cls, data: Optional[Dict[str, Any]]) -> "Project":
        data = data or {}
        return cls(id=data.get("id") or "", name=data.get("name") or "")


@dataclass
class Sequence:
    id: str = ""
    name: str = ""
    project_id: str = ""

    @classmethod
    def from_kitsu_dict(cls, data: Optional[Dict[str, Any]]) -> "Sequence":
        data = data or {}
        return cls(
            id=data.get("id") or "",
            name=data.get("name") or "",
            project_id=data.get("project_id") or "",
        )


@dataclass
class Shot:
    id: str = ""
    name: str = ""
    sequence_id: str = ""
    status: str = ""
    nb_frames: int = 0

    @classmethod
    def from_kitsu_dict(cls, data: Optional[Dict[str, Any]]) -> "Shot":
        data = data or {}
        return cls(
            id=data.get("id") or "",
            name=data.get("name") or "",
            sequence_id=data.get("sequence_id") or "",
            status=data.get("status") or "Todo",
            nb_frames=data.get("nb_frames") or 0,
        )


@dataclass
class Asset:
    id: str = ""
    name: str = ""
    asset_type_id: str = ""
    status: str = ""

    @classmethod
    def from_kitsu_dict(cls, data: Optional[Dict[str, Any]]) -> "Asset":
        data = data or {}
        return cls(
            id=data.get("id") or "",
            name=data.get("name") or "",
            # In Kitsu the asset type id is stored as 'entity_type_id' on the asset.
            asset_type_id=data.get("entity_type_id") or "",
            status=data.get("status") or "Todo",
        )


@dataclass
class AssetType:
    id: str = ""
    name: str = ""

    @classmethod
    def from_kitsu_dict(cls, data: Optional[Dict[str, Any]]) -> "AssetType":
        data = data or {}
        return cls(id=data.get("id") or "", name=data.get("name") or "")


@dataclass
class TaskType:
    id: str = ""
    name: str = ""
    for_entity: str = ""

    @classmethod
    def from_kitsu_dict(cls, data: Optional[Dict[str, Any]]) -> "TaskType":
        data = data or {}
        return cls(
            id=data.get("id") or "",
            name=data.get("name") or "",
            for_entity=data.get("for_entity") or "",
        )


@dataclass
class Task:
    """A production task enriched with the context the NamingPolicy needs."""

    id: str = ""
    entity_id: str = ""
    entity_type: EntityType = EntityType.UNKNOWN
    entity_name: str = ""
    sequence_name: str = ""
    asset_type_name: str = ""
    project_id: str = ""
    project_name: str = ""
    task_type_id: str = ""
    task_type_name: str = ""
    task_type_short_name: str = ""
    status: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_kitsu_dict(cls, data: Optional[Dict[str, Any]], **extra: Any) -> "Task":
        data = data or {}
        status = (
            data.get("task_status_name")
            or (data.get("task_status") or {}).get("name")
            or data.get("status")
            or ""
        )
        kwargs: Dict[str, Any] = {
            "id": data.get("id") or "",
            "entity_id": data.get("entity_id") or "",
            "entity_type": EntityType.from_raw(data.get("entity_type_name") or data.get("entity_type")),
            "entity_name": data.get("entity_name") or "",
            "sequence_name": data.get("sequence_name") or "",
            "asset_type_name": data.get("asset_type_name") or "",
            "project_id": data.get("project_id") or "",
            "project_name": data.get("project_name") or (data.get("project") or {}).get("name") or "",
            "task_type_id": data.get("task_type_id") or "",
            "task_type_name": data.get("task_type_name") or "",
            "task_type_short_name": data.get("task_type_short_name") or data.get("task_type_name") or "",
            "status": status,
            "data": data.get("data") or {},
        }
        kwargs.update(extra)
        return cls(**kwargs)

    # ------------------------------------------------------------------
    # Path helpers (delegated to NamingPolicy — the single source of truth)
    # ------------------------------------------------------------------
    def workfile_path(self) -> FilePath:
        return NamingPolicy.workfile_path(
            entity_type=self.entity_type,
            entity_name=self.entity_name,
            sequence_name=self.sequence_name,
            asset_type_name=self.asset_type_name,
            task_short_name=self.task_type_short_name,
            project_name=self.project_name,
        )

    def sparse_path(self) -> FilePath:
        return NamingPolicy.sparse_path(
            entity_type=self.entity_type,
            entity_name=self.entity_name,
            sequence_name=self.sequence_name,
            asset_type_name=self.asset_type_name,
        )
