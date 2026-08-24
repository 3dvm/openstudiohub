# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/vcs_adapters/abstract_vcs.py
# Rol Arquitectónico: Adaptador VCS / Capa de Abstracción
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.4.2
# =========================================================================================

"""
Interfaz base para todos los adaptadores de Control de Versiones.
Garantiza que cualquier motor (SVN, Git) exponga los mismos métodos al Hub.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pathlib import Path

class AbstractVCS(ABC):
    """
    Interfaz base para todos los adaptadores de Control de Versiones.
    Garantiza que cualquier motor (SVN, Git) exponga los mismos métodos al Hub.
    """
    def __init__(self, repo_url: str, workspace_dir: Path):
        self.repo_url = repo_url
        self.workspace_dir = workspace_dir

    @abstractmethod
    def full_pull(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Descarga o actualiza el repositorio completo."""
        pass

    @abstractmethod
    def sparse_pull(self, paths: List[str], username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Descarga estrictamente las rutas especificadas ignorando el resto (Jailing)."""
        pass

    @abstractmethod
    def commit(self, message: str, paths: Optional[List[str]] = None, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Sube los cambios locales al servidor."""
        pass

    @abstractmethod
    def lock(self, path: str, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Bloquea un archivo en el servidor para evitar conflictos."""
        pass

    @abstractmethod
    def unlock(self, path: str, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Libera un archivo bloqueado en el servidor."""
        pass

    @abstractmethod
    def revert(self, path: str) -> bool:
        """Revierte los cambios locales a la última versión del servidor."""
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, str]:
        """Devuelve el estado de los archivos locales (modificados, añadidos, etc)."""
        pass

    @abstractmethod
    def set_needs_lock(self, path: str) -> bool:
        """
        Aplica la propiedad de bloqueo estricto (ej. svn:needs-lock en SVN) a un archivo o ruta.
        Obliga a que el sistema de archivos local lo marque como Solo Lectura por defecto.
        """
        pass

    @abstractmethod
    def cleanup(self) -> bool:
        """
        Sanea la base de datos interna local del VCS para resolver bloqueos locales (local locks)
        provocados por cortes abruptos de energía, caídas de red o cierres forzados.
        """
        pass

    @abstractmethod
    def setup_ignore(self, patterns: List[str]) -> bool:
        """
        Configura las reglas nativas del motor VCS para ignorar archivos temporales.
        (Ej: Escribir un .gitignore en Git o aplicar svn:ignore en Subversion).
        """
        pass

    @abstractmethod
    def add_all(self, path: str = ".") -> bool:
        """
        Registra todos los archivos nuevos o modificados en la ruta dada, 
        preparándolos para el commit.
        """
        pass

    @abstractmethod
    def create_server_repository(self, project_name: str, vfs_svn: str) -> bool:
        """
        Crea el repositorio remoto en el servidor para el nuevo proyecto 
        e inicializa la topología base si es necesario.
        """
        pass

