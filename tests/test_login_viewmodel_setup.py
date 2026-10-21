"""Unit tests for the startup VCS/setup verification on the login screen."""

from types import SimpleNamespace

from src.interfaces.qt.viewmodels.login_viewmodel import LoginViewModel


class FakeConfig:
    def __init__(self, kitsu_url: str = "") -> None:
        self.kitsu_url = kitsu_url

    def get_kitsu_api_url(self) -> str:
        return self.kitsu_url


class FakeSetupService:
    def __init__(self, needs_setup: bool) -> None:
        self._status = SimpleNamespace(needs_setup=needs_setup)

    def status(self):
        return self._status


def _vm(config, setup_service, qapp):
    return LoginViewModel(
        auth_service=SimpleNamespace(),
        credential_vault=SimpleNamespace(),
        config_factory=config,
        initial_setup_service=setup_service,
    )


def test_load_config_state_requests_setup_when_it_is_incomplete(qapp):
    vm = _vm(FakeConfig(), FakeSetupService(needs_setup=True), qapp)
    received = []
    vm.setup_state_changed.connect(received.append)

    vm.load_config_state()

    assert received == [True]
    assert vm.setup_required() is True


def test_load_config_state_does_not_request_setup_when_complete(qapp):
    vm = _vm(
        FakeConfig("https://kitsu.example.com"),
        FakeSetupService(needs_setup=False),
        qapp,
    )
    received = []
    vm.setup_state_changed.connect(received.append)

    vm.load_config_state()

    assert received == [False]
    assert vm.setup_required() is False
