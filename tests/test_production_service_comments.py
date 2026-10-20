"""Unit tests for the task-board/comment helpers on ProductionService."""

from src.application.services.production_service import ProductionService


class FakeKitsu:
    def __init__(self):
        self.tasks = {
            "t1": {
                "id": "t1",
                "name": "main",
                "entity_id": "e1",
                "task_type_id": "tt1",
                "task_status_id": "ts1",
                "assignees": ["u1"],
            }
        }
        self.assign_calls = []
        self.clear_calls = []

    def all_tasks_for_project(self, _project_id):
        return [dict(self.tasks["t1"])]

    def all_persons(self):
        return [
            {"id": "u1", "full_name": "Ada", "email": "ada@studio.com"},
            {"id": "u2", "full_name": "Bob", "email": "bob@studio.com"},
        ]

    def all_task_types(self):
        return [{"id": "tt1", "name": "Modeling"}]

    def all_task_statuses_for_project(self, _project_id):
        return [{"id": "ts1", "name": "In Progress", "color": "#3B82F6"}]

    def get_task(self, task_id):
        return dict(self.tasks[task_id])

    def assign_task(self, task, person):
        self.assign_calls.append((str(task.get("id")), str(person.get("id"))))
        assignees = list(self.tasks[task["id"]].get("assignees") or [])
        if person["id"] not in assignees:
            assignees.append(person["id"])
        self.tasks[task["id"]]["assignees"] = assignees

    def clear_task_assignations(self, task, person=None):
        self.clear_calls.append((str(task.get("id")), str((person or {}).get("id", ""))))
        assignees = list(self.tasks[task["id"]].get("assignees") or [])
        if person and person.get("id") in assignees:
            assignees.remove(person["id"])
        self.tasks[task["id"]]["assignees"] = assignees

    def all_comments_for_task(self, _task):
        return [{"id": "c1", "task_id": "t1", "text": "hi", "person_id": "u2"}]

    def all_comments_for_project(self, _project_id):
        return [{"id": "c1", "task_id": "t1", "text": "hi", "person_id": "u2"}]

    def add_comment(self, task, status, comment="", **_kwargs):
        return {"id": "c2", "task_id": task["id"], "text": comment, "task_status_id": status["id"]}

    def update_comment_checklist(self, comment_id, checklist):
        self.updated_checklist = (comment_id, checklist)
        return {"id": comment_id, "checklist": checklist}

    def get_task_status(self, status_id):
        return {"id": status_id, "name": "In Progress", "color": "#3B82F6"}


def test_get_project_task_board_enriches_rows():
    service = ProductionService(FakeKitsu())

    rows = service.get_project_task_board("p1")

    assert rows[0]["task_type_name"] == "Modeling"
    assert rows[0]["task_status"]["name"] == "In Progress"
    assert rows[0]["assignees"][0]["full_name"] == "Ada"
    assert rows[0]["entity_name"] == "e1"


def test_apply_task_assignees_adds_and_removes():
    kitsu = FakeKitsu()
    service = ProductionService(kitsu)
    task = dict(kitsu.tasks["t1"])

    assignees = service.apply_task_assignees(task, ["u2"], ["u1"])

    assert ("t1", "u2") in kitsu.assign_calls
    assert ("t1", "u1") in kitsu.clear_calls
    assert [person["id"] for person in assignees] == ["u2"]


def test_comment_helpers_delegate_to_kitsu():
    kitsu = FakeKitsu()
    service = ProductionService(kitsu)

    assert service.get_task_comments({"id": "t1"})[0]["text"] == "hi"
    assert service.get_project_comments("p1")[0]["task_id"] == "t1"
    assert service.add_task_comment({"id": "t1"}, {"id": "ts1"}, "note")["text"] == "note"
    assert service.get_task_status({"task_status_id": "ts1"})["name"] == "In Progress"

    checklist = [{"text": "Check lighting", "checked": True}]
    assert service.update_comment_checklist("c1", checklist)["checklist"] == checklist
    assert kitsu.updated_checklist == ("c1", checklist)
