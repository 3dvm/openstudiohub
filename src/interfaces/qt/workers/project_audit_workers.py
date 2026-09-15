# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/project_audit_workers.py
# Architectural role: Thin QThread adapters for the project audit flow
# =========================================================================================

"""Project audit workers (filesystem + Kitsu health checks off the UI thread)."""

from PySide6.QtCore import QThread, Signal


class ProjectAuditWorker(QThread):
    """Audits every project on the grid without freezing the UI.

    Emits ``project_audited`` as soon as each ``HubProject`` is resolved so the
    matching card can be refreshed incrementally instead of waiting for the
    whole batch. The ``token`` identifies the grid render that requested the
    audit; the view discards results whose token is no longer current.
    """

    project_audited = Signal(int, object, object)  # (token, project_data: dict, hub_project)

    def __init__(self, audit_service, projects: list, token: int = 0) -> None:
        super().__init__()
        self.audit_service = audit_service
        self.projects = list(projects)
        self.token = token

    def run(self) -> None:
        for project_data in self.projects:
            project_name = project_data.get("name", "")
            kitsu_id = project_data.get("id", "")
            try:
                hub_project = self.audit_service.audit_project(project_name, kitsu_id)
            except Exception as error:  # noqa: BLE001
                print(f"[ProjectAudit] Error auditing '{project_name}': {error}")
                continue
            self.project_audited.emit(self.token, project_data, hub_project)
