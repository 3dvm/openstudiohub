"""Unit tests for ConfigFactory OS-key mapping and per-OS workspace root."""

import json
from pathlib import Path

from src.infrastructure.config_factory import ConfigFactory


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
