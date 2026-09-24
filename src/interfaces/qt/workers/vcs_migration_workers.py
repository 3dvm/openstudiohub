# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/vcs_migration_workers.py
# Architectural role: Thin QThread adapters for VCS migration
# =========================================================================================

"""Background workers for local -> remote VCS repository migration."""

from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker


class VCSMigrationWorker(ManagedWorker):
    """Migrates a single project repository to the remote VCS server."""

    progress_update = Signal(str, str)
    finished_migration = Signal(str, bool, str)  # (project_name, success, message)

    def __init__(self, migration_service, project_name: str, project_root, vcs_user: str, vcs_pwd: str, delete_old: bool = False) -> None:
        super().__init__()
        self.migration_service = migration_service
        self.project_name = project_name
        self.project_root = project_root
        self.vcs_user = vcs_user
        self.vcs_pwd = vcs_pwd
        self.delete_old = delete_old

    def run(self) -> None:
        try:
            success, message = self.migration_service.migrate_project(
                self.project_root,
                vcs_user=self.vcs_user,
                vcs_pwd=self.vcs_pwd,
                delete_old_repo=self.delete_old,
            )
        except Exception as error:  # noqa: BLE001
            success, message = False, f"Migration crashed: {error}"
        self.finished_migration.emit(self.project_name, success, message)


class VCSLocalCleanupWorker(ManagedWorker):
    """Deletes the old local Docker repository after a successful migration."""

    finished_cleanup = Signal(str, bool, str)  # (project_name, success, message)

    def __init__(self, migration_service, project_name: str) -> None:
        super().__init__()
        self.migration_service = migration_service
        self.project_name = project_name

    def run(self) -> None:
        try:
            success, message = self.migration_service.delete_local_repository(self.project_name)
        except Exception as error:  # noqa: BLE001
            success, message = False, f"Cleanup crashed: {error}"
        self.finished_cleanup.emit(self.project_name, success, message)
