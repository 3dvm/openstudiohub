# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/identity/events.py
# Architectural role: Identity domain events
# =========================================================================================

"""Identity domain events."""

from dataclasses import dataclass

from ..shared_kernel.events import DomainEvent


@dataclass(frozen=True)
class UserAuthenticated(DomainEvent):
    """Emitted after a user successfully authenticates."""

    user_id: str = ""


@dataclass(frozen=True)
class UserLoggedOut(DomainEvent):
    """Emitted after a user logs out."""

    user_id: str = ""
