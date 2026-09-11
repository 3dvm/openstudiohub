# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/production/value_objects.py
# Architectural role: Production value objects (EntityType, FilePath)
# =========================================================================================

"""Production value objects."""

from dataclasses import dataclass
from enum import Enum


class EntityType(str, Enum):
    """Kitsu production entity kind (mirrors Kitsu's entity_type_name)."""

    SHOT = "shot"
    ASSET = "asset"
    SEQUENCE = "sequence"
    EDIT = "edit"
    UNKNOWN = "unknown"

    @classmethod
    def from_raw(cls, raw: str) -> "EntityType":
        value = (raw or "").strip().lower()
        if value == "shot":
            return cls.SHOT
        if value == "asset":
            return cls.ASSET
        if value == "sequence":
            return cls.SEQUENCE
        if value == "edit":
            return cls.EDIT
        return cls.UNKNOWN


@dataclass(frozen=True)
class FilePath:
    """A production-file path relative to the VCS root (POSIX separators)."""

    value: str

    def __str__(self) -> str:
        return self.value

    def __fspath__(self) -> str:
        return self.value
