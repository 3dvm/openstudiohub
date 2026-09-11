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
