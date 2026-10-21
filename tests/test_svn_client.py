"""Unit tests for SVN client discovery and version gating."""

from pathlib import Path
from types import SimpleNamespace

from src.infrastructure.vcs import svn_client


def _fake_svn(tmp_path: Path, version: str = "1.14.5"):
    executable = tmp_path / "svn"
    executable.write_text("", encoding="utf-8")
    return executable


def test_parse_version_accepts_plain_and_banner_text():
    assert svn_client.parse_version("1.14.5") == (1, 14, 5)
    assert svn_client.parse_version("svn, version 1.14.5 (r2)") == (1, 14, 5)
    assert svn_client.parse_version("") == ()


def test_detect_svn_client_accepts_minimum_version(monkeypatch, tmp_path):
    executable = _fake_svn(tmp_path)
    monkeypatch.setattr(svn_client.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(svn_client, "bundled_candidates", lambda app_root=None: [])
    monkeypatch.setattr(
        svn_client.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="1.14.5\n", stderr=""),
    )

    status = svn_client.detect_svn_client()

    assert status.found is True
    assert status.meets_minimum is True
    assert status.version == (1, 14, 5)
    assert str(executable) in status.path


def test_detect_svn_client_rejects_older_version(monkeypatch, tmp_path):
    executable = _fake_svn(tmp_path)
    monkeypatch.setattr(svn_client.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(svn_client, "bundled_candidates", lambda app_root=None: [])
    monkeypatch.setattr(
        svn_client.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="1.8.19\n", stderr=""),
    )

    status = svn_client.detect_svn_client()

    assert status.found is True
    assert status.meets_minimum is False
    assert "older than" in status.message


def test_detect_svn_client_reports_missing_client(monkeypatch):
    monkeypatch.setattr(svn_client.shutil, "which", lambda _name: None)
    monkeypatch.setattr(svn_client, "bundled_candidates", lambda app_root=None: [])

    status = svn_client.detect_svn_client()

    assert status.found is False
    assert status.meets_minimum is False
    assert svn_client.MANUAL_INSTALL_MESSAGE in status.message
