"""Unit tests for the task <-> physical file mapping service."""

from pathlib import Path

import pytest

from src.application.services.task_file_service import TaskFileService
from src.domain.production.entities import Task


class FakeConfig:
    def get_vfs_svn_name(self) -> str:
        return "svn"


class FakeRepo:
    def __init__(self) -> None:
        self.calls = []

    def update_task_data(self, task_id: str, data: dict) -> bool:
        self.calls.append((task_id, data))
        return True


class FakeEmptyMaster:
    def __init__(self) -> None:
        self.requests = []

    def copy_into(self, project_root: Path, destination: Path, status_callback=None) -> Path:
        self.requests.append(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"BLEND")
        return destination


def _service() -> tuple[TaskFileService, FakeRepo, FakeEmptyMaster]:
    repo = FakeRepo()
    master = FakeEmptyMaster()
    service = TaskFileService(config_factory=FakeConfig(), repository=repo, empty_master_provider=master)
    return service, repo, master


def _asset_task() -> Task:
    return Task(
        id="t1",
        entity_name="Monkey",
        asset_type_name="Character",
        task_type_name="Modeling",
        task_type_short_name="Modeling",
    )


def test_validate_relative_path():
    assert TaskFileService.validate_relative_path("pro/assets/char/monkey/monkey-model.blend") is None
    assert TaskFileService.validate_relative_path("") is not None
    assert TaskFileService.validate_relative_path("/abs/file.blend") is not None
    assert TaskFileService.validate_relative_path("../escape.blend") is not None
    assert TaskFileService.validate_relative_path("pro/assets/file.txt") is not None


def test_suggest_relative_path_uses_naming_policy():
    service, _, _ = _service()
    task = _asset_task()
    from src.domain.production.value_objects import EntityType

    task.entity_type = EntityType.ASSET
    suggested = service.suggest_relative_path(task)
    assert suggested.endswith(".blend")
    assert "pro/assets/character/monkey" in suggested


def test_link_persists_filepath_in_task_data():
    service, repo, _ = _service()
    assert service.link(_asset_task(), "pro/assets/char/monkey/monkey-model.blend") is True
    task_id, data = repo.calls[-1]
    assert task_id == "t1"
    assert data["filepath"] == "pro/assets/char/monkey/monkey-model.blend"


def test_link_rejects_invalid_path():
    service, _, _ = _service()
    with pytest.raises(ValueError):
        service.link(_asset_task(), "../escape.blend")


def test_link_raises_when_repository_rejects():
    service, repo, _ = _service()
    repo.update_task_data = lambda task_id, data: False
    with pytest.raises(RuntimeError):
        service.link(_asset_task(), "pro/assets/char/monkey/monkey-model.blend")


def test_unlink_raises_when_repository_rejects():
    service, repo, _ = _service()
    repo.update_task_data = lambda task_id, data: False
    with pytest.raises(RuntimeError):
        service.unlink(_asset_task())


def test_unlink_removes_filepath():
    service, repo, _ = _service()
    task = _asset_task().with_filepath("pro/assets/char/monkey/monkey-model.blend")
    assert service.unlink(task) is True
    _, data = repo.calls[-1]
    assert "filepath" not in data


def test_create_empty_file_materializes(tmp_path):
    service, _, master = _service()
    relative = "pro/assets/char/monkey/monkey-model.blend"
    destination = service.create_empty_file(tmp_path, relative)
    assert destination == tmp_path / "svn" / relative
    assert destination.exists()
    assert master.requests == [destination]


def test_link_and_create_empty(tmp_path):
    service, repo, _ = _service()
    relative = "pro/assets/char/monkey/monkey-model.blend"
    assert service.link_and_create_empty(_asset_task(), tmp_path, relative) is True
    assert (tmp_path / "svn" / relative).exists()
    assert repo.calls[-1][1]["filepath"] == relative
