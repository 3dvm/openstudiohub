# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/identity/entities.py
# Architectural role: Identity entities (User, Session)
# =========================================================================================

"""Identity entities."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .value_objects import Role


@dataclass
class User:
    """An authenticated studio member (typed projection of Kitsu's person)."""

    id: Optional[str] = None
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    role: Role = Role.GUEST
    position: str = ""

    @classmethod
    def from_kitsu_dict(cls, data: Dict[str, Any]) -> "User":
        """Build a User from the raw Kitsu person dict (SSoT boundary).

        This is the one place the raw Kitsu schema is translated into the
        domain model; everything downstream consumes ``User``, never the dict.
        """
        data = data or {}
        first = data.get("first_name") or ""
        last = data.get("last_name") or ""
        full = data.get("full_name") or f"{first} {last}".strip()
        return cls(
            id=data.get("id"),
            email=data.get("email") or "",
            first_name=first,
            last_name=last,
            full_name=full,
            role=Role.from_kitsu(data.get("role") or "", data.get("position") or ""),
            position=(data.get("position") or "").lower(),
        )


@dataclass
class Session:
    """An authenticated Kitsu session (host + tokens)."""

    host: str = ""
    tokens: Dict[str, Any] = field(default_factory=dict)
