# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/artist_workers.py
# Architectural role: Thin QThread adapters for the artist dashboard
# =========================================================================================

"""Artist dashboard workers (fetch tasks, install workspace, launch DCC)."""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from src.application.services.installation_service import InstallationService
from src.application.services.production_service import ProductionService


class FetchArtistTasksWorker(QThread):
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


class InstallProjectWorker(QThread):
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


class LaunchTaskWorker(QThread):
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
