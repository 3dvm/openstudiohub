"""Unit tests for the VaultService application service."""

from src.application.services.vault_service import VaultService
from src.infrastructure.vault_manifest_repository import FileVaultManifestRepository


def test_load_inventory_seeds_default_when_absent(tmp_path):
    service = VaultService(FileVaultManifestRepository(tmp_path))
    inventory = service.load_inventory()

    # A default seed is created on the first load.
    assert "5.1.2" in inventory
    assert (tmp_path / "vault_manifest.json").exists()


def test_save_and_load_roundtrip(tmp_path):
    service = VaultService(FileVaultManifestRepository(tmp_path))

    payload = {
        "4.2.0": {
            "categories": {
                "addons": {"blender_kitsu": {"version": "1.5.0"}},
                "templates": {},
            }
        }
    }
    assert service.save_inventory(payload) is True

    loaded = service.load_inventory()
    assert loaded["4.2.0"]["addons"]["blender_kitsu"]["version"] == "1.5.0"


def test_manifest_path_and_vault_root(tmp_path):
    repo = FileVaultManifestRepository(tmp_path)
    service = VaultService(repo)

    assert service.manifest_path == tmp_path / "vault_manifest.json"
    assert service.vault_root == tmp_path
