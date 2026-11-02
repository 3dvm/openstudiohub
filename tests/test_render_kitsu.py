"""Unit tests for the render video upload to Kitsu."""

from src.interfaces.qt.workers.render_workers import KitsuUploadWorker


class FakeKitsu:
    def __init__(self):
        self.calls = []

    def get_task(self, task_id):
        return {"id": task_id, "entity_name": "sh010"}

    def publish_preview(self, task, status, **kwargs):
        self.calls.append((task, status, kwargs))
        return ({}, {})


class FakeProduction:
    def __init__(self):
        self.kitsu = FakeKitsu()

    def get_project_task_board(self, project_id):
        return [
            {"id": "task-1", "entity_name": "sh010", "task_type_name": "render"}
        ]


def test_upload_matches_the_shot_and_task_type(qapp):
    production = FakeProduction()
    worker = KitsuUploadWorker(
        production,
        "project-1",
        "sh010",
        "render",
        {"id": "status-1", "name": "Rendering"},
        "Render review",
        "/tmp/sh010-render-v001.mp4",
    )
    result = {}
    worker.upload_finished.connect(
        lambda ok, message: result.update(ok=ok, message=message)
    )

    worker.run()

    assert result["ok"] is True
    task, status, kwargs = production.kitsu.calls[0]
    assert task["id"] == "task-1"
    assert status["id"] == "status-1"
    assert kwargs["preview_file_path"] == "/tmp/sh010-render-v001.mp4"
    assert kwargs["comment"] == "Render review"
