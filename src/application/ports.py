# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/ports.py
# Architectural role: Application ports (interfaces for infrastructure adapters)
# =========================================================================================

"""Application-layer ports.

The domain/application layers depend on these abstractions; infrastructure
provides concrete implementations (e.g. ``FileSessionRepository``).
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.identity.entities import Session


class SessionRepository(ABC):
    """Persistence port for the authenticated Kitsu session."""

    @abstractmethod
    def load(self) -> Optional[Session]:
        """Return the saved session, or None if there is none."""

    @abstractmethod
    def save(self, session: Session) -> None:
        """Persist the given session."""

    @abstractmethod
    def delete(self) -> None:
        """Delete any persisted session."""
