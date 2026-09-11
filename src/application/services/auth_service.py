# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/auth_service.py
# Architectural role: Application service / Identity use cases
# =========================================================================================

"""Authentication application service.

Coordinates login / session-restore / logout across the Kitsu gateway
(infrastructure) and the session persistence port, translating the raw Kitsu
person dict into the domain ``User`` entity and publishing identity events.
"""

from typing import Optional, Tuple

from src.infrastructure.kitsu_manager import AuthFailedException, KitsuManager
from src.application.bus import MessageBus
from src.application.ports import SessionRepository
from src.domain.identity.entities import Session, User
from src.domain.identity.events import UserAuthenticated, UserLoggedOut
from src.domain.identity.value_objects import Role


class AuthService:
    """Use cases: login, restore_session, logout; queries: role, token, user."""

    def __init__(
        self,
        kitsu: KitsuManager,
        session_repository: SessionRepository,
        bus: Optional[MessageBus] = None,
    ) -> None:
        self.kitsu = kitsu
        self.session_repository = session_repository
        self.bus = bus or MessageBus()
        self._user: Optional[User] = None
        self._raw_user_data: Optional[dict] = None
        self._host: str = ""

    # ------------------------------------------------------------------
    # State (read by the legacy facade and the UI)
    # ------------------------------------------------------------------
    @property
    def current_user(self) -> Optional[User]:
        return self._user

    @property
    def raw_user_data(self) -> Optional[dict]:
        """Raw Kitsu person dict, kept only for backward-compatible UI reads."""
        return self._raw_user_data

    @property
    def host(self) -> str:
        return self._host

    # ------------------------------------------------------------------
    # Use cases
    # ------------------------------------------------------------------
    def set_host(self, host_url: str) -> None:
        if not host_url.endswith("/api"):
            host_url = f"{host_url.rstrip('/')}/api"
        self._host = host_url
        self.kitsu.set_host(host_url)

    def login(self, email: str, password: str, host_url: str) -> Tuple[bool, str]:
        try:
            self.set_host(host_url)
            tokens = self.kitsu.log_in(email, password)
            raw = self.kitsu.get_current_user()
            user = User.from_kitsu_dict(raw or {})
            self._raw_user_data = raw
            self._user = user
            self.session_repository.save(Session(host=self._host, tokens=tokens))
            self.bus.publish(UserAuthenticated(user_id=user.id or ""))
            return True, "Login successful."
        except Exception as error:  # noqa: BLE001 - reported to the caller
            return False, self._classify_login_error(error)

    def restore_session(self) -> bool:
        session = self.session_repository.load()
        if session is None:
            return False
        try:
            self.set_host(session.host)
            self.kitsu.set_tokens(session.tokens)
            raw = self.kitsu.get_current_user()
            user = User.from_kitsu_dict(raw or {})
            self._raw_user_data = raw
            self._user = user
            return True
        except Exception:  # noqa: BLE001 - stale/corrupt session
            self.session_repository.delete()
            self._user = None
            self._raw_user_data = None
            return False

    def logout(self) -> None:
        user_id = self._user.id if self._user else ""
        self.kitsu.log_out()
        self._user = None
        self._raw_user_data = None
        self.session_repository.delete()
        self.bus.publish(UserLoggedOut(user_id=user_id))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def current_role(self) -> Role:
        return self._user.role if self._user else Role.GUEST

    def access_token(self) -> str:
        if self.kitsu.has_session_tokens():
            return self.kitsu.get_access_token()
        session = self.session_repository.load()
        if session is not None:
            return session.tokens.get("access_token", "")
        return ""

    @staticmethod
    def _classify_login_error(error: Exception) -> str:
        if isinstance(error, AuthFailedException):
            return "Invalid credentials."
        return f"Connection error: {str(error)}"
