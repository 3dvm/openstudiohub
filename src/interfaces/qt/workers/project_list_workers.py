# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/project_list_workers.py
# Architectural role: Thin QThread adapters for the project grid
# =========================================================================================

"""Project grid workers."""

import shutil
from pathlib import Path

from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker

from src.application.services.installation_service import InstallationService
from src.application.services.production_service import ProductionService


class ProjectInstallWorker(ManagedWorker):
    """Runs the workspace installation for a project without freezing the UI."""

    progress_update = Signal(str, str)
    progress = Signal(int)
    finished_install = Signal(bool, str)

    def __init__(self, installation_service: InstallationService, project_root, vcs_user: str, vcs_pwd: str, user_role: str) -> None:
        super().__init__()
        self.installation_service = installation_service
        self.project_root = project_root
        self.vcs_user = vcs_user
        self.vcs_pwd = vcs_pwd
        self.user_role = user_role

    def run(self) -> None:
        success, msg = self.installation_service.instalar_entorno(
            project_root=self.project_root,
            vcs_user=self.vcs_user,
            vcs_pwd=self.vcs_pwd,
            status_callback=self._emit_status,
            user_role=self.user_role,
            progress_callback=self.progress.emit,
        )
        self.finished_install.emit(success, msg)

    def _emit_status(self, message: str, color: str) -> None:
        self.progress_update.emit(message, color)


class ResetWorkingCopyWorker(ManagedWorker):
    """Deletes the project's VCS working copy and re-checks it out cleanly.

    Used to recover from a conflicted working copy (e.g. an old import that
    pre-created ``<vfs_svn>/*`` folders before the checkout).
    """

    progress_update = Signal(str, str)
    progress = Signal(int)
    finished_reset = Signal(bool, str)

    def __init__(
        self,
        installation_service: InstallationService,
        project_root,
        vfs_svn: str,
        vcs_user: str,
        vcs_pwd: str,
        user_role: str,
    ) -> None:
        super().__init__()
        self.installation_service = installation_service
        self.project_root = Path(project_root)
        self.vfs_svn = vfs_svn
        self.vcs_user = vcs_user
        self.vcs_pwd = vcs_pwd
        self.user_role = user_role

    def run(self) -> None:
        try:
            workspace = self.project_root / self.vfs_svn
            if workspace.exists():
                self.progress_update.emit(
                    f"Removing the local working copy '{self.vfs_svn}'...", "yellow"
                )
                shutil.rmtree(workspace)
            success, message = self.installation_service.instalar_entorno(
                project_root=self.project_root,
                vcs_user=self.vcs_user,
                vcs_pwd=self.vcs_pwd,
                status_callback=self.progress_update.emit,
                user_role=self.user_role,
                progress_callback=self.progress.emit,
            )
        except Exception as error:  # noqa: BLE001
            success, message = False, f"Reset failed: {error}"
        self.finished_reset.emit(success, message)


class ProjectGridWorker(ManagedWorker):
    """Fetches the studio's open projects from Kitsu."""

    data_ready = Signal(list)

    def __init__(self, production_service: ProductionService) -> None:
        super().__init__()
        self.production_service = production_service

    def run(self) -> None:
        try:
            projects = self.production_service.list_open_projects()
            self.data_ready.emit(projects)
        except Exception as error:  # noqa: BLE001
            print(f"[ProjectList] Error retrieving projects: {error}")
            self.data_ready.emit([])
