# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/api_queries.py
# Architectural role: Thin QThread adapters (delegate to ProductionService)
# =========================================================================================

"""Thin QThread adapters.

The audit/enrichment logic now lives in ``ProductionService``; these workers
only invoke a service method and re-emit the result as Qt signals.
"""

from pathlib import Path

from PySide6.QtCore import QThread, Signal


class FetchProjectsWorker(QThread):
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, production_service):
        super().__init__()
        self.production_service = production_service

    def run(self):
        try:
            self.data_ready.emit(self.production_service.list_all_projects())
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))


class FetchShotsWorker(QThread):
    data_ready = Signal(list, list)
    error_occurred = Signal(str)

    def __init__(self, production_service, project_id: str, project_root: Path, vfs_svn: str):
        super().__init__()
        self.production_service = production_service
        self.project_id = project_id
        self.project_root = project_root
        self.vfs_svn = vfs_svn

    def run(self):
        try:
            result, task_types = self.production_service.audit_shots(self.project_id, self.project_root, self.vfs_svn)
            self.data_ready.emit(result, task_types)
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))


class FetchEntitiesWorker(QThread):
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, pm_core, project_id):
        super().__init__()
        self.pm_core = pm_core
        self.project_id = project_id

    def run(self):
        try:
            self.data_ready.emit(self.pm_core.get_pending_entities(self.project_id))
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))


class FetchSequencesWorker(QThread):
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, production_service, project_id: str, project_root: Path, vfs_svn: str):
        super().__init__()
        self.production_service = production_service
        self.project_id = project_id
        self.project_root = project_root
        self.vfs_svn = vfs_svn

    def run(self):
        try:
            self.data_ready.emit(self.production_service.audit_sequences(self.project_id, self.project_root, self.vfs_svn))
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))


class FetchAssetsWorker(QThread):
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, production_service, project_id: str, project_root: Path, vfs_svn: str):
        super().__init__()
        self.production_service = production_service
        self.project_id = project_id
        self.project_root = project_root
        self.vfs_svn = vfs_svn

    def run(self):
        try:
            self.data_ready.emit(self.production_service.audit_assets(self.project_id, self.project_root, self.vfs_svn))
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))


class FetchEditStatusWorker(QThread):
    data_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, production_service, project_id: str, project_name: str, project_root: Path, vfs_svn: str):
        super().__init__()
        self.production_service = production_service
        self.project_id = project_id
        self.project_name = project_name
        self.project_root = project_root
        self.vfs_svn = vfs_svn

    def run(self):
        try:
            self.data_ready.emit(
                self.production_service.audit_edit(self.project_id, self.project_name, self.project_root, self.vfs_svn)
            )
        except Exception as error:  # noqa: BLE001
            self.error_occurred.emit(str(error))
