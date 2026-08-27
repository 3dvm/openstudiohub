# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/workspace/topography.py
# Architectural role: Workspace value object (semantic VFS topography)
# =========================================================================================

"""Semantic topography of a studio workspace.

The "VFS" folder names (svn / shared / local / pipeline + custom dirs) define
the physical layout of a project on the NAS. This value object is the single
model for that layout, previously spread across ``ConfigFactory`` getters.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class WorkspaceTopography:
    vfs_svn: str = "svn"
    vfs_shared: str = "shared"
    vfs_local: str = "local"
    vfs_pipeline: str = "pipeline"
    custom_dirs: Tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> "WorkspaceTopography":
        data = data or {}
        return cls(
            vfs_svn=data.get("vfs_svn") or "svn",
            vfs_shared=data.get("vfs_shared") or "shared",
            vfs_local=data.get("vfs_local") or "local",
            vfs_pipeline=data.get("vfs_pipeline") or "pipeline",
            custom_dirs=tuple(data.get("custom_dirs") or ()),
        )

    def base_folders(self) -> Tuple[str, ...]:
        """The structural folders created inside a project's SVN root."""
        return (
            f"{self.vfs_svn}/pro",
            f"{self.vfs_svn}/tools",
            f"{self.vfs_svn}/pro/assets",
            f"{self.vfs_svn}/pro/shots",
            f"{self.vfs_svn}/pro/edit",
            f"{self.vfs_svn}/pro/strips",
        ) + self.custom_dirs
