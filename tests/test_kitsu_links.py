"""Tests for building Kitsu web URLs from task data."""

from src.domain.production.kitsu_links import (
    kitsu_base_url,
    task_kitsu_path,
    task_kitsu_url,
)


def _task(entity_type, task_id="t1", project_id="p1", **extra):
    data = {
        "id": task_id,
        "project_id": project_id,
        "entity_type_name": entity_type,
    }
    data.update(extra)
    return data


def test_kitsu_base_url_strips_api_suffix():
    assert kitsu_base_url("https://kitsu.test/api") == "https://kitsu.test"
    assert kitsu_base_url("https://kitsu.test/api/") == "https://kitsu.test"


def test_task_path_uses_the_entity_type():
    assert task_kitsu_path(_task("Shot")) == "/productions/p1/shots/tasks/t1"
    assert task_kitsu_path(_task("Sequence")) == "/productions/p1/sequences/tasks/t1"
    assert task_kitsu_path(_task("Asset")) == "/productions/p1/assets/tasks/t1"
    assert task_kitsu_path(_task("Edit")) == "/productions/p1/edits/tasks/t1"


def test_task_path_handles_episodes_and_unknown_types():
    episode = _task("Episode", episode_id="e1")
    assert task_kitsu_path(episode) == "/productions/p1/episodes/e1/tasks/t1"
    assert task_kitsu_path(_task("Unknown")) == "/productions/p1/assets/tasks/t1"


def test_task_kitsu_url_requires_ids():
    assert task_kitsu_url("https://kitsu.test/api", _task("Sequence")) == (
        "https://kitsu.test/productions/p1/sequences/tasks/t1"
    )
    assert task_kitsu_url("https://kitsu.test/api", {"entity_type_name": "Shot"}) == ""
