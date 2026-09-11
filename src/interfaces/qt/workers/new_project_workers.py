# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/new_project_workers.py
# Architectural role: Thin QThread adapters for the project creation dialog
# =========================================================================================

"""Project creation workers (Kitsu templates + heavy creation I/O)."""

from PySide6.QtCore import QThread, Signal

from src.application.services.project_creation_service import ProjectCreationService


class FetchKitsuTemplatesWorker(QThread):
    """Fetches the available Kitsu project templates."""

    data_ready = Signal(list)

    def __init__(self, production_service) -> None:
        super().__init__()
        self.production_service = production_service

    def run(self) -> None:
        try:
            self.data_ready.emit(self.production_service.list_templates())
        except Exception as error:  # noqa: BLE001
            print(f"[FetchKitsuTemplatesWorker] Network error: {error}")
            self.data_ready.emit([])


class ProjectCreationWorker(QThread):
    """Runs the heavy project creation I/O without freezing the modal."""

    result = Signal(bool, str)

    def __init__(
        self,
        project_creation_service: ProjectCreationService,
        name: str,
        version: str,
        dependencies: dict,
        kitsu_template: str,
        splash: str,
        vcs_user: str,
        vcs_pwd: str,
        vcs_enabled: bool,
    ) -> None:
        super().__init__()
        self.project_creation_service = project_creation_service
        self.name = name
        self.version = version
        self.dependencies = dependencies
        self.template = kitsu_template
        self.splash = splash
        self.vcs_user = vcs_user
        self.vcs_pwd = vcs_pwd
        self.vcs_enabled = vcs_enabled

    def run(self) -> None:
        ok, message = self.project_creation_service.create_project(
            project_name=self.name,
            blender_version=self.version,
            dependencies=self.dependencies,
            kitsu_template=self.template,
            splash_image_path=self.splash,
            vcs_user=self.vcs_user,
            vcs_pwd=self.vcs_pwd,
            vcs_enabled=self.vcs_enabled,
        )
        self.result.emit(ok, message)
