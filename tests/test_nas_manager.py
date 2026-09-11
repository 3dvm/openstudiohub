"""Unit tests for NasManager dynamic base directory resolution."""

import json
from pathlib import Path

from src.infrastructure.config_factory import ConfigFactory
from src.infrastructure.nas_manager import NasManager


def test_base_dir_follows_config_changes(monkeypatch, tmp_path):
    monkeypatch.setattr("src.infrastructure.config_factory.platform.system", lambda: "Linux")
    cfg_path = tmp_path / "settings.json"
    cfg_path.write_text(json.dumps({
        "vcs_engine": {"local_workspace_root": {"linux": str(tmp_path / "root_a")}}
    }), encoding="utf-8")

    factory = ConfigFactory(cfg_path)
    manager = NasManager(config_factory=factory)

    assert manager.base_dir == Path(tmp_path / "root_a")

    factory.set_local_workspace_root(tmp_path / "root_b")

    assert manager.base_dir == Path(tmp_path / "root_b")


def test_base_dir_snapshot_without_config_factory(tmp_path):
    manager = NasManager(tmp_path / "root")
    assert manager.base_dir == Path(tmp_path / "root")


def test_load_project_blueprint_missing(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    manager = NasManager(tmp_path)
    status, data = manager.load_project_blueprint(project)

    assert status == "missing"
    assert data is None


def test_load_project_blueprint_invalid_json(tmp_path):
    project = tmp_path / "project"
    pipeline = project / "pipeline"
    pipeline.mkdir(parents=True)
    (pipeline / "project_init.json").write_text("{ not valid json", encoding="utf-8")

    manager = NasManager(tmp_path)
    status, data = manager.load_project_blueprint(project)

    assert status == "invalid"
    assert data is None


def test_load_project_blueprint_ok(tmp_path):
    project = tmp_path / "project"
    pipeline = project / "pipeline"
    pipeline.mkdir(parents=True)
    (pipeline / "project_init.json").write_text('{"project_name": "Neon"}', encoding="utf-8")

    manager = NasManager(tmp_path)
    status, data = manager.load_project_blueprint(project)

    assert status == "ok"
    assert data == {"project_name": "Neon"}
