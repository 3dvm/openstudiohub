# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/local_installer.py
# Architectural role: Deprecated facade over InstallationService
# =========================================================================================

"""DEPRECATED facade.

The workspace-installation saga now lives in
``src.application.services.installation_service.InstallationService``. This
class keeps the legacy ``LocalInstaller`` API for ``view_artist``,
``project_card`` and ``widget_task_list``.
"""

from pathlib import Path
from typing import Optional, Tuple

from src.application.services.installation_service import InstallationService


class LocalInstaller:
    def __init__(self, projects_dir: Path, config_factory) -> None:
        self.projects_dir = projects_dir
        self.config_factory = config_factory

        try:
            vault_root = self.config_factory.get_workspace_root() / "openstudio_vault"
        except Exception:
            vault_root = self.projects_dir.parent / "openstudio_vault"

        self._service = InstallationService(config_factory, vault_root)

    def verificar_instalacion(self, project_root: Path) -> bool:
        vfs_local = self.config_factory.get_vfs_local_name()
        vfs_svn = self.config_factory.get_vfs_svn_name()

        config_local = project_root / vfs_local / "project_config.json"
        vcs_dir = project_root / vfs_svn
        return config_local.exists() and vcs_dir.exists()

    def instalar_entorno(self, *args, **kwargs) -> Tuple[bool, str]:
        return self._service.instalar_entorno(*args, **kwargs)

    def _get_os_info(self) -> Tuple[str, str]:
        return self._service._get_os_info()
