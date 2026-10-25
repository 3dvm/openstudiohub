"""Unit tests for the batch creation worker (asset/shot forging)."""

from pathlib import Path

import pytest

from src.interfaces.qt.workers import blender_spawners
from src.interfaces.qt.workers.blender_spawners import BatchCreationWorker


class FakeConfigFactory:
    def __init__(self, root: Path):
        self._root = root

    def get_workspace_root(self):
        return self._root

    def get_vfs_local_name(self):
        return "local"

    def get_vfs_svn_name(self):
        return "svn"

    def get_kitsu_api_url(self):
        return "http://kitsu.test/api"


class FakeProcess:
    def __init__(self, env, returncode=0):
        self.env = env
        self.returncode = returncode
        self.stdout = iter([])

    def wait(self):
        return self.returncode


class FakePopenFactory:
    """Records the environment of every spawned subprocess."""

    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.calls = []

    def __call__(self, cmd, env=None, stdout=None, stderr=None, text=None, **kwargs):
        process = FakeProcess(env or {}, returncode=self.returncode)
        self.calls.append(process)
        return process


def _install_fakes(monkeypatch, tmp_path, returncode=0):
    monkeypatch.setattr(blender_spawners.BlenderLocator, "resolve", staticmethod(lambda _p: "/usr/bin/blender"))
    popen = FakePopenFactory(returncode=returncode)
    monkeypatch.setattr(blender_spawners.subprocess, "Popen", popen)
    return popen


def _run(worker):
    finished = []
    worker.finished_batch.connect(lambda success, message: finished.append((success, message)))
    worker.run()
    return finished


def _asset(**overrides):
    asset = {
        "id": "asset-1",
        "name": "hero",
        "type": "Character",
        "asset_type_id": "type-1",
        "asset_type_name": "Character",
        "has_file": False,
        "tasks": {
            "Modeling": {"has_file": False, "filepath": "", "raw_task": {}},
            "Rigging": {"has_file": False, "filepath": "", "raw_task": {}},
        },
    }
    asset.update(overrides)
    return asset


def _shot(**overrides):
    shot = {
        "id": "shot-1",
        "name": "sh010",
        "type": "Shot",
        "parent": "SQ010",
        "has_file": False,
        "tasks": {
            "Layout": {"has_file": False, "raw_task": {}},
            "Animation": {"has_file": False, "raw_task": {}},
        },
    }
    shot.update(overrides)
    return shot


def _worker(config, entities, task_types):
    return BatchCreationWorker(
        pm_core=None,
        config_factory=config,
        project_id="p1",
        project_name="MIDEQ_promo",
        entities=entities,
        task_types=task_types,
    )


def test_asset_uses_generic_build_target_and_forwards_kitsu_type(monkeypatch, tmp_path, qapp):
    config = FakeConfigFactory(tmp_path)
    popen = _install_fakes(monkeypatch, tmp_path)

    finished = _run(_worker(config, [_asset()], ["Modeling"]))

    assert len(popen.calls) == 1
    env = popen.calls[0].env
    assert env["OPENSTUDIO_BUILD_TARGET"] == "ASSET"
    assert env["OPENSTUDIO_KITSU_ASSET_TYPE_ID"] == "type-1"
    assert env["OPENSTUDIO_KITSU_TASK_TYPE_NAME"] == "Modeling"
    assert finished == [(True, "1 entities processed successfully.")]


def test_unselected_task_types_are_skipped(monkeypatch, tmp_path, qapp):
    config = FakeConfigFactory(tmp_path)
    popen = _install_fakes(monkeypatch, tmp_path)

    _run(_worker(config, [_asset()], ["Rigging"]))

    assert len(popen.calls) == 1
    assert popen.calls[0].env["OPENSTUDIO_KITSU_TASK_TYPE_NAME"] == "Rigging"


def test_asset_without_tasks_is_not_forged(monkeypatch, tmp_path, qapp):
    config = FakeConfigFactory(tmp_path)
    popen = _install_fakes(monkeypatch, tmp_path)

    finished = _run(_worker(config, [_asset(tasks={})], ["Modeling"]))

    assert popen.calls == []
    assert finished == [(True, "1 entities processed successfully.")]


def test_shot_routes_to_shot_builder(monkeypatch, tmp_path, qapp):
    config = FakeConfigFactory(tmp_path)
    popen = _install_fakes(monkeypatch, tmp_path)

    _run(_worker(config, [_shot()], ["Layout"]))

    assert len(popen.calls) == 1
    env = popen.calls[0].env
    assert env["OPENSTUDIO_BUILD_TARGET"] == "SHOT"
    assert env["OPENSTUDIO_KITSU_SEQUENCE_NAME"] == "SQ010"


def test_failed_subprocess_reports_failure(monkeypatch, tmp_path, qapp):
    config = FakeConfigFactory(tmp_path)
    _install_fakes(monkeypatch, tmp_path, returncode=1)

    finished = _run(_worker(config, [_asset()], ["Modeling"]))

    assert len(finished) == 1
    success, message = finished[0]
    assert success is False
    assert "hero [Modeling]" in message
