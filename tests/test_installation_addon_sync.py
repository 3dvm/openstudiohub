"""Version-aware add-on deployment for project workspaces."""

import json
import zipfile
from pathlib import Path

from src.application.services.installation_service import InstallationService


class FakeConfig:
    def get_vfs_local_name(self):
        return "local"

    def get_vfs_svn_name(self):
        return "svn"


def _write_manifest(vault_root: Path, version: str, addons: dict) -> None:
    vault_root.mkdir(parents=True, exist_ok=True)
    (vault_root / "vault_manifest.json").write_text(
        json.dumps(
            {
                version: {
                    "blender_version": version,
                    "categories": {"addons": addons, "templates": {}},
                }
            }
        ),
        encoding="utf-8",
    )


def _write_addon_zip(
    vault_root: Path,
    filename: str,
    addon_id: str,
    version: str,
    min_blender: str = "4.2.0",
    extra: str = "",
) -> Path:
    path = vault_root / "addons" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "blender_manifest.toml",
            f'id = "{addon_id}"\nname = "{addon_id}"\nversion = "{version}"\n'
            f'blender_version_min = "{min_blender}"\n',
        )
        zf.writestr("__init__.py", "def register():\n    pass\n")
        if extra:
            zf.writestr(extra, "extra")
    return path


def _service(vault_root: Path) -> InstallationService:
    return InstallationService(FakeConfig(), vault_root)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "local").mkdir(parents=True)
    (project / "svn").mkdir()
    (project / "local" / "project_config.json").write_text(
        json.dumps(
            {
                "blender_version": "5.2.3",
                "vfs_local": "local",
                "dependencies": {"addons": {"toolkit": "0.6.0"}},
            }
        ),
        encoding="utf-8",
    )
    pipeline = project / "pipeline"
    pipeline.mkdir()
    (pipeline / "project_init.json").write_text(
        json.dumps(
            {
                "blender_version": "5.2.3",
                "dependencies": {"addons": {"toolkit": "0.6.0"}},
                "topography_signature": {"vfs_local": "local"},
            }
        ),
        encoding="utf-8",
    )
    return project


def _installed(project: Path) -> Path:
    return project / "local" / "blender_data" / "extensions" / "user_default" / "toolkit"


def test_addon_is_installed_from_the_manifest_version(tmp_path):
    vault = tmp_path / "vault"
    _write_manifest(vault, "5.2.3", {"toolkit": {"version": "0.6.0"}})
    _write_addon_zip(vault, "toolkit-0.6.0.zip", "toolkit", "0.6.0")
    project = _project(tmp_path)
    messages = []

    _service(vault)._sincronizar_addons(
        project,
        "local",
        {"addons": {"toolkit": "0.5.0"}},
        lambda message, color: messages.append(message),
        "5.2.3",
    )

    assert (_installed(project) / "blender_manifest.toml").exists()
    assert (_installed(project) / ".openstudio_addon_source.json").exists()
    assert any("deployed" in message for message in messages)
    assert _service(vault).addons_need_update(project) is False


def test_installed_addon_is_replaced_by_a_newer_manifest_version(tmp_path):
    vault = tmp_path / "vault"
    _write_manifest(vault, "5.2.3", {"toolkit": {"version": "0.6.0"}})
    _write_addon_zip(vault, "toolkit-0.6.0.zip", "toolkit", "0.6.0")
    project = _project(tmp_path)
    old = _installed(project)
    old.mkdir(parents=True)
    (old / "blender_manifest.toml").write_text(
        'id = "toolkit"\nname = "toolkit"\nversion = "0.5.0"\n'
        'blender_version_min = "4.2.0"\n',
        encoding="utf-8",
    )

    _service(vault)._sincronizar_addons(
        project, "local", {"addons": {"toolkit": "0.5.0"}}, lambda *_: None, "5.2.3"
    )

    manifest = (old / "blender_manifest.toml").read_text(encoding="utf-8")
    assert 'version = "0.6.0"' in manifest


def test_same_version_with_new_content_is_refreshed(tmp_path):
    vault = tmp_path / "vault"
    _write_manifest(vault, "5.2.3", {"toolkit": {"version": "0.6.0"}})
    zip_path = _write_addon_zip(vault, "toolkit-0.6.0.zip", "toolkit", "0.6.0")
    project = _project(tmp_path)
    service = _service(vault)
    service._sincronizar_addons(
        project, "local", {"addons": {"toolkit": "0.6.0"}}, lambda *_: None, "5.2.3"
    )
    assert not (_installed(project) / "new_file.txt").exists()

    _write_addon_zip(
        vault, zip_path.name, "toolkit", "0.6.0", extra="new_file.txt"
    )
    service._sincronizar_addons(
        project, "local", {"addons": {"toolkit": "0.6.0"}}, lambda *_: None, "5.2.3"
    )

    assert (_installed(project) / "new_file.txt").exists()


def test_incompatible_addon_is_not_installed(tmp_path):
    vault = tmp_path / "vault"
    _write_manifest(vault, "5.2.3", {"toolkit": {"version": "0.6.0"}})
    _write_addon_zip(
        vault, "toolkit-0.6.0.zip", "toolkit", "0.6.0", min_blender="6.0.0"
    )
    project = _project(tmp_path)
    messages = []

    _service(vault)._sincronizar_addons(
        project,
        "local",
        {"addons": {"toolkit": "0.6.0"}},
        lambda message, color: messages.append(message),
        "5.2.3",
    )

    assert not _installed(project).exists()
    assert any("requires Blender" in message for message in messages)


def test_declared_version_without_a_zip_is_not_silently_replaced(tmp_path):
    vault = tmp_path / "vault"
    _write_manifest(vault, "5.2.3", {"toolkit": {"version": "0.6.0"}})
    _write_addon_zip(vault, "toolkit-0.5.0.zip", "toolkit", "0.5.0")
    project = _project(tmp_path)
    messages = []

    _service(vault)._sincronizar_addons(
        project,
        "local",
        {"addons": {"toolkit": "0.5.0"}},
        lambda message, color: messages.append(message),
        "5.2.3",
    )

    assert not _installed(project).exists()
    assert any("not available" in message for message in messages)


def test_workspace_needs_update_when_the_manifest_has_a_new_addon_version(tmp_path):
    vault = tmp_path / "vault"
    _write_manifest(vault, "5.2.3", {"toolkit": {"version": "0.6.0"}})
    _write_addon_zip(vault, "toolkit-0.6.0.zip", "toolkit", "0.6.0")
    project = _project(tmp_path)
    old = _installed(project)
    old.mkdir(parents=True)
    (old / "blender_manifest.toml").write_text(
        'id = "toolkit"\nname = "toolkit"\nversion = "0.5.0"\n'
        'blender_version_min = "4.2.0"\n',
        encoding="utf-8",
    )
    service = _service(vault)

    assert service.workspace_needs_update(project) is True

    service._sincronizar_addons(
        project, "local", {"addons": {"toolkit": "0.6.0"}}, lambda *_: None, "5.2.3"
    )

    assert service.workspace_needs_update(project) is False


def test_preferences_template_seeds_a_new_sandbox_only(tmp_path):
    project = _project(tmp_path)
    source = project / "pipeline" / "blender_preferences.blend"
    source.write_bytes(b"template")
    service = _service(tmp_path / "vault")
    messages = []

    service._install_preferences_template(
        project, "local", "pipeline", lambda message, color: messages.append(message)
    )

    target = project / "local" / "blender_data" / "config" / "userpref.blend"
    assert target.read_bytes() == b"template"

    target.write_bytes(b"artist")
    service._install_preferences_template(
        project, "local", "pipeline", lambda message, color: messages.append(message)
    )
    assert target.read_bytes() == b"artist"
