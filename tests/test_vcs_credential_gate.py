"""Unit tests for the shared, per-server VCS credential gate."""

from src.application.credential_vault import CredentialVault
from src.interfaces.qt.viewmodels.vcs_credential_gate import (
    VcsPromptResult,
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


def _gate(required, vault, prompt, server_id="vps"):
    return ensure_vcs_credentials(
        required,
        server_id,
        "VPS",
        False,
        vault,
        prompt=prompt,
        report_status=lambda msg, color: None,
    )


def test_vcs_requires_credentials_false_when_none():
    assert vcs_requires_credentials(FakeConfigFactory("none")) is False
    assert vcs_requires_credentials(FakeConfigFactory("")) is False


def test_vcs_requires_credentials_true_for_svn_and_localhost():
    assert vcs_requires_credentials(FakeConfigFactory("svn")) is True
    assert vcs_requires_credentials(FakeConfigFactory("svn", "svn://localhost/repo")) is True


def test_ensure_skips_when_not_required():
    vault = CredentialVault()
    result = _gate(False, vault, prompt=lambda *a: VcsPromptResult("u", "p"))
    assert result == ("", "")
    assert vault.has_server_credentials("vps") is False


def test_ensure_uses_existing_vault_credentials():
    vault = CredentialVault()
    vault.save_server_credentials("vps", "existing", "secret", enabled=True)
    called = {"prompt": False}

    def prompt(*args):
        called["prompt"] = True
        return VcsPromptResult("new", "new-secret")

    result = _gate(True, vault, prompt=prompt)
    assert result == ("existing", "secret")
    assert called["prompt"] is False


def test_ensure_prompts_and_saves_for_server():
    vault = CredentialVault()
    result = _gate(True, vault, prompt=lambda *a: VcsPromptResult("artist", "secret", "key-pass"))

    assert result == ("artist", "secret")
    assert vault.get_server_credentials("vps") == ("artist", "secret")
    assert vault.is_server_enabled("vps") is True
    assert vault.get_ssh_passphrase("vps") == "key-pass"


def test_ensure_cancel_reports_and_returns_none():
    vault = CredentialVault()
    messages = []
    result = ensure_vcs_credentials(
        True, "vps", "VPS", False, vault,
        prompt=lambda *a: None,
        report_status=lambda msg, color: messages.append((msg, color)),
    )
    assert result is None
    assert messages and messages[-1][1] == "red"
    assert vault.has_server_credentials("vps") is False


def test_ensure_without_prompt_reports_and_returns_none():
    vault = CredentialVault()
    result = _gate(True, vault, prompt=None)
    assert result is None
