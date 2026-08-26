# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/production/events.py
# Architectural role: Production domain events
# =========================================================================================

"""Production domain events."""

from dataclasses import dataclass

from ..shared_kernel.events import DomainEvent


@dataclass(frozen=True)
class ProjectCreated(DomainEvent):
    project_id: str = ""
    project_name: str = ""


@dataclass(frozen=True)
class TaskForged(DomainEvent):
    task_id: str = ""
    entity_id: str = ""
    file_path: str = ""


@dataclass(frozen=True)
class FilePathMapped(DomainEvent):
    entity_id: str = ""
    file_path: str = ""
