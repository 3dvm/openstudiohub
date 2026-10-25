# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/vcs_migration_workers.py
# Architectural role: Thin QThread adapters for VCS migration
# =========================================================================================

"""Background workers for local -> remote VCS repository migration."""

from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker


class VCSMigrationWorker(ManagedWorker):
    """Migrates a single project repository to the chosen VCS server."""

    progress_update = Signal(str, str)
    finished_migration = Signal(str, bool, str)  # (project_name, success, message)

    def __init__(self, migration_service, project_name: str, project_root, vcs_user: str, vcs_pwd: str, delete_old: bool = False, target_server_id: str = "") -> None:
        super().__init__()
        self.migration_service = migration_service
        self.project_name = project_name
        self.project_root = project_root
        self.vcs_user = vcs_user
        self.vcs_pwd = vcs_pwd
        self.delete_old = delete_old
        self.target_server_id = target_server_id

    def run(self) -> None:
        try:
            success, message = self.migration_service.migrate_project(
                self.project_root,
                vcs_user=self.vcs_user,
                vcs_pwd=self.vcs_pwd,
                delete_old_repo=self.delete_old,
                target_server_id=self.target_server_id,
            )
        except Exception as error:  # noqa: BLE001
            success, message = False, f"Migration crashed: {error}"
        self.finished_migration.emit(self.project_name, success, message)


class VCSLocalCleanupWorker(ManagedWorker):
    """Deletes the old repository on a source server after a successful migration."""

    finished_cleanup = Signal(str, bool, str)  # (project_name, success, message)

    def __init__(self, migration_service, project_name: str, server_id: str = "") -> None:
        super().__init__()
        self.migration_service = migration_service
        self.project_name = project_name
        self.server_id = server_id

    def run(self) -> None:
        try:
            if self.server_id:
                success, message = self.migration_service.delete_repository(self.server_id, self.project_name)
            else:
                success, message = self.migration_service.delete_local_repository(self.project_name)
        except Exception as error:  # noqa: BLE001
            success, message = False, f"Cleanup crashed: {error}"
        self.finished_cleanup.emit(self.project_name, success, message)


class ApplyVcsPolicyWorker(ManagedWorker):
    """Installs or refreshes the server-side SVN lock policy for a project."""

    finished_policy = Signal(str, bool, str)  # (project_name, success, message)

    def __init__(self, migration_service, project_name: str, project_root=None) -> None:
        super().__init__()
        self.migration_service = migration_service
        self.project_name = project_name
        self.project_root = project_root

    def run(self) -> None:
        try:
            success, message = self.migration_service.apply_policy(
                self.project_name, self.project_root
            )
        except Exception as error:  # noqa: BLE001
            success, message = False, f"Policy update crashed: {error}"
        self.finished_policy.emit(self.project_name, success, message)


class ListVcsLocksWorker(ManagedWorker):
    """List repository locks for a project."""

    locks_ready = Signal(str, bool, list, str)  # (project_name, ok, locks, message)

    def __init__(self, migration_service, project_name: str, project_root=None) -> None:
        super().__init__()
        self.migration_service = migration_service
        self.project_name = project_name
        self.project_root = project_root

    def run(self) -> None:
        try:
            ok, locks, message = self.migration_service.list_locks(
                self.project_name, self.project_root
            )
        except Exception as error:  # noqa: BLE001
            ok, locks, message = False, [], str(error)
        self.locks_ready.emit(self.project_name, ok, locks, message)


class BreakVcsLockWorker(ManagedWorker):
    """Remove a repository lock as a TD administrator."""

    finished_break = Signal(str, str, bool, str)  # (project_name, path, ok, message)

    def __init__(self, migration_service, project_name: str, project_root, path: str) -> None:
        super().__init__()
        self.migration_service = migration_service
        self.project_name = project_name
        self.project_root = project_root
        self.path = path

    def run(self) -> None:
        try:
            ok, message = self.migration_service.break_lock(
                self.project_name, self.project_root, self.path
            )
        except Exception as error:  # noqa: BLE001
            ok, message = False, str(error)
        self.finished_break.emit(self.project_name, self.path, ok, message)
