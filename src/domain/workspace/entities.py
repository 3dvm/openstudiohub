
# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/workspace/entities.py
# Architectural role: Workspace domain entities
# =========================================================================================

from dataclasses import dataclass, field
from typing import List, Optional
from src.domain.production.entities import Project as KitsuProject
from src.domain.workspace.blueprint import ProjectBlueprint

@dataclass
class ProjectHealth:
    """Value Object representing the result of the project audit."""
    is_accessible_on_nas: bool = False
    is_installed_locally: bool = False
    missing_critical_folders: List[str] = field(default_factory=list)
    has_blueprint: bool = False
    has_kitsu_project: bool = False

    @property
    def is_healthy(self) -> bool:
        return (self.is_accessible_on_nas and
                len(self.missing_critical_folders) == 0 and
                self.has_blueprint and
                self.has_kitsu_project)

@dataclass
class HubProject:
    """Main Hub unifiying entity between prodcution and file system."""

    name: str
    kitsu_info: Optional[KitsuProject] = None
    blueprint: ProjectBlueprint = field(default_factory=ProjectBlueprint)
    health: ProjectHealth = field(default_factory=ProjectHealth)

    @property
    def ready_to_launch(self) -> bool:
        """Only launches healthy and installed projects."""
        return self.health.is_healthy and self.health.is_installed_locally
