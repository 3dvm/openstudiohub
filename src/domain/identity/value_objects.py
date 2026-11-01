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


class ViewProfile(str, Enum):
    """Dashboard profile a user can switch to."""

    TD = "td"
    PM = "pm"
    ARTIST = "artist"

    @property
    def label(self) -> str:
        return {
            ViewProfile.TD: "TD",
            ViewProfile.PM: "PM",
            ViewProfile.ARTIST: "Artist",
        }[self]

    @classmethod
    def from_value(cls, value) -> "ViewProfile | None":
        normalized = str(getattr(value, "value", value) or "").strip().lower()
        for profile in cls:
            if profile.value == normalized:
                return profile
        return None


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

    def access_profiles(self) -> tuple[ViewProfile, ...]:
        """Incremental dashboard profiles granted by this role."""
        return {
            Role.TD: (ViewProfile.TD, ViewProfile.PM, ViewProfile.ARTIST),
            Role.MANAGER: (ViewProfile.PM, ViewProfile.ARTIST),
            Role.LEAD: (ViewProfile.ARTIST,),
            Role.ARTIST: (ViewProfile.ARTIST,),
            Role.VENDOR: (ViewProfile.ARTIST,),
        }.get(self, ())

    def has_hub_access(self) -> bool:
        return bool(self.access_profiles())

    def default_profile(self, position: str = "") -> ViewProfile | None:
        profiles = self.access_profiles()
        if not profiles:
            return None
        if self is Role.TD:
            return ViewProfile.TD
        if self is Role.MANAGER:
            # A PM with the lead position is the editor: same artist dashboard.
            return ViewProfile.ARTIST if (position or "").strip().lower() == "lead" else ViewProfile.PM
        return ViewProfile.ARTIST

    def profile_label(self, profile, position: str = "") -> str:
        view = ViewProfile.from_value(profile)
        if view is None:
            return self.label
        if (
            view is ViewProfile.ARTIST
            and self is Role.MANAGER
            and (position or "").strip().lower() == "lead"
        ):
            return "Editor"
        return view.label
