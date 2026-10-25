"""Unit tests for the vault manifest integrity auditor."""

import zipfile

from src.domain.vault.integrity import (
    VaultIntegrityAuditor,
    base_version,
    parse_binary_filename,
    register_disk_versions,
    remove_version,
)


def _make_addon(vault_root, filename: str, addon_id: str, version: str = "1.0.0", description: str = "Test addon"):
    addons_dir = vault_root / "addons"
    addons_dir.mkdir(parents=True, exist_ok=True)
    path = addons_dir / filename
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "blender_manifest.toml",
            f'id = "{addon_id}"\nversion = "{version}"\ndescription = "{description}"\n',
        )
    return path


def test_parse_binary_filename_and_base_version():
    parsed = parse_binary_filename("blender-5.2.1-linux-x64.tar.xz")
    assert parsed == {"version": "5.2.1", "os": "linux", "arch": "x64", "ext": "tar.xz"}
    assert parse_binary_filename("not-a-binary.txt") is None
    assert base_version("5.2.1") == "5.2"
    assert base_version("4.2") == "4.2"


def test_audit_reports_unregistered_and_missing_binaries(tmp_path):
    binaries = tmp_path / "blender_versions"
    binaries.mkdir()
    (binaries / "blender-5.2.1-linux-x64.tar.xz").write_bytes(b"x")
    (binaries / "blender-5.0.1-linux-x64.tar.xz").write_bytes(b"x")

    manifest = {
        "5.2.0": {"addons": {}, "templates": {}},
        "5.1.2": {"addons": {}, "templates": {}},
    }

    report = VaultIntegrityAuditor(tmp_path).audit(manifest)

    assert sorted(a.version for a in report.unregistered_binaries) == ["5.0.1", "5.2.1"]
    assert report.missing_binaries == ["5.2.0", "5.1.2"]
    assert report.has_issues is True


def test_audit_detects_orphan_and_missing_addons(tmp_path):
    _make_addon(tmp_path, "lighting_overrider_v1.0.0.zip", "lighting_overrider")
    _make_addon(tmp_path, "orphan_addon_v1.0.0.zip", "orphan_addon")

    manifest = {
        "5.2.0": {
            "addons": {
                "Lighting Overrider": {
                    "version": "1.0.0",
                    "path": "addons/lighting_overrider_v1.0.0.zip",
                },
                "Ghost Addon": {"version": "2.0.0", "path": "addons/ghost_v2.0.0.zip"},
            },
            "templates": {},
        }
    }

    report = VaultIntegrityAuditor(tmp_path).audit(manifest)

    assert [a.filename for a in report.orphan_addons] == ["orphan_addon_v1.0.0.zip"]
    assert report.missing_addon_files == [("5.2.0", "Ghost Addon", "addons/ghost_v2.0.0.zip")]


def test_audit_detects_version_mismatch_and_broken_requires(tmp_path):
    _make_addon(tmp_path, "blender_kitsu_v1.0.0.zip", "blender_kitsu", version="1.0.0")

    manifest = {
        "5.2.0": {
            "addons": {
                "blender_kitsu": {
                    "version": "1.5.0",
                    "requires": ["asset_pipeline"],
                }
            },
            "templates": {},
        }
    }

    report = VaultIntegrityAuditor(tmp_path).audit(manifest)

    assert report.addon_version_mismatches == [("5.2.0", "blender_kitsu", "1.5.0", "1.0.0")]
    assert report.broken_requires == [("5.2.0", "blender_kitsu", "asset_pipeline")]


def test_audit_detects_templates_and_misplaced_binaries(tmp_path):
    (tmp_path / "project_templates" / "Base").mkdir(parents=True)
    (tmp_path / "project_templates" / "Orphan").mkdir()
    (tmp_path / "blender-5.3.0-linux-x64.tar.xz").write_bytes(b"x")
    (tmp_path / "blender_versions").mkdir()

    manifest = {
        "5.2.0": {
            "addons": {},
            "templates": {"Base": {}, "Missing": {}},
        }
    }

    report = VaultIntegrityAuditor(tmp_path).audit(manifest)

    assert report.missing_templates == [("5.2.0", "Missing")]
    assert report.orphan_templates == ["Orphan"]
    assert [p.name for p in report.misplaced_binaries] == ["blender-5.3.0-linux-x64.tar.xz"]
    assert report.disk_binaries == []


def test_register_disk_versions_and_remove_version(tmp_path):
    binaries = tmp_path / "blender_versions"
    binaries.mkdir()
    (binaries / "blender-5.2.1-linux-x64.tar.xz").write_bytes(b"x")
    (binaries / "blender-5.0.1-linux-x64.tar.xz").write_bytes(b"x")

    manifest = {"5.2.0": {"addons": {}, "templates": {}}}
    report = VaultIntegrityAuditor(tmp_path).audit(manifest)

    added = register_disk_versions(manifest, report)
    assert sorted(added) == ["5.0.1", "5.2.1"]
    assert manifest["5.0.1"] == {"addons": {}, "templates": {}}

    assert remove_version(manifest, "5.2.0") is True
    assert "5.2.0" not in manifest
    assert remove_version(manifest, "9.9.9") is False


def test_audit_matches_addons_across_naming_conventions(tmp_path):
    # Manifest uses a display name + underscore path; the archive is compacted.
    _make_addon(tmp_path, "contactsheet_v1.0.0.zip", "contact_sheet")

    manifest = {
        "5.2.0": {
            "addons": {
                "Contact Sheet": {"version": "1.0.0", "path": "addons/contact_sheet_v1.0.0.zip"}
            },
            "templates": {},
        }
    }

    report = VaultIntegrityAuditor(tmp_path).audit(manifest)
    assert report.missing_addon_files == []
    assert report.orphan_addons == []
    assert report.addon_version_mismatches == []


def test_clean_vault_has_no_issues(tmp_path):
    binaries = tmp_path / "blender_versions"
    binaries.mkdir()
    (binaries / "blender-5.2.0-linux-x64.tar.xz").write_bytes(b"x")
    _make_addon(tmp_path, "lighting_overrider_v1.0.0.zip", "lighting_overrider")

    manifest = {
        "5.2.0": {
            "addons": {
                "lighting_overrider": {
                    "version": "1.0.0",
                    "path": "addons/lighting_overrider_v1.0.0.zip",
                }
            },
            "templates": {},
        }
    }

    report = VaultIntegrityAuditor(tmp_path).audit(manifest)
    assert report.has_issues is False
