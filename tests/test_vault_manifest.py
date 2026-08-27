"""Unit tests for the unified vault manifest (schema consolidation)."""

import zipfile

from src.domain.vault.manifest import VaultManifest
from src.infrastructure.manifest_manager import ManifestManager
from src.infrastructure.vault_manifest_repository import FileVaultManifestRepository


def test_vault_manifest_roundtrip():
    raw = {
        "5.1.2": {
            "blender_version": "5.1.2",
            "categories": {"addons": {"a": {"version": "1.0"}}, "templates": {}},
        }
    }
    manifest = VaultManifest.from_dict(raw)
    assert manifest.registered_versions() == ["5.1.2"]
    assert manifest.get_addons("5.1.2") == {"a": {"version": "1.0"}}
    assert manifest.to_dict() == raw


def test_vault_manifest_from_legacy_shape():
    # Legacy shape: no categories wrapper, no blender_version.
    legacy = {"5.1.2": {"addons": {"a": {"version": "1.0"}}, "templates": {}}}
    manifest = VaultManifest.from_dict(legacy)
    assert manifest.registered_versions() == ["5.1.2"]
    assert manifest.to_dict()["5.1.2"]["categories"]["addons"]["a"]["version"] == "1.0"


def test_vault_manifest_add_addon():
    manifest = VaultManifest()
    manifest.add_addon("5.1.2", "blender_kitsu", "1.5.0", description="Kitsu", mandatory=True, requires=["asset_pipeline"])
    entry = manifest.get_addons("5.1.2")["blender_kitsu"]
    assert entry["version"] == "1.5.0"
    assert entry["mandatory"] is True
    assert entry["requires"] == ["asset_pipeline"]


def test_file_repository_roundtrip(tmp_path):
    repo = FileVaultManifestRepository(tmp_path)
    manifest = VaultManifest()
    manifest.add_addon("5.1.2", "a", "1.0")
    assert repo.save(manifest) is True
    assert repo.load().get_addons("5.1.2")["a"]["version"] == "1.0"


def test_manifest_manager_register_addon(tmp_path):
    source = tmp_path / "addon.zip"
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr("blender_manifest.toml", 'id = "my_addon"\nversion = "1.0.0"\n')

    manager = ManifestManager(tmp_path)
    ok, _ = manager.register_addon("5.1.2", "My Addon", "1.0.0", source, description="Test")
    assert ok is True

    # Zip copied to the canonical addons dir, manifest at the canonical location.
    assert (tmp_path / "addons" / "my_addon_v1.0.0.zip").exists()
    assert (tmp_path / "vault_manifest.json").exists()

    loaded = FileVaultManifestRepository(tmp_path).load()
    entry = loaded.get_addons("5.1.2")["My Addon"]
    assert entry["version"] == "1.0.0"
    assert entry["description"] == "Test"


def test_manifest_manager_scan_binaries(tmp_path):
    (tmp_path / "blender_versions").mkdir()
    (tmp_path / "blender_versions" / "blender-5.1.2-linux-x64.tar.xz").write_text("x")

    manager = ManifestManager(tmp_path)
    versions = manager.scan_local_blender_binaries()
    assert "5.1.2" in versions
    assert "5.1.2" in manager.get_registered_blender_versions()
