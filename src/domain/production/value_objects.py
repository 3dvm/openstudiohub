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


# VCS status codes that mean "the working copy differs from the server".
CHANGED_STATUS_CODES = frozenset({"M", "A", "D", "R", "C", "!", "~"})

# VCS status code for a file that is not tracked yet (needs ``add`` before commit).
UNVERSIONED_STATUS_CODE = "?"


@dataclass(frozen=True)
class FileChange:
    """A single working-copy entry reported by the VCS status scan."""

    relative_path: str
    status: str

    @property
    def is_unversioned(self) -> bool:
        """True when the file is new and must be added before being committed."""
        return self.status == UNVERSIONED_STATUS_CODE

    @property
    def is_changed(self) -> bool:
        """True when the entry represents a real, committable change."""
        return self.status in CHANGED_STATUS_CODES or self.is_unversioned
