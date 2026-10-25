"""Unit tests for the SettingsViewModel session-credential flow."""

from src.application.credential_vault import CredentialVault
from src.interfaces.qt.viewmodels.settings_viewmodel import SettingsViewModel


class FakeConfigFactory:
    def get_raw_config(self):
        return {}


class FakeVaultService:
    def load_inventory(self):
        return {}


def test_session_credentials_stay_in_vault_only():
    vault = CredentialVault()
    vm = SettingsViewModel(
        FakeConfigFactory(),
        FakeVaultService(),
        credential_vault=vault,
    )

    assert vm.load_session_credentials("vps") == ("", False)

    vm.save_session_credentials("vps", "artist", "secret", True)

    assert vm.load_session_credentials("vps") == ("artist", True)
    assert vault.get_server_credentials("vps") == ("artist", "secret")
    assert vault.is_server_enabled("vps") is True

    vm.save_session_credentials("vps", "artist", "secret", False)
    assert vault.is_server_enabled("vps") is False


def test_session_credentials_are_isolated_per_server():
    vault = CredentialVault()
    vm = SettingsViewModel(FakeConfigFactory(), FakeVaultService(), credential_vault=vault)

    vm.save_session_credentials("local", "local-user", "local-pass", True)
    vm.save_session_credentials("vps", "vps-user", "vps-pass", True)

    assert vault.get_server_credentials("local") == ("local-user", "local-pass")
    assert vault.get_server_credentials("vps") == ("vps-user", "vps-pass")


def test_session_credentials_without_vault_are_noop():
    vm = SettingsViewModel(FakeConfigFactory(), FakeVaultService(), credential_vault=None)
    assert vm.load_session_credentials("vps") == ("", False)
    vm.save_session_credentials("vps", "artist", "secret", True)
