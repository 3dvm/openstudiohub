"""Integration tests for the atomic initial-setup configuration write."""

from pathlib import Path

from src.infrastructure.config_factory import ConfigFactory
from src.infrastructure.seed_engine import StudioSeedService


def _payload() -> dict:
    return {
        "studio_profile": {"name": "Studio"},
        "kitsu_production": {"api_url": "https://kitsu.example.com"},
        "infrastructure_topology": {"vault_dir": "openstudio_vault"},
        "project_topography": {"vfs_svn": "svn"},
        "vcs_engine": {
            "servers": [
                {
                    "id": "svn",
                    "name": "Studio SVN",
                    "adapter": "svn",
                    "repository_url": "svn://studio.local",
                }
            ],
            "default_server_id": "svn",
        },
    }


def test_apply_initial_setup_writes_seed_projects_and_svn_path(tmp_path):
    factory = ConfigFactory(tmp_path / "settings.json")
    seed_ok, seed_path = StudioSeedService(factory).export_seed(_payload(), tmp_path)
    assert seed_ok is True
    projects = tmp_path / "projects"
    projects.mkdir()

    ok, message = factory.apply_initial_setup(Path(seed_path), projects, "/usr/bin/svn")

    assert ok is True
    assert "successfully" in message
    assert factory.get_kitsu_api_url() == "https://kitsu.example.com"
    assert factory.has_local_workspace_root() is True
    assert factory.get_workspace_root() == projects
    assert factory.get_svn_cli_path() == "/usr/bin/svn"
    assert factory.get_default_server().adapter == "svn"
    assert factory.get_vault_path() == projects / "openstudio_vault"


def test_seed_sanitization_drops_machine_specific_svn_path():
    payload = _payload()
    payload["vcs_engine"]["svn_cli_path"] = {"linux": "/usr/bin/svn"}

    clean = StudioSeedService.sanitize_payload(payload)

    assert "svn_cli_path" not in clean["vcs_engine"]
    assert payload["vcs_engine"]["svn_cli_path"] == {"linux": "/usr/bin/svn"}


def test_read_seed_payload_requires_kitsu_url(tmp_path):
    factory = ConfigFactory(tmp_path / "settings.json")
    payload = _payload()
    payload.pop("kitsu_production")
    export_ok, seed_path = StudioSeedService(factory).export_seed(payload, tmp_path)
    assert export_ok is True

    ok, data, error = factory.read_seed_payload(Path(seed_path))

    assert ok is False
    assert data is None
    assert "Kitsu" in error


def test_apply_local_paths_persists_without_reimporting_a_seed(tmp_path):
    factory = ConfigFactory(tmp_path / "settings.json")
    projects = tmp_path / "local_projects"
    projects.mkdir()

    assert factory.apply_local_paths(projects, "/usr/bin/svn") is True
    assert factory.has_local_workspace_root() is True
    assert factory.get_workspace_root() == projects
    assert factory.get_svn_cli_path() == "/usr/bin/svn"


def test_seed_sanitization_drops_machine_local_tls_ca_path():
    payload = _payload()
    payload["vcs_engine"]["servers"][0]["profile"] = {
        "ca_file": "/home/artist/studio-ca.crt",
        "trust_default_ca": False,
        "trust_server_cert_failures": "unknown-ca",
    }

    clean = StudioSeedService.sanitize_payload(payload)

    profile = clean["vcs_engine"]["servers"][0]["profile"]
    assert "ca_file" not in profile
    assert profile["trust_default_ca"] is False
    assert profile["trust_server_cert_failures"] == "unknown-ca"
