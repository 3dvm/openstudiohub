"""Unit tests for the ProvisioningService."""

from src.application.services.provisioning_service import ProvisioningService


class FakeManifestManager:
    def __init__(self):
        self.calls = []

    def register_addon(self, **kwargs):
        self.calls.append(kwargs)
        return True, "ok"


def test_register_if_compatible_success():
    manager = FakeManifestManager()
    parsed = {"is_valid": True, "name": "blender_kitsu", "version": "1.5.0", "min_blender_version": "4.2.0"}

    ok, entry = ProvisioningService.register_if_compatible(manager, parsed, "4.3.0", "/tmp/a.zip")
    assert ok is True
    assert entry["version"] == "1.5.0"
    assert entry["mandatory"] is False
    assert manager.calls[0]["addon_name"] == "blender_kitsu"
    assert manager.calls[0]["source_zip"] == "/tmp/a.zip"


def test_register_if_compatible_incompatible():
    manager = FakeManifestManager()
    parsed = {"is_valid": True, "name": "x", "version": "1.0", "min_blender_version": "4.3.0"}

    ok, entry = ProvisioningService.register_if_compatible(manager, parsed, "4.2.0", "/tmp/a.zip")
    assert ok is False
    assert entry is None
    assert manager.calls == []


def test_register_if_compatible_invalid():
    manager = FakeManifestManager()
    ok, entry = ProvisioningService.register_if_compatible(manager, {"is_valid": False}, "4.3.0", "/tmp/a.zip")
    assert ok is False
    assert entry is None
