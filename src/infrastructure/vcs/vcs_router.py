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
from typing import Callable, Optional

from .abstract_vcs import AbstractVCS
from .svn_adapter import SVNAdapter
from .git_lfs_adapter import GitLFSAdapter
from src.domain.workspace.vcs_server_profile import VCSServerProfile

PassphraseProvider = Callable[[], Optional[str]]

class VCSRouter:
    """
    Main router for the VCS layer. Instantiates and returns the correct adapter
    based on the configuration extracted from the ConfigFactory.
    """
    def __init__(
        self,
        vcs_type: str,
        repo_url: str,
        workspace_dir: Path,
        server_profile: Optional[VCSServerProfile] = None,
        ssh_passphrase_provider: Optional[PassphraseProvider] = None,
    ):
        self.vcs_type = vcs_type.lower()
        self.repo_url = repo_url
        self.workspace_dir = workspace_dir
        self.server_profile = server_profile or VCSServerProfile()
        self.ssh_passphrase_provider = ssh_passphrase_provider
        self._ensure_workspace()

    def _ensure_workspace(self):
        """Ensures the destination folder exists before operating."""
        if not self.workspace_dir.exists():
            self.workspace_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _build_adapter(
        vcs_type: str,
        repo_url: str,
        workspace_dir: Path,
        server_profile: Optional[VCSServerProfile] = None,
        ssh_passphrase_provider: Optional[PassphraseProvider] = None,
    ) -> AbstractVCS:
        if vcs_type == "svn":
            return SVNAdapter(
                repo_url,
                workspace_dir,
                server_profile=server_profile,
                ssh_passphrase_provider=ssh_passphrase_provider,
            )
        elif vcs_type == "git-lfs":
            return GitLFSAdapter(repo_url, workspace_dir, server_profile=server_profile)
        elif vcs_type == "none":
            return None
        else:
            raise ValueError(f"Unsupported or unknown VCS engine: '{vcs_type}'")

    def get_adapter(self) -> AbstractVCS:
        """
        Returns the instance of the concrete adapter to use.
        """
        return self._build_adapter(
            self.vcs_type,
            self.repo_url,
            self.workspace_dir,
            self.server_profile,
            self.ssh_passphrase_provider,
        )

    @classmethod
    def probe_health(
        cls,
        vcs_type: str,
        repo_url: str,
        username: str = None,
        password: str = None,
        timeout: float = 5.0,
        server_profile: Optional[VCSServerProfile] = None,
        ssh_passphrase_provider: Optional[PassphraseProvider] = None,
    ):
        """
        Side-effect free pre-flight probe for a VCS server.

        Unlike :meth:`check_health`, this does not create the workspace folder, so
        it is safe to run before any project data has been written.
        """
        vcs_type = (vcs_type or "").strip().lower()
        if vcs_type in ("", "none"):
            return True, "VCS disabled (NAS only)."
        adapter = cls._build_adapter(
            vcs_type,
            repo_url,
            Path("."),
            server_profile,
            ssh_passphrase_provider,
        )
        return adapter.check_server_health(username, password, timeout)

    @classmethod
    def destroy_repository(
        cls,
        vcs_type: str,
        repo_url: str,
        project_name: str,
        vfs_svn: str,
        server_profile: Optional[VCSServerProfile] = None,
        ssh_passphrase_provider: Optional[PassphraseProvider] = None,
    ):
        """
        Side-effect free rollback of a server-side repository.

        Uses a throwaway workspace so it does not recreate the project folder
        while the NAS cleanup is in progress.
        """
        vcs_type = (vcs_type or "").strip().lower()
        if vcs_type in ("", "none"):
            return True, "VCS disabled (NAS only)."
        adapter = cls._build_adapter(
            vcs_type,
            repo_url,
            Path("."),
            server_profile,
            ssh_passphrase_provider,
        )
        return adapter.destroy_server_repository(project_name, vfs_svn)

    def check_health(self, username: str = None, password: str = None, timeout: float = 5.0):
        """Pre-flight probe for the configured VCS server."""
        return self.probe_health(
            self.vcs_type,
            self.repo_url,
            username,
            password,
            timeout,
            self.server_profile,
            self.ssh_passphrase_provider,
        )

    def destroy_server_repository(self, project_name: str, vfs_svn: str):
        """Best-effort rollback of the server-side repository."""
        return self.destroy_repository(
            self.vcs_type,
            self.repo_url,
            project_name,
            vfs_svn,
            self.server_profile,
            self.ssh_passphrase_provider,
        )
