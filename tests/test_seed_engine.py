"""Unit tests for the StudioSeedService."""

import base64
import json
import zlib
from pathlib import Path

from src.infrastructure.seed_engine import StudioSeedService


class FakeConfigFactory:
    def __init__(self):
        self.saved = None

    def save_configuration(self, payload, from_seed=False):
        self.saved = payload
        return True


def _decode_seed(seed_path) -> dict:
    encoded = seed_path.read_text(encoding="utf-8")
    return json.loads(zlib.decompress(base64.b64decode(encoded)).decode("utf-8"))


def test_seed_roundtrip(tmp_path):
    config_factory = FakeConfigFactory()
    service = StudioSeedService(config_factory)

    payload = {
        "studio_profile": {"name": "Macuare Estudio"},
        "kitsu_production": {"api_url": "http://localhost:8080"},
    }

    ok, seed_path = service.export_seed(payload, tmp_path)
    assert ok is True
    assert seed_path.endswith("macuare_estudio.seed")

    assert service.import_seed(tmp_path / "macuare_estudio.seed") is True
    assert config_factory.saved == payload


def test_sanitize_payload_strips_machine_specific_paths():
    payload = {
        "infrastructure_topology": {
            "vault_path": "/home/macuare/Nextcloud/vault",
            "vault_dir": "openstudio_vault",
            "vcs_server": {"mode": "remote_ssh", "remote": {"ssh_key_path": "/home/macuare/.ssh/id_ed25519"}},
        },
        "vcs_engine": {
            "servers": [
                {
                    "id": "vps",
                    "profile": {
                        "mode": "remote_ssh",
                        "remote": {
                            "ssh_key_path": "/home/macuare/.ssh/id_ed25519",
                            "ssh_cert_path": "/home/macuare/.ssh/id_ed25519-cert.pub",
                            "known_hosts_path": "/home/macuare/.ssh/known_hosts",
                            "host": "svn-vps",
                        },
                    },
                }
            ]
        },
    }

    clean = StudioSeedService.sanitize_payload(payload)

    assert "vault_path" not in clean["infrastructure_topology"]
    assert clean["infrastructure_topology"]["vault_dir"] == "openstudio_vault"
    legacy_remote = clean["infrastructure_topology"]["vcs_server"]["remote"]
    server_remote = clean["vcs_engine"]["servers"][0]["profile"]["remote"]
    assert legacy_remote["ssh_key_path"] == ""
    for field_name in ("ssh_key_path", "ssh_cert_path", "known_hosts_path"):
        assert server_remote[field_name] == ""
    assert server_remote["host"] == "svn-vps"
    # The original payload is untouched.
    assert payload["infrastructure_topology"]["vault_path"] == "/home/macuare/Nextcloud/vault"


def test_export_seed_writes_sanitized_payload(tmp_path):
    service = StudioSeedService(FakeConfigFactory())
    payload = {
        "infrastructure_topology": {"vault_path": "/home/macuare/Nextcloud/vault"},
        "vcs_engine": {
            "servers": [
                {"id": "vps", "profile": {"mode": "remote_ssh", "remote": {"ssh_key_path": "/home/macuare/.ssh/id_ed25519"}}}
            ]
        },
    }

    ok, seed_path = service.export_seed(payload, tmp_path)
    assert ok is True

    decoded = _decode_seed(Path(seed_path))
    assert "vault_path" not in decoded["infrastructure_topology"]
    assert decoded["vcs_engine"]["servers"][0]["profile"]["remote"]["ssh_key_path"] == ""


def test_export_seed_default_name(tmp_path):
    service = StudioSeedService(FakeConfigFactory())
    ok, seed_path = service.export_seed({}, tmp_path)
    assert ok is True
    assert seed_path.endswith("openstudio.seed")


def test_import_seed_missing_file(tmp_path):
    service = StudioSeedService(FakeConfigFactory())
    assert service.import_seed(tmp_path / "missing.seed") is False
