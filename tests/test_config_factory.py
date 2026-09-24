"""Unit tests for ConfigFactory OS-key mapping and per-OS workspace root."""

import json
from pathlib import Path

from src.infrastructure.config_factory import DEFAULT_VAULT_DIR, ConfigFactory


def _write(tmp_path, payload: dict) -> Path:
    cfg_path = tmp_path / "settings.json"
    cfg_path.write_text(json.dumps(payload), encoding="utf-8")
    return cfg_path


def test_current_os_maps_darwin_to_macos(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Darwin")
    factory = ConfigFactory(tmp_path / "settings.json")
    assert factory._get_current_os() == "macos"


def test_current_os_maps_windows(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Windows")
    factory = ConfigFactory(tmp_path / "settings.json")
    assert factory._get_current_os() == "windows"


def test_current_os_maps_linux(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Linux")
    factory = ConfigFactory(tmp_path / "settings.json")
    assert factory._get_current_os() == "linux"


def test_get_workspace_root_uses_macos_key(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Darwin")
    cfg_path = _write(tmp_path, {
        "vcs_engine": {"local_workspace_root": {"macos": "/Volumes/studio"}}
    })
    factory = ConfigFactory(cfg_path)
    assert factory.get_workspace_root() == Path("/Volumes/studio")


def test_set_local_workspace_root_only_updates_current_os(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Linux")
    cfg_path = _write(tmp_path, {
        "vcs_engine": {
            "local_workspace_root": {
                "windows": "Z:\\studio",
                "linux": "/mnt/studio",
                "macos": "/Volumes/studio",
            }
        }
    })

    factory = ConfigFactory(cfg_path)
    assert factory.set_local_workspace_root(Path("/home/artist/projects")) is True

    reloaded = json.loads(cfg_path.read_text(encoding="utf-8"))
    roots = reloaded["vcs_engine"]["local_workspace_root"]
    assert roots["linux"] == "/home/artist/projects"
    assert roots["windows"] == "Z:\\studio"
    assert roots["macos"] == "/Volumes/studio"

    assert factory.get_workspace_root() == Path("/home/artist/projects")


def test_set_local_workspace_root_creates_missing_keys(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Windows")
    cfg_path = tmp_path / "settings.json"
    factory = ConfigFactory(cfg_path)  # file does not exist yet

    assert factory.set_local_workspace_root(Path("C:\\projects")) is True

    reloaded = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert reloaded["vcs_engine"]["local_workspace_root"]["windows"] == "C:\\projects"


def test_vcs_server_profile_and_repository_url_persist(tmp_path):
    cfg_path = tmp_path / "settings.json"
    factory = ConfigFactory(cfg_path)

    assert factory.set_vcs_server_profile({
        "mode": "remote_ssh",
        "remote": {"host": "svn-vps", "ssh_user": "ops", "repo_root": "/srv/svn"},
    }) is True
    assert factory.set_repository_url("svn://svn-vps") is True

    reloaded = ConfigFactory(cfg_path)
    profile = reloaded.get_vcs_server_profile()
    assert profile.is_remote is True
    assert profile.remote.host == "svn-vps"
    assert reloaded.get_vcs_repository_url() == "svn://svn-vps"
    assert reloaded.is_remote_server() is True


def test_vcs_server_profile_defaults_to_local_docker(tmp_path):
    factory = ConfigFactory(tmp_path / "settings.json")
    assert factory.get_server_mode() == "local_docker"


def test_multi_server_registry_crud(tmp_path):
    factory = ConfigFactory(tmp_path / "settings.json")

    assert factory.save_vcs_server({
        "id": "local", "name": "Local", "adapter": "svn", "repository_url": "svn://localhost",
    }) is True
    assert factory.save_vcs_server({
        "id": "vps", "name": "VPS", "adapter": "svn", "repository_url": "svn://vps",
        "profile": {"mode": "remote_ssh", "remote": {"host": "vps", "ssh_user": "ops", "container": "estudio_svn"}},
    }) is True

    assert {s.id for s in factory.get_vcs_servers().servers} == {"local", "vps"}
    assert factory.get_default_server().id == "local"

    assert factory.set_default_server("vps") is True
    assert factory.get_default_server().id == "vps"
    assert factory.get_vcs_repository_url() == "svn://vps"
    assert factory.get_vcs_server_profile().mode == "remote_ssh"

    assert factory.remove_vcs_server("vps") is True
    assert factory.get_default_server().id == "local"


def test_legacy_single_server_config_is_migrated(tmp_path):
    cfg_path = _write(tmp_path, {
        "vcs_engine": {
            "active_adapter": "svn",
            "repository_url": "svn://old-server",
            "enable_vendor_sparse_checkout": False,
        },
        "infrastructure_topology": {
            "vcs_server": {"mode": "remote_ssh", "remote": {"host": "old", "ssh_user": "u", "container": "c"}},
        },
    })
    factory = ConfigFactory(cfg_path)

    registry = factory.get_vcs_servers()
    assert len(registry.servers) == 1
    server = registry.default()
    assert server.id == "default"
    assert server.repository_url == "svn://old-server"
    assert server.enable_vendor_sparse_checkout is False
    assert server.profile.mode == "remote_ssh"


def test_get_server_for_project_uses_blueprint_binding(tmp_path):
    factory = ConfigFactory(tmp_path / "settings.json")
    factory.save_vcs_server({"id": "local", "name": "Local", "adapter": "svn", "repository_url": "svn://localhost"})
    factory.save_vcs_server({"id": "vps", "name": "VPS", "adapter": "svn", "repository_url": "svn://vps"})
    factory.set_default_server("local")

    project = tmp_path / "neon"
    (project / "pipeline").mkdir(parents=True)
    (project / "pipeline" / "project_init.json").write_text(
        json.dumps({"vcs_server_id": "vps"}), encoding="utf-8"
    )

    assert factory.get_server_for_project(project).id == "vps"
    # Unknown project falls back to the default.
    assert factory.get_server_for_project(tmp_path / "ghost").id == "local"


def test_save_configuration_preserves_server_registry(tmp_path):
    factory = ConfigFactory(tmp_path / "settings.json")
    factory.save_vcs_server({"id": "vps", "name": "VPS", "adapter": "svn", "repository_url": "svn://vps"})

    assert factory.save_configuration({"vcs_engine": {"local_workspace_root": {"linux": "/projects"}}}) is True

    assert factory.get_server("vps") is not None
    assert factory.get_vcs_repository_url() == "svn://vps"


# ---------------------------------------------------------------------------
# Portable vault resolution & migration
# ---------------------------------------------------------------------------
def _write_vault_config(tmp_path, workspace: Path, vault_path: str) -> Path:
    return _write(tmp_path, {
        "vcs_engine": {"local_workspace_root": {"linux": workspace.as_posix()}},
        "infrastructure_topology": {"vault_path": vault_path},
    })


def test_vault_under_workspace_migrates_to_relative(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Linux")
    workspace = tmp_path / "nas" / "projects"
    vault = workspace / DEFAULT_VAULT_DIR
    vault.mkdir(parents=True)

    cfg_path = _write_vault_config(tmp_path, workspace, str(vault))
    factory = ConfigFactory(cfg_path)

    persisted = json.loads(cfg_path.read_text(encoding="utf-8"))["infrastructure_topology"]
    assert persisted == {"vault_dir": DEFAULT_VAULT_DIR}
    assert factory.get_vault_dir() == DEFAULT_VAULT_DIR
    assert factory.get_vault_path() == vault


def test_missing_foreign_vault_self_heals_to_workspace_default(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Linux")
    workspace = tmp_path / "artist" / "nas"
    (workspace / DEFAULT_VAULT_DIR).mkdir(parents=True)

    cfg_path = _write_vault_config(tmp_path, workspace, "/home/macuare/Nextcloud/vault")
    factory = ConfigFactory(cfg_path)

    assert factory.get_vault_path() == workspace / DEFAULT_VAULT_DIR
    persisted = json.loads(cfg_path.read_text(encoding="utf-8"))["infrastructure_topology"]
    assert "vault_path" not in persisted


def test_external_existing_vault_kept_as_local_override(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Linux")
    workspace = tmp_path / "nas"
    workspace.mkdir()
    external = tmp_path / "external_vault"
    external.mkdir()

    cfg_path = _write_vault_config(tmp_path, workspace, str(external))
    factory = ConfigFactory(cfg_path)

    assert factory.get_vault_path() == external
    persisted = json.loads(cfg_path.read_text(encoding="utf-8"))["infrastructure_topology"]
    assert persisted == {"vault_path": str(external)}


def test_portable_vault_config_and_set_vault_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Linux")
    workspace = tmp_path / "nas"
    workspace.mkdir()
    factory = ConfigFactory(tmp_path / "settings.json")
    factory.set_local_workspace_root(workspace)

    inside = workspace / DEFAULT_VAULT_DIR
    assert factory.portable_vault_config(str(inside)) == {"vault_dir": DEFAULT_VAULT_DIR}
    assert factory.portable_vault_config(str(tmp_path / "elsewhere")) == {"vault_path": str(tmp_path / "elsewhere")}

    assert factory.set_vault_dir("studio_vault") is True
    assert factory.get_vault_path() == workspace / "studio_vault"


def test_fresh_install_defaults_vault_under_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Linux")
    workspace = tmp_path / "nas"
    workspace.mkdir()
    cfg_path = _write(tmp_path, {"vcs_engine": {"local_workspace_root": {"linux": workspace.as_posix()}}})
    factory = ConfigFactory(cfg_path)
    assert factory.get_vault_path() == workspace / DEFAULT_VAULT_DIR


def test_seed_import_does_not_inherit_foreign_machine_paths(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Linux")
    from src.infrastructure.seed_engine import StudioSeedService

    workspace = tmp_path / "artist_nas"
    (workspace / DEFAULT_VAULT_DIR).mkdir(parents=True)

    factory = ConfigFactory(tmp_path / "settings.json")
    seed_payload = {
        "infrastructure_topology": {
            "vault_path": "/home/someartist/Nextcloud/vault",
            "vcs_server": {"mode": "remote_ssh", "remote": {"ssh_key_path": "/home/someartist/.ssh/id_ed25519"}},
        },
        "vcs_engine": {
            "local_workspace_root": {"linux": "/home/someartist/Nextcloud/projects"},
            "servers": [
                {
                    "id": "vps",
                    "name": "VPS",
                    "adapter": "svn",
                    "repository_url": "svn://vps",
                    "profile": {
                        "mode": "remote_ssh",
                        "remote": {
                            "host": "vps",
                            "ssh_user": "ops",
                            "container": "c",
                            "ssh_key_path": "/home/someartist/.ssh/id_ed25519",
                        },
                    },
                }
            ],
            "default_server_id": "vps",
        },
    }
    ok, seed_path = StudioSeedService(factory).export_seed(seed_payload, tmp_path)
    assert ok is True

    assert factory.import_seed(Path(seed_path)) is True
    factory.set_local_workspace_root(workspace)
    factory.set_vault_dir(factory.get_vault_dir())

    assert factory.get_vault_path() == workspace / DEFAULT_VAULT_DIR
    server = factory.get_server("vps")
    assert server.profile.remote.ssh_key_path != "/home/someartist/.ssh/id_ed25519"
