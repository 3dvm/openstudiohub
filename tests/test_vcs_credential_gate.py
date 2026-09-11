"""Unit tests for the shared VCS credential gate."""

from src.application.credential_vault import CredentialVault
from src.interfaces.qt.viewmodels.vcs_credential_gate import (
    ensure_vcs_credentials,
    vcs_requires_credentials,
)


class FakeConfigFactory:
    def __init__(self, adapter="svn", repo="") -> None:
        self._adapter = adapter
        self._repo = repo

    def get_vcs_adapter_type(self):
        return self._adapter

    def get_vcs_repository_url(self):
        return self._repo


def test_vcs_requires_credentials_false_when_none():
    assert vcs_requires_credentials(FakeConfigFactory("none")) is False
    assert vcs_requires_credentials(FakeConfigFactory("")) is False


def test_vcs_requires_credentials_true_for_svn_and_localhost():
    assert vcs_requires_credentials(FakeConfigFactory("svn")) is True
    assert vcs_requires_credentials(FakeConfigFactory("svn", "svn://localhost/repo")) is True


def test_ensure_skips_when_not_required():
    vault = CredentialVault()
    result = ensure_vcs_credentials(
        False, vault, prompt=lambda: ("u", "p"), report_status=lambda msg, color: None
    )
    assert result == ("", "")
    assert vault.has_svn_credentials() is False


def test_ensure_uses_existing_vault_credentials():
    vault = CredentialVault()
    vault.save_svn_credentials("existing", "secret", enabled=True)
    called = {"prompt": False}

    def prompt():
        called["prompt"] = True
        return ("new", "new-secret")

    result = ensure_vcs_credentials(True, vault, prompt=prompt, report_status=lambda msg, color: None)
    assert result == ("existing", "secret")
    assert called["prompt"] is False


def test_ensure_prompts_and_saves():
    vault = CredentialVault()
    result = ensure_vcs_credentials(
        True, vault, prompt=lambda: ("artist", "secret"), report_status=lambda msg, color: None
    )
    assert result == ("artist", "secret")
    assert vault.get_svn_credentials() == ("artist", "secret")
    assert vault.is_svn_enabled() is True


def test_ensure_cancel_reports_and_returns_none():
    vault = CredentialVault()
    messages = []
    result = ensure_vcs_credentials(
        True,
        vault,
        prompt=lambda: None,
        report_status=lambda msg, color: messages.append((msg, color)),
    )
    assert result is None
    assert messages and messages[-1][1] == "red"
    assert vault.has_svn_credentials() is False


def test_ensure_without_prompt_reports_and_returns_none():
    vault = CredentialVault()
    result = ensure_vcs_credentials(True, vault, prompt=None, report_status=lambda msg, color: None)
    assert result is None
