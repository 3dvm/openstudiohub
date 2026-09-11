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

    assert vm.load_session_credentials() == ("", False)

    vm.save_session_credentials("artist", "secret", True)

    assert vm.load_session_credentials() == ("artist", True)
    assert vault.get_svn_credentials() == ("artist", "secret")
    assert vault.is_svn_enabled() is True

    vm.save_session_credentials("artist", "secret", False)
    assert vault.is_svn_enabled() is False


def test_session_credentials_without_vault_are_noop():
    vm = SettingsViewModel(FakeConfigFactory(), FakeVaultService(), credential_vault=None)
    assert vm.load_session_credentials() == ("", False)
    vm.save_session_credentials("artist", "secret", True)
