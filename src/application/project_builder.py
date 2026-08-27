# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/project_builder.py
# Architectural role: Deprecated facade over ProjectCreationService
# =========================================================================================

"""DEPRECATED facade.

The project-creation saga now lives in
``src.application.services.project_creation_service.ProjectCreationService``.
This class keeps the legacy ``ProjectBuilder`` API for ``window_new_project``.
"""

from pathlib import Path

from src.application.services.project_creation_service import ProjectCreationService


class ProjectBuilder:
    def __init__(self, config_factory) -> None:
        self.config_factory = config_factory
        self._service = ProjectCreationService(config_factory)

    @property
    def base_dir(self) -> Path:
        return self.config_factory.get_workspace_root()

    @property
    def vault_root(self) -> Path:
        return self.config_factory.get_vault_path()

    @property
    def vault_templates_dir(self) -> Path:
        return self.vault_root / "project_templates"

    @property
    def vault_blender_dir(self) -> Path:
        return self.vault_root / "blender_versions"

    def create_project(self, *args, **kwargs):
        return self._service.create_project(*args, **kwargs)
