"""Unit tests for AuthService using in-memory fakes."""

from src.application.bus import MessageBus
from src.application.ports import SessionRepository
from src.application.services.auth_service import AuthService
from src.domain.identity.entities import Session
from src.domain.identity.events import UserAuthenticated, UserLoggedOut
from src.domain.identity.value_objects import Role
from src.infrastructure.kitsu_manager import AuthFailedException


class FakeKitsu:
    def __init__(self):
        self.host = None
        self.tokens = {}
        self.user = {
            "id": "u-1",
            "email": "ada@studio.com",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "role": "admin",
            "position": "",
        }
        self.logged_out = False

    def set_host(self, host):
        self.host = host

    def log_in(self, email, password):
        if password == "bad":
            raise AuthFailedException("bad credentials")
        self.tokens = {"access_token": "tok-123"}
        return self.tokens

    def get_current_user(self):
        return self.user

    def set_tokens(self, tokens):
        self.tokens = tokens or {}

    def log_out(self):
        self.logged_out = True
        self.tokens = {}

    def has_session_tokens(self):
        return bool(self.tokens)

    def get_access_token(self):
        return self.tokens.get("access_token", "")


class InMemorySessionRepository(SessionRepository):
    def __init__(self):
        self.session = None

    def load(self):
        return self.session

    def save(self, session):
        self.session = session

    def delete(self):
        self.session = None


def make_service():
    kitsu = FakeKitsu()
    repo = InMemorySessionRepository()
    bus = MessageBus()
    events = []
    bus.subscribe(UserAuthenticated, events.append)
    bus.subscribe(UserLoggedOut, events.append)
    return AuthService(kitsu, repo, bus), kitsu, repo, events


def test_login_success():
    svc, kitsu, repo, events = make_service()
    ok, msg = svc.login("ada@studio.com", "good", "http://localhost:8080")
    assert ok is True
    assert msg == "Login successful."
    assert svc.current_role() is Role.TD
    assert svc.current_user.email == "ada@studio.com"
    assert svc.host == "http://localhost:8080/api"
    assert repo.session is not None
    assert repo.session.tokens["access_token"] == "tok-123"
    assert svc.access_token() == "tok-123"
    assert isinstance(events[0], UserAuthenticated)


def test_login_invalid_credentials():
    svc, kitsu, repo, events = make_service()
    ok, msg = svc.login("ada@studio.com", "bad", "http://localhost:8080")
    assert ok is False
    assert msg == "Invalid credentials."
    assert svc.current_user is None
    assert svc.current_role() is Role.GUEST


def test_restore_and_logout():
    svc, kitsu, repo, events = make_service()
    repo.save(Session(host="http://h/api", tokens={"access_token": "saved"}))
    assert svc.restore_session() is True
    assert svc.current_role() is Role.TD
    assert svc.access_token() == "saved"

    svc.logout()
    assert svc.current_user is None
    assert svc.current_role() is Role.GUEST
    assert repo.session is None
    assert kitsu.logged_out is True
    assert isinstance(events[0], UserLoggedOut)


def test_restore_without_session():
    svc, kitsu, repo, events = make_service()
    assert svc.restore_session() is False
    assert svc.current_user is None
