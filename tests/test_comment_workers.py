"""Tests for the project-comments fallback used by comment badges."""

from src.interfaces.qt.workers.comment_workers import FetchProjectsCommentsWorker


class FakeProduction:
    def get_project_comments(self, _project_id):
        raise PermissionError("project comments forbidden")

    def get_task_comments(self, task):
        return [
            {
                "id": f"c-{task['id']}",
                "object_id": task["id"],
                "text": "fallback",
            }
        ]


def test_project_comments_fall_back_to_task_comments(qapp):
    worker = FetchProjectsCommentsWorker(
        FakeProduction(), {"p1": [{"id": "t1"}, {"id": "t2"}]}
    )
    captured = {}
    worker.data_ready.connect(lambda payload: captured.update(payload))

    worker.run()

    assert captured["p1"][0]["object_id"] == "t1"
    assert captured["p1"][1]["object_id"] == "t2"
