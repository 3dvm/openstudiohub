# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/vcs_router.py
# Rol Arquitectónico: VCS Layer Router / Factory
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.8.0
# =========================================================================================

"""
Main router for the VCS layer. Instantiates and returns the correct adapter
based on the configuration extracted from the ConfigFactory.
Anchored to English standard.
"""

from pathlib import Path
from .abstract_vcs import AbstractVCS
from .svn_adapter import SVNAdapter
from .git_lfs_adapter import GitLFSAdapter

class VCSRouter:
    """
    Main router for the VCS layer. Instantiates and returns the correct adapter
    based on the configuration extracted from the ConfigFactory.
    """
    def __init__(self, vcs_type: str, repo_url: str, workspace_dir: Path):
        self.vcs_type = vcs_type.lower()
        self.repo_url = repo_url
        self.workspace_dir = workspace_dir
        self._ensure_workspace()

    def _ensure_workspace(self):
        """Ensures the destination folder exists before operating."""
        if not self.workspace_dir.exists():
            self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def get_adapter(self) -> AbstractVCS:
        """
        Returns the instance of the concrete adapter to use.
        """
        if self.vcs_type == "svn":
            return SVNAdapter(self.repo_url, self.workspace_dir)
        elif self.vcs_type == "git-lfs":
            return GitLFSAdapter(self.repo_url, self.workspace_dir)
        else:
            raise ValueError(f"Unsupported or unknown VCS engine: '{self.vcs_type}'")
