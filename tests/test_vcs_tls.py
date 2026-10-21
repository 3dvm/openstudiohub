"""Unit tests for SVN TLS configuration."""

from pathlib import Path

import pytest

from src.domain.workspace.vcs_server_profile import VCSServerProfile
from src.infrastructure.vcs.svn_adapter import SVNAdapter
from src.infrastructure.vcs.svn_errors import VcsError


def _adapter(url: str, profile: VCSServerProfile | None = None) -> SVNAdapter:
    return SVNAdapter(url, Path("/tmp/workspace"), server_profile=profile)


def test_https_without_overrides_uses_default_ca():
    args = _adapter("https://svn.example.com/repo")._build_auth_args(None, None)

    assert "--non-interactive" in args
    assert "--trust-server-cert" not in args
    assert "--trust-server-cert-failures" not in args


def test_https_with_ca_file_pins_the_authority(tmp_path):
    ca_file = tmp_path / "studio-ca.crt"
    ca_file.write_text("certificate", encoding="utf-8")
    profile = VCSServerProfile(ca_file=str(ca_file))

    args = _adapter("https://svn.example.com/repo", profile)._build_auth_args(None, None)

    assert "--config-option" in args
    assert f"servers:global:ssl-authority-files={ca_file}" in args


def test_https_without_default_ca_disables_system_bundle():
    profile = VCSServerProfile(trust_default_ca=False)

    args = _adapter("https://svn.example.com/repo", profile)._build_auth_args(None, None)

    assert "servers:global:ssl-trust-default-ca=no" in args


def test_https_with_explicit_failures_passes_the_list():
    profile = VCSServerProfile(trust_server_cert_failures="unknown-ca,cn-mismatch")

    args = _adapter("https://svn.example.com/repo", profile)._build_auth_args(None, None)

    assert "--trust-server-cert-failures" in args
    assert "unknown-ca,cn-mismatch" in args


def test_missing_ca_file_fails_closed(tmp_path):
    profile = VCSServerProfile(ca_file=str(tmp_path / "missing.crt"))

    with pytest.raises(VcsError):
        _adapter("https://svn.example.com/repo", profile)._build_auth_args(None, None)


def test_svn_scheme_ignores_tls_settings(tmp_path):
    ca_file = tmp_path / "studio-ca.crt"
    ca_file.write_text("certificate", encoding="utf-8")
    profile = VCSServerProfile(
        ca_file=str(ca_file),
        trust_default_ca=False,
        trust_server_cert_failures="unknown-ca",
    )

    args = _adapter("svn://svn.example.com/repo", profile)._build_auth_args(None, None)

    assert "--config-option" not in args
    assert "--trust-server-cert-failures" not in args
