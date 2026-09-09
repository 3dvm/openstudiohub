# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/composition.py
# Architectural role: Composition root (dependency wiring)
# =========================================================================================

"""Composition root for the presentation layer.

Constructs the application/infrastructure services once and exposes the
ViewModels and the shared ``StatusSink``. The ``OpenStudioHub`` main window
builds the actual View widgets from this context.
"""

from pathlib import Path

from src.application.credential_vault import CredentialVault
from src.application.services.auth_service import AuthService
from src.application.services.installation_service import InstallationService
from src.application.services.production_service import ProductionService
from src.application.services.project_audit_service import ProjectAuditService
from src.application.services.project_creation_service import ProjectCreationService
from src.application.services.project_repair_service import ProjectRepairService
from src.application.services.vault_service import VaultService
from src.infrastructure.config_factory import ConfigFactory
from src.infrastructure.kitsu_manager import KitsuManager
from src.infrastructure.nas_manager import NasManager
from src.infrastructure.session_repository import FileSessionRepository
from src.infrastructure.vault_manifest_repository import FileVaultManifestRepository
from src.infrastructure.vcs.vcs_router import VCSRouter
from src.interfaces.qt.viewmodels.base_viewmodel import StatusSink
from src.interfaces.qt.viewmodels.project_audit_viewmodel import ProjectAuditViewModel
from src.interfaces.qt.viewmodels.project_repair_viewmodel import ProjectRepairViewModel


class AppContext:
    def __init__(self, settings_path: Path) -> None:
        self.config_factory = ConfigFactory(settings_path)

        self.kitsu = KitsuManager()
        self.auth_service = AuthService(self.kitsu, FileSessionRepository())
        self.production_service = ProductionService(self.kitsu)

        self.vault_service = VaultService(FileVaultManifestRepository(self.config_factory.get_vault_path()))
        self.installation_service = InstallationService(self.config_factory, self.config_factory.get_vault_path())
        self.project_creation_service = ProjectCreationService(self.config_factory)

        self.credential_vault = CredentialVault()

        self.nas_manager = NasManager(self.config_factory.get_workspace_root())

        self.vcs_router = VCSRouter(
            vcs_type=self.config_factory.get_vcs_adapter_type(),
            repo_url=self.config_factory.get_vcs_repository_url(),
            workspace_dir=self.config_factory.get_workspace_root(),
        )

        # Application services for the future audit/repair use cases.
        self.audit_service = ProjectAuditService(self.nas_manager, self.kitsu)
        self.repair_service = ProjectRepairService(self.kitsu, self.nas_manager, self.config_factory)

        # Shared status channel for the dashboard ViewModels.
        self.status_sink = StatusSink()

        # ViewModels for the upcoming audit/repair features (Phase 2 wiring).
        self.audit_viewmodel = ProjectAuditViewModel(self.audit_service, self.status_sink)
        self.repair_viewmodel = ProjectRepairViewModel(self.repair_service, self.credential_vault, self.status_sink)
