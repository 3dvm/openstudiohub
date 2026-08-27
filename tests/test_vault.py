"""Unit tests for the Vault bounded context."""

import zipfile

from src.domain.addon_inspector import AddonInspector
from src.domain.addon_parser import AddonParser
from src.domain.vault import addon as vault_addon
from src.domain.vault.compatibility import CompatibilityPolicy
from src.domain.vault.value_objects import SemVer


# ----------------------------------------------------------------------
# SemVer / CompatibilityPolicy
# ----------------------------------------------------------------------
def test_semver_parse_and_compare():
    assert SemVer.parse("4.2.0").parts == (4, 2, 0)
    assert SemVer.parse("4.2").parts == (4, 2)
    assert SemVer.parse((4, 2, 0)).parts == (4, 2, 0)
    assert SemVer.parse("1.0b").parts == (1, 0)  # strips non-numeric
    assert SemVer.parse("4.2.0") >= SemVer.parse("4.2.0")
    assert SemVer.parse("4.3.0") >= SemVer.parse("4.2.0")
    assert SemVer.parse("4.2") >= SemVer.parse("4.2.0")  # padded equal
    assert SemVer.parse("4.1.0") < SemVer.parse("4.2.0")


def test_compatibility_policy():
    assert CompatibilityPolicy.is_compatible("4.2.0", "4.2.0") is True
    assert CompatibilityPolicy.is_compatible("4.2.0", "4.3.0") is True
    assert CompatibilityPolicy.is_compatible("4.2.0", "4.1.0") is False
    # Parse failure -> permissive (TD judgment), preserving legacy behavior.
    assert CompatibilityPolicy.is_compatible("not-a-version", "4.2.0") is True


# ----------------------------------------------------------------------
# Unified addon parser
# ----------------------------------------------------------------------
def test_parse_toml_prefers_id():
    meta = vault_addon.parse_toml(
        'id = "blender_kitsu"\nname = "Blender Kitsu"\nversion = "1.5.0"\nblender_version_min = "4.2.0"'
    )
    assert meta.name == "blender_kitsu"
    assert meta.version == "1.5.0"
    assert meta.min_blender_version == "4.2.0"
    assert meta.type == "manifest"
    assert meta.is_valid is True


def test_parse_legacy_bl_info():
    content = 'bl_info = {\n    "name": "My Addon",\n    "version": (1, 2, 3),\n    "blender": (2, 80, 0),\n}'
    meta = vault_addon.parse_legacy_bl_info(content)
    assert meta.name == "My Addon"
    assert meta.version == "1.2.3"
    assert meta.min_blender_version == "2.80.0"
    assert meta.type == "legacy"


def test_parse_zip(tmp_path):
    zip_path = tmp_path / "my_addon.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("blender_manifest.toml", 'id = "my_addon"\nversion = "1.0.0"\nblender_version_min = "4.2.0"\n')
    meta = vault_addon.parse_zip(zip_path)
    assert meta.name == "my_addon"
    assert meta.is_valid is True


def test_parse_directory(tmp_path):
    addon_dir = tmp_path / "legacy_addon"
    addon_dir.mkdir()
    (addon_dir / "__init__.py").write_text(
        'bl_info = {"name": "Legacy Addon", "version": (1, 0, 0), "blender": (2, 80, 0)}', encoding="utf-8"
    )
    meta = vault_addon.parse_directory(addon_dir)
    assert meta.name == "Legacy Addon"
    assert meta.type == "legacy"


# ----------------------------------------------------------------------
# Deprecated shims preserve their legacy API
# ----------------------------------------------------------------------
def test_addon_parser_shim(tmp_path):
    zip_path = tmp_path / "a.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("blender_manifest.toml", 'id = "a"\nversion = "1.0.0"\nblender_version_min = "4.2.0"\n')
    parsed = AddonParser.parse_zip(zip_path)
    assert parsed["is_valid"] is True
    assert parsed["name"] == "a"
    assert parsed["min_blender_version"] == "4.2.0"
    assert AddonParser.is_compatible("4.2.0", "4.3.0") is True


def test_addon_inspector_shim(tmp_path):
    zip_path = tmp_path / "a.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("blender_manifest.toml", 'id = "a"\nversion = "1.0.0"\nblender_version_min = "4.2.0"\n')
    inspected = AddonInspector.inspect_zip(zip_path)
    assert inspected["name"] == "a"
    assert inspected["blender_min"] == (4, 2, 0)
    assert AddonInspector.is_compatible((4, 2, 0), "4.3.0") is True
