# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/kitsu_migration_workers.py
# Architectural role: Thin QThread adapters for Kitsu export/import
# =========================================================================================

"""Background workers for the ``.oshproject`` export/import flow.

The application services push granular progress to a ``queue.Queue`` (drained on
the main thread by the ViewModel) and these thin workers only emit the final
result signals, exactly like the VCS migration workers.
"""

from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker


class KitsuExportEstimateWorker(ManagedWorker):
    """Computes the approximate export size table."""

    estimate_ready = Signal(dict)
    estimate_failed = Signal(str)

    def __init__(self, export_service, project_id: str, project_name: str, options: dict) -> None:
        super().__init__()
        self.export_service = export_service
        self.project_id = project_id
        self.project_name = project_name
        self.options = options

    def run(self) -> None:
        try:
            from src.application.services.kitsu_export_service import ExportOptions

            sizes = self.export_service.estimate(
                self.project_id, self.project_name, ExportOptions.from_dict(self.options)
            )
            self.estimate_ready.emit(sizes)
        except Exception as error:  # noqa: BLE001
            self.estimate_failed.emit(f"Size estimation failed: {error}")


class KitsuExportWorker(ManagedWorker):
    """Runs the export and emits the final outcome."""

    finished_export = Signal(str, bool, str, object)  # name, success, message, archive_path

    def __init__(self, export_service, project_id: str, project_name: str, destination_dir, options: dict) -> None:
        super().__init__()
        self.export_service = export_service
        self.project_id = project_id
        self.project_name = project_name
        self.destination_dir = destination_dir
        self.options = options

    def run(self) -> None:
        try:
            from src.application.services.kitsu_export_service import ExportOptions

            outcome = self.export_service.export(
                self.project_id, self.project_name, self.destination_dir,
                ExportOptions.from_dict(self.options),
            )
            self.finished_export.emit(self.project_name, outcome.success, outcome.message, outcome.archive_path)
        except Exception as error:  # noqa: BLE001
            self.finished_export.emit(self.project_name, False, f"Export crashed: {error}", None)


class KitsuImportInspectWorker(ManagedWorker):
    """Reads and validates an archive and resolves the target person list."""

    plan_ready = Signal(object, list)  # ImportPlan, target persons
    conflict = Signal(str)
    inspect_failed = Signal(str)

    def __init__(self, import_service, archive_path) -> None:
        super().__init__()
        self.import_service = import_service
        self.archive_path = archive_path

    def run(self) -> None:
        try:
            plan = self.import_service.inspect(self.archive_path)
            conflict = self.import_service.check_conflict(plan)
            if conflict:
                self.conflict.emit(conflict)
                return
            persons = self.import_service._safe(lambda: self.import_service.kitsu.all_persons(), [])
            self.plan_ready.emit(plan, persons)
        except Exception as error:  # noqa: BLE001
            self.inspect_failed.emit(f"Could not read the archive: {error}")


class KitsuImportRepoProbeWorker(ManagedWorker):
    """Probes the target VCS repository for the import's vfs_svn folder."""

    repo_status = Signal(dict)

    def __init__(self, import_service, plan, target_server_id: str = "") -> None:
        super().__init__()
        self.import_service = import_service
        self.plan = plan
        self.target_server_id = target_server_id

    def run(self) -> None:
        try:
            status = self.import_service.probe_repository(self.plan, self.target_server_id)
        except Exception as error:  # noqa: BLE001
            status = {
                "state": "unknown", "repo_name": "", "source": "", "target": "",
                "server_name": "", "dirs": [], "error": str(error),
            }
        self.repo_status.emit(status)


class KitsuCreatePersonWorker(ManagedWorker):
    """Creates a single target person (no password) during mapping."""

    person_created = Signal(object, object)  # source person, target person
    person_failed = Signal(object, str)

    def __init__(self, import_service, source_person: dict) -> None:
        super().__init__()
        self.import_service = import_service
        self.source_person = source_person

    def run(self) -> None:
        try:
            target = self.import_service.create_target_person(self.source_person)
            self.person_created.emit(self.source_person, target)
        except Exception as error:  # noqa: BLE001
            self.person_failed.emit(self.source_person, f"Could not create the person: {error}")


class KitsuImportWorker(ManagedWorker):
    """Runs the full import and emits the report."""

    finished_import = Signal(object)  # ImportReport

    def __init__(self, import_service, plan, person_map: dict, options: dict) -> None:
        super().__init__()
        self.import_service = import_service
        self.plan = plan
        self.person_map = person_map
        self.options = options

    def run(self) -> None:
        try:
            from src.application.services.kitsu_import_service import ImportOptions

            report = self.import_service.import_project(
                self.plan, person_map=self.person_map, options=ImportOptions.from_dict(self.options)
            )
        except Exception as error:  # noqa: BLE001
            from src.application.services.kitsu_import_service import ImportReport

            report = ImportReport(False, f"Import crashed: {error}")
        self.finished_import.emit(report)


class KitsuCheckoutWorker(ManagedWorker):
    """Checks out the imported project from VCS after the Kitsu import."""

    finished_checkout = Signal(bool, str)

    def __init__(self, import_service, project_root, vcs_user: str, vcs_pwd: str, user_role: str = "td") -> None:
        super().__init__()
        self.import_service = import_service
        self.project_root = project_root
        self.vcs_user = vcs_user
        self.vcs_pwd = vcs_pwd
        self.user_role = user_role

    def run(self) -> None:
        try:
            ok, message = self.import_service.checkout_project(
                self.project_root, self.vcs_user, self.vcs_pwd, self.user_role
            )
        except Exception as error:  # noqa: BLE001
            ok, message = False, f"Checkout crashed: {error}"
        self.finished_checkout.emit(ok, message)


class KitsuRollbackWorker(ManagedWorker):
    """Deletes a partially-created Kitsu project after a failed import."""

    finished_rollback = Signal(bool, str)

    def __init__(self, import_service, plan, project_id: str) -> None:
        super().__init__()
        self.import_service = import_service
        self.plan = plan
        self.project_id = project_id

    def run(self) -> None:
        try:
            ok, message = self.import_service.rollback(self.plan, self.project_id)
        except Exception as error:  # noqa: BLE001
            ok, message = False, f"Rollback crashed: {error}"
        self.finished_rollback.emit(ok, message)
