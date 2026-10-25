# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/task_board_workers.py
# Architectural role: Thin QThread adapters for the PM/TD task board
# =========================================================================================

"""Task board workers: project list, tasks, people, thumbnails and assignment."""

from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker


class FetchProjectsWorker(ManagedWorker):
    data_ready = Signal(list)

    def __init__(self, production_service) -> None:
        super().__init__()
        self.production_service = production_service

    def run(self) -> None:
        try:
            self.data_ready.emit(self.production_service.list_open_projects() or [])
        except Exception:  # noqa: BLE001
            self.data_ready.emit([])


class FetchProjectTaskBoardWorker(ManagedWorker):
    data_ready = Signal(str, list)  # (project_id, tasks)

    def __init__(self, production_service, project_id: str) -> None:
        super().__init__()
        self.production_service = production_service
        self.project_id = str(project_id or "")

    def run(self) -> None:
        try:
            tasks = self.production_service.get_project_task_board(self.project_id) or []
        except Exception:  # noqa: BLE001
            tasks = []
        self.data_ready.emit(self.project_id, tasks)


class FetchPersonsWorker(ManagedWorker):
    data_ready = Signal(list)

    def __init__(self, production_service) -> None:
        super().__init__()
        self.production_service = production_service

    def run(self) -> None:
        try:
            self.data_ready.emit(self.production_service.list_persons() or [])
        except Exception:  # noqa: BLE001
            self.data_ready.emit([])


class AssignTaskWorker(ManagedWorker):
    finished_assign = Signal(str, bool, str, list)  # (task_id, ok, message, assignees)

    def __init__(
        self,
        production_service,
        task_id: str,
        task_ref,
        add_ids: list,
        remove_ids: list,
    ) -> None:
        super().__init__()
        self.production_service = production_service
        self.task_id = str(task_id or "")
        self.task_ref = task_ref
        self.add_ids = list(add_ids or [])
        self.remove_ids = list(remove_ids or [])

    def run(self) -> None:
        try:
            assignees = self.production_service.apply_task_assignees(
                self.task_ref, self.add_ids, self.remove_ids
            )
            self.finished_assign.emit(self.task_id, True, "Assignees updated.", assignees)
        except Exception as error:  # noqa: BLE001
            self.finished_assign.emit(self.task_id, False, str(error), [])


class FetchThumbnailsWorker(ManagedWorker):
    """Download entity thumbnails sequentially and emit each result."""

    image_ready = Signal(str, bytes)  # (entity_id, image bytes)

    def __init__(self, token: str, host: str, entity_ids: list) -> None:
        super().__init__()
        self.token = token
        self.host = host
        self.entity_ids = [str(eid) for eid in entity_ids or [] if eid]

    def run(self) -> None:
        import requests

        headers = {"Authorization": f"Bearer {self.token}"}
        for entity_id in self.entity_ids:
            try:
                entity = requests.get(
                    f"{self.host}/data/entities/{entity_id}", headers=headers, timeout=10
                )
                if entity.status_code != 200:
                    continue
                preview_id = (entity.json() or {}).get("preview_file_id")
                if not preview_id:
                    continue
                image = requests.get(
                    f"{self.host}/pictures/thumbnails/preview-files/{preview_id}.png",
                    headers=headers,
                    timeout=10,
                )
                if image.status_code == 200:
                    self.image_ready.emit(entity_id, image.content)
            except Exception:  # noqa: BLE001 - a broken thumbnail must not stop the rest
                continue
