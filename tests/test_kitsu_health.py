"""Unit tests for the Kitsu server reachability probe."""

from src.infrastructure import kitsu_manager as mod
from src.infrastructure.kitsu_manager import KitsuManager


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _patch_host(monkeypatch, host: str) -> None:
    monkeypatch.setattr(mod.gazu.client, "get_host", lambda: host)


def test_online_probe_strips_api_suffix(monkeypatch):
    _patch_host(monkeypatch, "http://localhost:5000/api")
    seen = {}

    def fake_get(url, timeout=None):
        seen["url"] = url
        seen["timeout"] = timeout
        return _Response(200)

    monkeypatch.setattr(mod.requests, "get", fake_get)

    ok, message = KitsuManager().check_health()

    assert ok is True
    assert seen["url"] == "http://localhost:5000"
    assert seen["timeout"] == 5.0
    assert "online" in message.lower()


def test_any_http_response_counts_as_online(monkeypatch):
    _patch_host(monkeypatch, "http://localhost:5000/api")
    monkeypatch.setattr(mod.requests, "get", lambda url, timeout=None: _Response(403))

    ok, message = KitsuManager().check_health()

    assert ok is True
    assert "403" in message


def test_unreachable_server_is_offline(monkeypatch):
    _patch_host(monkeypatch, "http://localhost:5000/api")

    def fake_get(url, timeout=None):
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(mod.requests, "get", fake_get)

    ok, message = KitsuManager().check_health()

    assert ok is False
    assert "unreachable" in message.lower()


def test_missing_host_is_offline(monkeypatch):
    _patch_host(monkeypatch, "")

    ok, message = KitsuManager().check_health()

    assert ok is False
    assert "not configured" in message.lower()
