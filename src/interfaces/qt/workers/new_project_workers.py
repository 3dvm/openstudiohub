# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/new_project_workers.py
# Architectural role: Thin QThread adapters for the project creation dialog
# =========================================================================================

"""Project creation workers (Kitsu templates + heavy creation I/O)."""

from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker

from src.application.services.creation_saga import CreationContext
from src.application.services.project_creation_service import ProjectCreationService


class FetchKitsuTemplatesWorker(ManagedWorker):
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


class ProjectCreationWorker(ManagedWorker):
    """Runs the heavy project creation I/O without freezing the modal."""

    result = Signal(object)

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
        addon_configuration: dict | None = None,
        server_id: str = "",
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
        self.addon_configuration = addon_configuration
        self.server_id = server_id

    def run(self) -> None:
        outcome = self.project_creation_service.create_project(
            project_name=self.name,
            blender_version=self.version,
            dependencies=self.dependencies,
            kitsu_template=self.template,
            splash_image_path=self.splash,
            vcs_user=self.vcs_user,
            vcs_pwd=self.vcs_pwd,
            vcs_enabled=self.vcs_enabled,
            addon_configuration=self.addon_configuration,
            server_id=self.server_id,
        )
        self.result.emit(outcome)


class ProjectCreationRetryWorker(ManagedWorker):
    """Resumes a failed creation from its recorded context."""

    result = Signal(object)

    def __init__(self, project_creation_service: ProjectCreationService, context: CreationContext) -> None:
        super().__init__()
        self.project_creation_service = project_creation_service
        self.context = context

    def run(self) -> None:
        self.result.emit(self.project_creation_service.retry(self.context))


class ProjectRollbackWorker(ManagedWorker):
    """Deletes the data created by a failed project creation."""

    result = Signal(bool, str)

    def __init__(self, project_creation_service: ProjectCreationService, context: CreationContext) -> None:
        super().__init__()
        self.project_creation_service = project_creation_service
        self.context = context

    def run(self) -> None:
        ok, message = self.project_creation_service.rollback(self.context)
        self.result.emit(ok, message)
