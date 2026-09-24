# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/artist_workers.py
# Architectural role: Thin QThread adapters for the artist dashboard
# =========================================================================================

"""Artist dashboard workers (fetch tasks, install workspace, launch DCC)."""

from pathlib import Path

from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker

from src.application.services.installation_service import InstallationService
from src.application.services.production_service import ProductionService
from src.application.services.task_file_sync_service import TaskFileSyncService


class FetchArtistTasksWorker(ManagedWorker):
    """Asynchronously fetches the tasks assigned to the current user."""

    data_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, production_service: ProductionService) -> None:
        super().__init__()
        self.production_service = production_service

    def run(self) -> None:
        try:
            tasks = self.production_service.get_artist_task_board()
            self.data_ready.emit(tasks)
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))


class InstallProjectWorker(ManagedWorker):
    """Runs the local installation engine without freezing the UI."""

    progress_updated = Signal(str, str)
    finished_install = Signal(bool, str)

    def __init__(
        self,
        project_root: Path,
        vcs_user: str,
        vcs_pwd: str,
        installation_service: InstallationService,
        task_data: dict,
    ) -> None:
        super().__init__()
        self.project_root = project_root
        self.vcs_user = vcs_user
        self.vcs_pwd = vcs_pwd
        self.installation_service = installation_service
        self.task_data = task_data

    def run(self) -> None:
        try:
            total_steps = 7
            current_step = 0

            def progress_interceptor(message: str, color: str) -> None:
                nonlocal current_step
                trigger_words = [
                    "Reading structural",
                    "Synchronizing",
                    "Extracting",
                    "Injecting",
                    "Deploying",
                    "Configuring",
                    "Generating",
                ]
                if any(word in message for word in trigger_words):
                    current_step += 1

                percent = int((current_step / total_steps) * 100)
                if percent > 100:
                    percent = 100
                self.progress_updated.emit(f"⏳ {percent}% - {message}", "yellow")

            success, message = self.installation_service.instalar_entorno(
                project_root=self.project_root,
                vcs_user=self.vcs_user,
                vcs_pwd=self.vcs_pwd,
                status_callback=progress_interceptor,
                user_role="artist",
                task_metadata=self.task_data,
            )

            self.finished_install.emit(success, message)
        except Exception as error:  # noqa: BLE001
            self.finished_install.emit(False, str(error))


class LaunchTaskWorker(ManagedWorker):
    """Launches Blender in a background thread without freezing the UI."""

    finished_launch = Signal(bool, str)

    def __init__(self, kwargs: dict) -> None:
        super().__init__()
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            from src.infrastructure.env_launcher import lanzar_blender

            lanzar_blender(**self.kwargs)
            self.finished_launch.emit(True, "DCC session finished and lock released.")
        except Exception as error:  # noqa: BLE001
            self.finished_launch.emit(False, f"Error launching DCC: {str(error)}")


class CheckVcsChangesWorker(ManagedWorker):
    """Scans the project VCS workspace for uncommitted local changes."""

    changes_ready = Signal(str, list)  # (task_id, list[FileChange])
    error_occurred = Signal(str)

    def __init__(
        self,
        sync_service: TaskFileSyncService,
        task_id: str,
        project_root: Path,
    ) -> None:
        super().__init__()
        self.sync_service = sync_service
        self.task_id = task_id
        self.project_root = project_root

    def run(self) -> None:
        try:
            changes = self.sync_service.scan_local_changes(self.project_root)
            self.changes_ready.emit(self.task_id, changes)
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))


class UpdateVcsWorker(ManagedWorker):
    """Pulls the latest VCS revision into the project workspace off the UI thread."""

    finished_update = Signal(str, bool, str)  # (project_id, success, message)

    def __init__(
        self,
        sync_service: TaskFileSyncService,
        project_id: str,
        project_root: Path,
        username: str,
        password: str,
    ) -> None:
        super().__init__()
        self.sync_service = sync_service
        self.project_id = project_id
        self.project_root = project_root
        self.username = username
        self.password = password

    def run(self) -> None:
        try:
            success, message = self.sync_service.update_working_copy(
                project_root=self.project_root,
                username=self.username,
                password=self.password,
            )
            self.finished_update.emit(self.project_id, success, message)
        except Exception as error:  # noqa: BLE001
            self.finished_update.emit(self.project_id, False, str(error))


class PublishVcsChangesWorker(ManagedWorker):
    """Commits the selected task files to the VCS without freezing the UI."""

    finished_publish = Signal(str, bool, str)  # (task_id, success, message)

    def __init__(
        self,
        sync_service: TaskFileSyncService,
        task_id: str,
        project_root: Path,
        selected_paths: list,
        unversioned_paths: list,
        username: str,
        password: str,
        message: str,
    ) -> None:
        super().__init__()
        self.sync_service = sync_service
        self.task_id = task_id
        self.project_root = project_root
        self.selected_paths = selected_paths
        self.unversioned_paths = unversioned_paths
        self.username = username
        self.password = password
        self.message = message

    def run(self) -> None:
        try:
            success, message = self.sync_service.publish(
                project_root=self.project_root,
                selected_paths=self.selected_paths,
                unversioned_paths=self.unversioned_paths,
                username=self.username,
                password=self.password,
                message=self.message,
            )
            self.finished_publish.emit(self.task_id, success, message)
        except Exception as error:  # noqa: BLE001
            self.finished_publish.emit(self.task_id, False, str(error))
