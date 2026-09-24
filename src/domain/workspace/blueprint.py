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
from typing import Any, Dict, Optional

from src.domain.shared_kernel.addon_contract import (
    ADDON_CONFIGURATION_KEY,
    AddonConfiguration,
    default_addon_configuration,
    parse_addon_configuration,
    serialize_addon_configuration,
)

from .topography import WorkspaceTopography


@dataclass
class ProjectBlueprint:
    project_name: str = ""
    kitsu_project_id: str = ""
    blender_version: str = ""
    template: str = ""
    dependencies: Dict[str, Any] = field(default_factory=dict)
    addon_configuration: Dict[str, AddonConfiguration] = field(default_factory=dict)
    topography: WorkspaceTopography = field(default_factory=WorkspaceTopography)
    vcs_enabled: bool = True
    # Per-project VCS binding (e.g. after a local -> remote migration). An empty
    # ``vcs_server_id`` means "use the resolved/global default server", and an
    # empty ``vcs_base_url`` means "use that server's configured URL".
    vcs_server_id: str = ""
    vcs_base_url: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectBlueprint":
        data = data or {}
        version_locking = data.get("version_locking") or {}
        dependencies = data.get("dependencies") or {}
        raw_addon_config: Optional[Dict[str, Any]] = data.get(ADDON_CONFIGURATION_KEY)
        if raw_addon_config is None:
            # Legacy blueprint: derive an enabled skeleton from the add-on deps.
            addon_configuration = default_addon_configuration(dependencies)
        else:
            addon_configuration = parse_addon_configuration(raw_addon_config)
        return cls(
            project_name=data.get("project_name") or "",
            kitsu_project_id=data.get("kitsu_project_id") or "",
            blender_version=version_locking.get("blender_version") or data.get("blender_version") or "",
            template=data.get("template") or "",
            dependencies=dependencies,
            addon_configuration=addon_configuration,
            topography=WorkspaceTopography.from_dict(data.get("topography_signature") or {}),
            vcs_server_id=data.get("vcs_server_id") or "",
            vcs_base_url=data.get("vcs_base_url") or "",
        )

    @staticmethod
    def is_valid(data: Any) -> bool:
        """Validate the raw blueprint schema. All fields are mandatory."""
        if not isinstance(data, dict):
            return False

        version_locking = data.get("version_locking")
        if version_locking is not None and not isinstance(version_locking, dict):
            return False

        blender_version = (version_locking or {}).get("blender_version") or data.get("blender_version")
        dependencies = data.get("dependencies")
        topography = data.get("topography_signature")

        for field in ("project_name", "kitsu_project_id", "template"):
            value = data.get(field)
            if not isinstance(value, str) or not value:
                return False

        if not isinstance(blender_version, str) or not blender_version:
            return False
        if not isinstance(dependencies, dict):
            return False
        addon_configuration = data.get(ADDON_CONFIGURATION_KEY)
        if addon_configuration is not None and not isinstance(addon_configuration, dict):
            return False
        if not isinstance(topography, dict):
            return False

        for key in ("vfs_svn", "vfs_shared", "vfs_local", "vfs_pipeline"):
            value = topography.get(key)
            if not isinstance(value, str) or not value:
                return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "kitsu_project_id": self.kitsu_project_id,
            "blender_version": self.blender_version,
            "template": self.template,
            "dependencies": self.dependencies,
            ADDON_CONFIGURATION_KEY: serialize_addon_configuration(self.addon_configuration),
            "topography_signature": {
                "vfs_svn": self.topography.vfs_svn,
                "vfs_shared": self.topography.vfs_shared,
                "vfs_local": self.topography.vfs_local,
                "vfs_pipeline": self.topography.vfs_pipeline,
                "custom_dirs": list(self.topography.custom_dirs),
            },
            "vcs_base_url": self.vcs_base_url,
            "vcs_server_id": self.vcs_server_id,
        }
