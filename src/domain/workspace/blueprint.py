# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/workspace/blueprint.py
# Architectural role: Workspace aggregate (ProjectBlueprint)
# =========================================================================================

"""Project blueprint (the ``project_init.json`` aggregate).

Written by ``ProjectBuilder`` and read by ``LocalInstaller`` / ``env_launcher``
to know a project's Blender version, template, dependencies, and topography.
"""

from dataclasses import dataclass, field
from typing import Any, Dict

from .topography import WorkspaceTopography


@dataclass
class ProjectBlueprint:
    project_name: str = ""
    kitsu_project_id: str = ""
    blender_version: str = ""
    template: str = ""
    dependencies: Dict[str, Any] = field(default_factory=dict)
    topography: WorkspaceTopography = field(default_factory=WorkspaceTopography)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectBlueprint":
        data = data or {}
        version_locking = data.get("version_locking") or {}
        return cls(
            project_name=data.get("project_name") or "",
            kitsu_project_id=data.get("kitsu_project_id") or "",
            blender_version=version_locking.get("blender_version") or data.get("blender_version") or "",
            template=data.get("template") or "",
            dependencies=data.get("dependencies") or {},
            topography=WorkspaceTopography.from_dict(data.get("topography_signature") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "kitsu_project_id": self.kitsu_project_id,
            "blender_version": self.blender_version,
            "template": self.template,
            "dependencies": self.dependencies,
            "topography_signature": {
                "vfs_svn": self.topography.vfs_svn,
                "vfs_shared": self.topography.vfs_shared,
                "vfs_local": self.topography.vfs_local,
                "vfs_pipeline": self.topography.vfs_pipeline,
            },
        }
