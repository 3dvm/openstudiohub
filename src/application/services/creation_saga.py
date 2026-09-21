# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/creation_saga.py
# Architectural role: Application service / project creation saga types
# =========================================================================================

"""Resumable project creation saga value objects.

The creation flow is modelled as an ordered set of steps so a failed step can be
retried without re-running the steps that already succeeded. ``CreationOutcome``
carries enough information for the UI to offer recovery actions (retry / delete
created data / go back).
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Set

from src.domain.workspace.blueprint import ProjectBlueprint


class CreationStep(str, Enum):
    PREFLIGHT_KITSU = "preflight_kitsu"
    PREFLIGHT_VCS = "preflight_vcs"
    KITSU = "kitsu"
    SCAFFOLD = "scaffold"
    MANIFESTS = "manifests"
    SPLASH = "splash"
    VFS_PATCH = "vfs_patch"
    VCS = "vcs"


SIDE_EFFECT_STEPS = frozenset(
    {
        CreationStep.KITSU.value,
        CreationStep.SCAFFOLD.value,
        CreationStep.MANIFESTS.value,
        CreationStep.SPLASH.value,
        CreationStep.VFS_PATCH.value,
        CreationStep.VCS.value,
    }
)


class StageError(Exception):
    """Raised by a saga step to signal an expected, recoverable failure."""

    def __init__(self, step: CreationStep, message: str) -> None:
        super().__init__(message)
        self.step = step
        self.message = message


@dataclass
class CreationContext:
    """Mutable state carried across saga steps and retries."""

    project_name: str
    folder_name: str
    project_path: Path
    blueprint: ProjectBlueprint
    vcs_user: str = ""
    vcs_pwd: str = ""
    vcs_enabled: bool = True
    splash_image_path: str = ""
    ignore_rules: list = field(default_factory=list)
    kitsu_project_id: str = ""
    completed: Set[str] = field(default_factory=set)

    def is_done(self, step: CreationStep) -> bool:
        return step.value in self.completed

    def mark_done(self, step: CreationStep) -> None:
        self.completed.add(step.value)

    @property
    def has_side_effects(self) -> bool:
        return bool(self.completed & SIDE_EFFECT_STEPS)


@dataclass
class CreationOutcome:
    """Result of a creation or retry attempt, with recovery hints for the UI."""

    success: bool
    message: str
    failed_step: str = ""
    has_side_effects: bool = False
    can_retry: bool = False
    can_rollback: bool = False
    context: Optional[CreationContext] = None
