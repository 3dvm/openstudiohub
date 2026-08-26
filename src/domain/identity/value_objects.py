# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/identity/value_objects.py
# Architectural role: Identity value objects (RBAC Role)
# =========================================================================================

"""Identity value objects.

``Role`` owns the single RBAC mapping between Kitsu's raw role/position fields
and the Hub's domain roles. Kitsu is the System of Record; the Hub mirrors it
into this typed projection.
"""

from enum import Enum


class Role(str, Enum):
    """Studio role for authorization decisions across the Hub."""

    TD = "td"
    SUPERVISOR = "supervisor"
    MANAGER = "manager"
    LEAD = "lead"
    ARTIST = "artist"
    VENDOR = "vendor"
    CLIENT = "client"
    GUEST = "guest"

    @classmethod
    def from_kitsu(cls, kitsu_role: str, kitsu_position: str = "") -> "Role":
        """Translate Kitsu's raw role/position into a Hub domain role.

        Previously this logic lived inline in ``AuthManager.get_user_role``.
        """
        role = (kitsu_role or "").strip().lower()
        position = (kitsu_position or "").strip().lower()

        if role == "admin":
            return cls.TD
        if role == "supervisor":
            return cls.SUPERVISOR
        if role == "manager":
            return cls.MANAGER
        if role == "vendor":
            return cls.VENDOR
        if role == "client":
            return cls.CLIENT
        if role == "user":
            return cls.LEAD if position == "lead" else cls.ARTIST
        return cls.ARTIST

    @property
    def label(self) -> str:
        """Human-readable role label for the UI."""
        return self.value.capitalize()
