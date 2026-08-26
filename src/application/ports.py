# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/ports.py
# Architectural role: Application ports (interfaces for infrastructure adapters)
# =========================================================================================

"""Application-layer ports.

The domain/application layers depend on these abstractions; infrastructure
provides concrete implementations (e.g. ``FileSessionRepository``,
``KitsuProductionRepository``).
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from src.domain.identity.entities import Session
from src.domain.production.entities import (
    Project,
    Sequence,
    Shot,
    Asset,
    AssetType,
    TaskType,
    Task,
)


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


class ProductionRepository(ABC):
    """Port for production data (Kitsu is the System of Record).

    Implementations translate the external Kitsu schema into the typed
    ``src.domain.production`` entities; nothing outside this port should see
    raw Kitsu dicts.
    """

    # --- Projects ---
    @abstractmethod
    def all_projects(self) -> List[Project]:
        """Return all projects."""

    @abstractmethod
    def get_project(self, project_id: str) -> Optional[Project]:
        """Return a project by id."""

    # --- Sequences / Shots / Assets ---
    @abstractmethod
    def all_sequences_for_project(self, project_id: str) -> List[Sequence]:
        """Return all sequences for a project."""

    @abstractmethod
    def get_sequence(self, sequence_id: str) -> Optional[Sequence]:
        """Return a sequence by id."""

    @abstractmethod
    def all_shots_for_project(self, project_id: str) -> List[Shot]:
        """Return all shots for a project."""

    @abstractmethod
    def all_assets_for_project(self, project_id: str) -> List[Asset]:
        """Return all assets for a project."""

    @abstractmethod
    def get_asset_type(self, asset_type_id: str) -> Optional[AssetType]:
        """Return an asset type by id."""

    # --- Task types / tasks ---
    @abstractmethod
    def all_task_types(self) -> List[TaskType]:
        """Return all global task types."""

    @abstractmethod
    def get_task_type_by_name(self, name: str) -> Optional[TaskType]:
        """Return a task type by name."""

    @abstractmethod
    def new_task_type(self, name: str, color: str = "#000000", for_entity: str = "Asset") -> TaskType:
        """Create (or return) a global task type."""

    @abstractmethod
    def create_task(self, entity_id: str, task_type_name: str) -> Optional[Task]:
        """Create a task of the given type on an entity."""

    # --- Metadata ---
    @abstractmethod
    def update_entity_data(self, entity_id: str, data: dict) -> bool:
        """Persist custom metadata on a generic entity."""
