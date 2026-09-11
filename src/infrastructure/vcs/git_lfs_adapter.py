# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/vcs_adapters/git_lfs_adapter.py
# Rol Arquitectónico: Adaptador VCS / Capa de Abstracción
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.5.0
# =========================================================================================

"""
Concrete adapter for Git LFS operations.
(Currently in 'NotImplemented' state preparing for future support).
Anchored to English standard.
"""

from typing import List, Dict, Optional
from pathlib import Path
from .abstract_vcs import AbstractVCS

class GitLFSAdapter(AbstractVCS):
    """
    Concrete adapter for Git LFS operations.
    (Currently in 'NotImplemented' state preparing for future support).
    """

    def full_pull(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        raise NotImplementedError("Git LFS support is currently under development.")

    def sparse_pull(self, paths: List[str], username: Optional[str] = None, password: Optional[str] = None) -> bool:
        # According to SDD 3.3: git clone --filter=blob:none --sparse
        raise NotImplementedError("Git LFS support is currently under development.")

    def commit(self, message: str, paths: Optional[List[str]] = None, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        raise NotImplementedError("Git LFS support is currently under development.")

    def lock(self, path: str, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        raise NotImplementedError("Git LFS support is currently under development.")

    def unlock(self, path: str, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        raise NotImplementedError("Git LFS support is currently under development.")

    def revert(self, path: str) -> bool:
        raise NotImplementedError("Git LFS support is currently under development.")

    def get_status(self) -> Dict[str, str]:
        raise NotImplementedError("Git LFS support is currently under development.")

    def set_needs_lock(self, path: str) -> bool:
        raise NotImplementedError("Git LFS support is currently under development.")

    def cleanup(self) -> bool:
        raise NotImplementedError("Git LFS support is currently under development.")

    def setup_ignore(self, patterns: List[str]) -> bool:
        raise NotImplementedError("Git LFS support is currently under development.")

    def add_all(self, path: str = ".") -> bool:
        raise NotImplementedError("Git LFS support is currently under development.")

    def create_server_repository(self, project_name: str, vfs_svn: str) -> bool:
        raise NotImplementedError("Git LFS support is currently under development.")
