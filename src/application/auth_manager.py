# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/auth_manager.py
# Architectural role: Backward-compatible facade (Identity)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. All rights reserved.
# License: GNU General Public License v3.0 (GPLv3)
# =========================================================================================

"""
Backward-compatible facade over the identity services.

The RBAC mapping, session persistence, and Kitsu query logic have been moved out
into the domain (``Role``/``User``) and the application services
(``AuthService`` / ``ProductionService``). This class only *delegates*, so the
existing UI consumers keep working while they are migrated to depend on the
services directly.
"""

from typing import Dict, List, Optional, Tuple

from src.application.ports import SessionRepository
from src.application.services.auth_service import AuthService
from src.application.services.production_service import ProductionService
from src.infrastructure.kitsu_manager import KitsuManager
from src.infrastructure.session_repository import FileSessionRepository


class AuthManager:
    """Thin facade: auth -> AuthService, production queries -> ProductionService."""

    def __init__(
        self,
        auth_service: Optional[AuthService] = None,
        production_service: Optional[ProductionService] = None,
    ) -> None:
        if auth_service is None or production_service is None:
            kitsu = KitsuManager()
            auth_service = auth_service or AuthService(kitsu, FileSessionRepository())
            production_service = production_service or ProductionService(kitsu)
        self.auth_service = auth_service
        self.production_service = production_service
        self.kitsu = auth_service.kitsu

    # ------------------------------------------------------------------
    # Legacy passthrough state (read by the UI)
    # ------------------------------------------------------------------
    @property
    def user_data(self) -> Optional[dict]:
        return self.auth_service.raw_user_data

    @property
    def kitsu_host(self) -> str:
        return self.auth_service.host

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def set_host(self, host_url: str) -> None:
        self.auth_service.set_host(host_url)

    def login_with_credentials(self, email: str, password: str, host_url: str) -> Tuple[bool, str]:
        return self.auth_service.login(email, password, host_url)

    def login_with_saved_session(self) -> bool:
        return self.auth_service.restore_session()

    def logout(self) -> None:
        self.auth_service.logout()

    def get_user_role(self) -> str:
        return self.auth_service.current_role().value

    def get_user_position(self) -> str:
        user = self.auth_service.current_user
        return user.position if user else ""

    def get_current_token(self) -> str:
        return self.auth_service.access_token()

    # ------------------------------------------------------------------
    # Production queries (delegated; Phase 3 moves these behind a repository)
    # ------------------------------------------------------------------
    def sync_studio_identity(self) -> dict:
        return self.production_service.sync_studio_identity()

    def obtener_proyectos_activos(self) -> Dict[str, str]:
        return self.production_service.obtener_proyectos_activos()

    def get_task_metadata(self, task_id: str) -> Optional[Dict[str, str]]:
        return self.production_service.get_task_metadata(task_id)

    def get_assigned_tasks(self) -> List[dict]:
        return self.production_service.get_assigned_tasks()

    def get_recent_activity(self, limit: int = 15) -> List[dict]:
        return self.production_service.get_recent_activity(limit)

    def acknowledge_activity(self, task_id: str, comment_id: str) -> bool:
        return self.production_service.acknowledge_activity(task_id, comment_id)
