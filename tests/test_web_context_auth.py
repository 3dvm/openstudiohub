"""Tests for the Kitsu Authorization header interceptor."""

from PySide6.QtCore import QUrl

from src.interfaces.qt.shell.web_context_view import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
    KitsuAuthInterceptor,
    WebContextView,
)


class FakeRequestInfo:
    def __init__(self, url: str) -> None:
        self._url = QUrl(url)
        self.headers = {}

    def requestUrl(self):
        return self._url

    def setHttpHeader(self, name, value):
        self.headers[name] = value


def test_interceptor_adds_header_only_to_kitsu_api(qapp):
    interceptor = KitsuAuthInterceptor()
    interceptor.set_auth("kitsu.test", "token-123")

    api = FakeRequestInfo("https://kitsu.test/api/auth/authenticated")
    interceptor.interceptRequest(api)
    assert api.headers[b"Authorization"] == b"Bearer token-123"

    external = FakeRequestInfo("https://example.com/api/data")
    interceptor.interceptRequest(external)
    assert external.headers == {}

    non_api = FakeRequestInfo("https://kitsu.test/pictures/preview.png")
    interceptor.interceptRequest(non_api)
    assert non_api.headers == {}


def test_build_auth_cookie_matches_zou_defaults(qapp):
    access = WebContextView.build_auth_cookie(
        ACCESS_COOKIE, "access-token", "kitsu.test", "/", True, 7
    )
    assert access.name() == b"access_token_cookie"
    assert access.value() == b"access-token"
    assert access.domain() == "kitsu.test"
    assert access.path() == "/"
    assert access.isSecure() is True
    assert access.isHttpOnly() is True

    refresh = WebContextView.build_auth_cookie(
        REFRESH_COOKIE, "refresh-token", "kitsu.test", REFRESH_COOKIE_PATH, True, 15
    )
    assert refresh.name() == b"refresh_token_cookie"
    assert refresh.path() == "/auth/refresh-token"


def test_interceptor_can_be_cleared(qapp):
    interceptor = KitsuAuthInterceptor()
    interceptor.set_auth("kitsu.test", "token-123")
    interceptor.clear_auth()

    info = FakeRequestInfo("https://kitsu.test/api/auth/authenticated")
    interceptor.interceptRequest(info)

    assert info.headers == {}
