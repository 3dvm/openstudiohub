# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/infrastructure_workers.py
# Architectural role: Thin QThread adapters for the infrastructure panel
# =========================================================================================

"""Infrastructure workers (Docker lifecycle and database seeders)."""

import subprocess
from pathlib import Path

from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker

from src.infrastructure.dev_defaults import (
    DEV_KITSU_ADMIN_EMAIL,
    DEV_KITSU_ADMIN_PASSWORD,
)


class DockerWorker(ManagedWorker):
    """Runs Docker commands without freezing the UI while images download."""

    finished_signal = Signal(bool, str)

    def __init__(self, command: list, cwd: Path | None = None) -> None:
        super().__init__()
        self.command = command
        self.cwd = cwd

    def run(self) -> None:
        try:
            subprocess.run(
                self.command,
                cwd=self.cwd,
                check=True,
                capture_output=True,
                text=True,
            )
            self.finished_signal.emit(True, "Operation completed successfully.")
        except subprocess.CalledProcessError as error:
            error_msg = error.stderr if error.stderr else str(error)
            self.finished_signal.emit(False, f"Docker failure: {error_msg}")
        except Exception as error:  # noqa: BLE001
            self.finished_signal.emit(False, f"System error: {str(error)}")


class KitsuSeederWorker(ManagedWorker):
    """Interacts with the Kitsu database through Gazu and the CLI."""

    finished_signal = Signal(bool, str)

    def __init__(self, production_service, action: str) -> None:
        super().__init__()
        self.production_service = production_service
        self.action = action

    def run(self) -> None:
        try:
            if self.action == "admin":
                pwd = DEV_KITSU_ADMIN_PASSWORD
                cmd = [
                    "docker",
                    "exec",
                    "kitsu_local-zou-app",
                    "zou",
                    "create-admin",
                    DEV_KITSU_ADMIN_EMAIL,
                    "--password",
                    pwd,
                ]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                self.finished_signal.emit(
                    True, f"Admin created: {DEV_KITSU_ADMIN_EMAIL} / {DEV_KITSU_ADMIN_PASSWORD}"
                )

            elif self.action == "dummy":
                self.production_service.set_host("http://localhost:8080/api")
                success, msg = self.production_service.seed_test_database(
                    admin_email=DEV_KITSU_ADMIN_EMAIL,
                    admin_pwd=DEV_KITSU_ADMIN_PASSWORD,
                )
                self.finished_signal.emit(success, msg)

        except subprocess.CalledProcessError as error:
            error_msg = error.stderr if error.stderr else str(error)
            self.finished_signal.emit(False, f"Container error: {error_msg}")
        except Exception as error:  # noqa: BLE001
            self.finished_signal.emit(False, f"Seeder failure: {str(error)}")
