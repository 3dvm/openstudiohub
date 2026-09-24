# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/project_list_widget.py
# Architectural role: UI Widget / Project Grid
# =========================================================================================

"""Project grid widget.

Renders the responsive grid of project cards and forwards user actions to the
``ProjectListViewModel``.
"""

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.interfaces.qt.components.hub_project_config_dialog import HubProjectConfigDialog
from src.interfaces.qt.components.migration_progress_dialog import MigrationProgressDialog
from src.interfaces.qt.components.project_card import ProjectCard
from src.interfaces.qt.components.project_export_dialog import ProjectExportDialog
from src.interfaces.qt.components.project_import_dialog import ProjectImportDialog
from src.interfaces.qt.components.vcs_migration_dialog import MigrationServerDialog
from src.interfaces.qt.viewmodels.project_list_viewmodel import ProjectListViewModel
from src.interfaces.qt.viewmodels.project_audit_viewmodel import ProjectAuditViewModel
from src.interfaces.qt.viewmodels.project_repair_viewmodel import ProjectRepairViewModel
from src.interfaces.qt.views.repair_project_dialog import RepairBatchDialog

class ProjectListWidget(QFrame):
    def __init__(
        self,
        parent,
        viewmodel: ProjectListViewModel,
        audit_vm: ProjectAuditViewModel,
        repair_vm: ProjectRepairViewModel,
        on_open_wizard_callback: Optional[Callable] = None,
        on_new_project_callback: Optional[Callable] = None,
        on_repair_callback: Optional[Callable] = None,
        vault_service=None,
        **kwargs,
    ) -> None:
        super().__init__(parent, **kwargs)

        self.vm = viewmodel
        self.audit_vm = audit_vm
        self.repair_vm = repair_vm
        self.on_open_wizard_callback = on_open_wizard_callback
        self.on_new_project_callback = on_new_project_callback
        self.on_repair_callback = on_repair_callback
        self.vault_service = vault_service

        self.user_role = self.vm.user_role

        self._project_widgets = []
        self._cards_by_dir = {}
        self._cards_by_id = {}
        self._corrupted_projects = []
        self._current_cols = 0
        self._audit_generation = 0

        self.setObjectName("ProjectListWidgetBase")

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        content_layout = QVBoxLayout(self)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(20)

        hero_layout = QHBoxLayout()
        hero_layout.setContentsMargins(0, 0, 0, 0)

        if self.user_role != "td":
            lbl_title = QLabel(self.tr("My Assigned Projects"))
            lbl_title.setObjectName("H2Title")
            hero_layout.addWidget(lbl_title)

        hero_layout.addStretch()

        self.btn_refresh = QPushButton(self.tr("🔄 Refresh List"))
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.setFixedSize(150, 40)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh)
        hero_layout.addWidget(self.btn_refresh)

        if self.user_role == "td":
            self.btn_audit_system = QPushButton(self.tr("Repair Projects"))
            self.btn_audit_system.setObjectName("SecondaryButton")
            self.btn_audit_system.setFixedSize(150, 40)
            self.btn_audit_system.setCursor(Qt.PointingHandCursor)
            self.btn_audit_system.clicked.connect(self._on_repair_projects_clicked)
            hero_layout.addWidget(self.btn_audit_system)

            self.btn_new_project = QToolButton()
            self.btn_new_project.setObjectName("PrimaryButton")
            self.btn_new_project.setText(self.tr("Create New Project"))
            self.btn_new_project.setFixedSize(220, 40)
            self.btn_new_project.setCursor(Qt.PointingHandCursor)
            self.btn_new_project.setPopupMode(QToolButton.InstantPopup)
            self.btn_new_project.setStyleSheet(
                "QToolButton { background-color: #3B82F6; color: white; font-weight: bold; "
                "border-radius: 6px; padding: 0 15px; } "
                "QToolButton:hover { background-color: #2563EB; } "
                "QToolButton::menu-indicator { image: none; }"
            )
            new_menu = QMenu(self.btn_new_project)
            new_menu.setStyleSheet(
                "QMenu { background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155; "
                "border-radius: 6px; } QMenu::item { padding: 8px 25px; } "
                "QMenu::item:selected { background-color: #3B82F6; }"
            )
            new_menu.addAction(self.tr("New Project"), self._open_new_project)
            new_menu.addAction(self.tr("Import Project (.oshproject)"), self._open_import_project)
            self.btn_new_project.setMenu(new_menu)
            hero_layout.addWidget(self.btn_new_project)

        content_layout.addLayout(hero_layout)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("InvisibleScrollArea")

        self.grid_widget = QWidget()
        self.grid_widget.setObjectName("TransparentGridContainer")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.scroll_area.setWidget(self.grid_widget)
        content_layout.addWidget(self.scroll_area, stretch=1)

    def _connect_signals(self) -> None:
        self.vm.projects_loaded.connect(self._render_projects)
        self.vm.refresh_requested.connect(self.refresh)
        self.vm.install_finished.connect(self._on_install_finished)
        self.vm.delete_warning.connect(lambda msg: QMessageBox.warning(self, self.tr("Warning"), msg))
        self.vm.delete_completed.connect(lambda msg: QMessageBox.information(self, self.tr("Deleted"), msg))
        self.vm.migration_started.connect(self._on_migration_started)
        self.vm.migration_detail.connect(self._on_migration_detail)
        self.vm.migration_log.connect(self._on_migration_log)
        self.vm.migration_phase.connect(self._on_migration_phase)
        self.vm.migration_finished.connect(self._on_migration_finished)
        self.vm.cleanup_finished.connect(lambda name, ok, msg: QMessageBox.information(self, self.tr("VCS Cleanup"), msg))
        self.vm.export_uncommitted_found.connect(self._on_export_uncommitted_found)
        self.vm.publish_changes_ready.connect(self._on_publish_changes_ready)
        self.vm.publish_up_to_date.connect(self._on_publish_up_to_date)
        self.audit_vm.audit_completed.connect(self._on_project_audited)

    def _on_publish_up_to_date(self, project_name: str) -> None:
        QMessageBox.information(
            self,
            self.tr("Publish to VCS"),
            self.tr(f"'{project_name}' has no uncommitted files. Everything is up to date."),
        )

    def _on_publish_changes_ready(self, project_name: str, changes: list) -> None:
        """Open the publish checklist for a project's uncommitted files."""
        from types import SimpleNamespace

        from src.interfaces.qt.views.vcs_publish_dialog import VcsPublishDialog

        card = SimpleNamespace(
            task_data={"id": "__publish__"},
            project_name=project_name,
            project_root=self.vm._project_root_for(project_name),
            task_file_path="",
        )
        dialog = VcsPublishDialog(
            self,
            self.vm,
            card,
            changes,
            task_label=self.tr(
                f"'{project_name}' has {len(changes)} uncommitted file(s). Publish them to the VCS."
            ),
        )
        dialog.exec()

    def _request_reset_working_copy(self, project_name: str) -> None:
        """Confirm and reset a project's VCS working copy (destructive)."""
        answer = QMessageBox.warning(
            self,
            self.tr("Reset VCS Working Copy"),
            self.tr(
                f"Reset the VCS working copy for '{project_name}'?\n\n"
                "This deletes the local production folder and checks it out again "
                "from the server. Any UNCOMMITTED local changes in that folder will "
                "be lost."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.vm.reset_vcs_working_copy(project_name)

    def _on_export_uncommitted_found(self, project_name: str, changes: list) -> None:
        """Offer to publish uncommitted files so the SVN dump is complete."""
        count = len(changes)
        answer = QMessageBox.question(
            self,
            self.tr("Uncommitted Files"),
            self.tr(
                f"'{project_name}' has {count} uncommitted file(s). They will be missing "
                "from the exported SVN dump. Publish them now?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.vm.publish_then_export(changes)
        else:
            self.vm.export_anyway()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.btn_refresh.setEnabled(False)
        self.vm.refresh()

    def _open_new_project(self) -> None:
        if self.on_new_project_callback:
            self.on_new_project_callback()

    # ------------------------------------------------------------------
    # Kitsu export
    # ------------------------------------------------------------------
    def _request_export(self, project_name: str, project_id: str) -> None:
        dialog = ProjectExportDialog(self, project_name, default_dir=getattr(self.vm, "nas_dir", None))
        dialog.estimate_requested.connect(
            lambda options, pid=project_id, name=project_name: self.vm.estimate_export(pid, name, options)
        )
        dialog.start_requested.connect(
            lambda destination, options, pid=project_id, name=project_name: self.vm.request_export(
                pid, name, destination, options
            )
        )
        dialog.cancel_requested.connect(self.vm.cancel_export)

        self.vm.export_estimate_ready.connect(dialog.set_estimate)
        self.vm.export_phase.connect(dialog.set_phase)
        self.vm.export_log.connect(dialog.append_log)
        self.vm.export_progress.connect(dialog.set_progress)
        self.vm.export_finished.connect(dialog.on_export_finished)

        self._export_dialog = dialog
        dialog.finished.connect(lambda _result, d=dialog: self._release_export_dialog(d))
        dialog.show()

    def _release_export_dialog(self, dialog) -> None:
        if getattr(self, "_export_dialog", None) is dialog:
            self._export_dialog = None
        dialog.deleteLater()

    # ------------------------------------------------------------------
    # Kitsu import
    # ------------------------------------------------------------------
    def _open_import_project(self) -> None:
        dialog = ProjectImportDialog(self)
        try:
            servers = self.vm.list_servers()
            default_id = next(
                (str(server.get("id", "")) for server in servers if server.get("is_default")),
                "",
            )
            dialog.set_vcs_servers(servers, default_id)
        except Exception:  # noqa: BLE001
            pass
        try:
            dialog.set_default_topography(self.vm.target_topography())
        except Exception:  # noqa: BLE001
            pass

        dialog.inspect_requested.connect(self.vm.load_import_archive)
        dialog.repo_probe_requested.connect(self.vm.probe_import_repository)
        dialog.create_person_requested.connect(self.vm.create_target_person)
        dialog.start_requested.connect(lambda person_map, options: self.vm.import_project(person_map, options))
        dialog.cancel_requested.connect(self.vm.cancel_import)
        dialog.checkout_requested.connect(self.vm.checkout_imported_project)
        dialog.rollback_requested.connect(self.vm.rollback_import)

        self.vm.import_plan_ready.connect(dialog.on_plan_ready)
        self.vm.import_repo_status.connect(dialog.set_repo_status)
        self.vm.import_conflict.connect(dialog.set_conflict)
        self.vm.import_person_created.connect(dialog.on_person_created)
        self.vm.import_person_failed.connect(lambda message: QMessageBox.warning(self, self.tr("Person"), message))
        self.vm.import_phase.connect(dialog.set_phase)
        self.vm.import_log.connect(dialog.append_log)
        self.vm.import_progress.connect(dialog.set_progress)
        self.vm.import_finished.connect(dialog.finalize)
        self.vm.checkout_finished.connect(
            lambda ok, message: QMessageBox.information(self, self.tr("Checkout"), message)
        )
        self.vm.rollback_finished.connect(
            lambda ok, message: QMessageBox.information(self, self.tr("Rollback"), message)
        )

        self._import_dialog = dialog
        dialog.finished.connect(lambda _result, d=dialog: self._release_import_dialog(d))
        dialog.show()

    def _release_import_dialog(self, dialog) -> None:
        if getattr(self, "_import_dialog", None) is dialog:
            self._import_dialog = None
        dialog.deleteLater()

    def _on_repair_projects_clicked(self) -> None:
        """Shows a selectable list of damaged projects and repairs the chosen ones."""
        if not self._corrupted_projects:
            QMessageBox.information(self, self.tr("Repair"), self.tr("No damaged project available to repair."))
            return

        dialog = RepairBatchDialog(self, self._corrupted_projects)
        if not dialog.exec():
            return

        for project in dialog.selected_projects():
            self._request_repair(project["name"], project["id"], project["error_code"])

    def _request_repair(self, project_name: str, project_id: str, error_code: str) -> None:
        if self.on_repair_callback:
            self.on_repair_callback(project_name, project_id, error_code)

    def _request_config(self, project_name: str, project_id: str, project_dir=None) -> None:
        """Open the local HubProject configuration dialog for a card."""
        config = self.vm.project_config(project_name, project_id)
        dialog = HubProjectConfigDialog(
            self,
            config,
            on_probe=self.vm.probe_project_vcs,
            on_save=lambda payload, pid=project_id, pdir=config.get("project_dir"): (
                self.vm.save_project_config(pdir, pid, payload)
            ),
            vault_service=self.vault_service,
        )
        dialog.exec()

    def _request_migration(self, project_name: str, project_dir) -> None:
        """Ask which VCS server the project should migrate to, then run it."""
        servers = self.vm.list_servers()
        source = self.vm.server_for_project(project_dir)
        if source is None:
            QMessageBox.information(
                self, self.tr("Migrate VCS"),
                self.tr("Could not resolve the project's current VCS server."),
            )
            return

        targets = [
            server for server in servers
            if server.get("adapter") == "svn" and server.get("id") != source.get("id")
        ]
        if not targets:
            QMessageBox.information(
                self, self.tr("Migrate VCS"),
                self.tr("No other SVN server is available to migrate to."),
            )
            return

        default_target = next((s["id"] for s in targets if s.get("is_default")), targets[0]["id"])
        dialog = MigrationServerDialog(self, project_name, source, targets, default_target)
        if dialog.exec() != QDialog.Accepted:
            return
        self.vm.migrate_project(project_name, project_dir, target_server_id=dialog.selected_target_id())

    # ------------------------------------------------------------------
    # Migration progress window
    # ------------------------------------------------------------------
    def _on_migration_started(self, project_name: str, source: dict, target: dict) -> None:
        self._migration_dialog = MigrationProgressDialog(self, project_name, source, target)
        self._migration_dialog.set_phase(self.tr("Starting transfer..."))
        self._migration_dialog.cancel_requested.connect(
            lambda p=project_name: self._on_migration_cancelled(p)
        )
        self._migration_dialog.show()

    def _on_migration_detail(self, detail: dict) -> None:
        dialog = getattr(self, "_migration_dialog", None)
        if dialog is not None:
            dialog.update_detail(detail)

    def _on_migration_log(self, line: str) -> None:
        dialog = getattr(self, "_migration_dialog", None)
        if dialog is not None:
            dialog.append_log(line)

    def _on_migration_phase(self, message: str) -> None:
        dialog = getattr(self, "_migration_dialog", None)
        if dialog is not None:
            dialog.set_phase(message)

    def _on_migration_cancelled(self, project_name: str) -> None:
        self.vm.cancel_migration(project_name)
        dialog = getattr(self, "_migration_dialog", None)
        if dialog is not None:
            dialog.append_log("Cancellation requested; terminating processes...")

    def _on_migration_finished(self, project_name: str, success: bool, message: str) -> None:
        dialog = getattr(self, "_migration_dialog", None)
        if dialog is not None:
            dialog.finalize(success, message)

        if not success:
            answer = QMessageBox.question(
                self,
                self.tr("VCS Migration Failed"),
                self.tr(
                    f"{message}\n\nThe target repository may be partially loaded. "
                    "Delete it now?"
                ),
            )
            if answer == QMessageBox.Yes:
                self.vm.delete_target_repository(project_name)
            return

        source_name = self.vm.migration_source_name(project_name)
        answer = QMessageBox.question(
            self,
            self.tr("Delete Old Repository"),
            self.tr(
                f"The old repository on '{source_name}' can be deleted now.\n\n"
                "Delete it, or keep it orphaned?"
            ),
        )
        if answer == QMessageBox.Yes:
            self.vm.cleanup_local_repository(project_name)

    # ------------------------------------------------------------------
    # Responsive grid
    # ------------------------------------------------------------------
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._rearrange_grid()

    def _rearrange_grid(self) -> None:
        if not self._project_widgets:
            return
        viewport_width = self.scroll_area.viewport().width()
        card_width = 340 if self.user_role != "td" else 320
        spacing = self.grid_layout.spacing()
        cols = max(1, (viewport_width + spacing) // (card_width + spacing))

        if getattr(self, "_current_cols", 0) == cols:
            return
        self._current_cols = cols
        row, col = 0, 0

        for widget in self._project_widgets:
            self.grid_layout.removeWidget(widget)
            self.grid_layout.addWidget(widget, row, col)

            col += 1
            if col >= cols:
                col = 0
                row += 1

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render_projects(self, projects: list) -> None:
        self._clear_grid()
        self.btn_refresh.setEnabled(True)

        # A new render invalidates any in-flight audit: bump the generation so
        # stale results are discarded, and re-audit every card from scratch.
        self._audit_generation += 1
        audit_token = self._audit_generation

        token = self.vm.token
        host = self.vm.host

        for project_data in projects:
            project_id = project_data.get("id", "")

            card = ProjectCard(
                parent=self.grid_widget,
                project_data=project_data,
                user_role=self.user_role,
                status=None,
                token=token,
                host=host,
                thumbnail_fetcher=self.vm.thumbnail_fetcher,
                on_install=self.vm.install_project,
                on_launch=self.vm.launch_project,
                on_delete=lambda name, pid=project_id: self.vm.delete_project(name, pid),
                on_open_kitsu=lambda sub_path, pid=project_id: self.vm.open_kitsu(pid, sub_path),
                on_watchtower=self.vm.open_watchtower,
                on_open_wizard=self.on_open_wizard_callback,
                on_repair=self._request_repair,
                on_migrate=self._request_migration,
                on_export=lambda name, pid=project_id: self._request_export(name, pid),
                on_publish=lambda name, pid=project_id: self.vm.request_project_publish(name),
                on_reset=lambda name, pid=project_id: self._request_reset_working_copy(name),
                on_configure=self._request_config,
            )

            self._project_widgets.append(card)
            self._cards_by_id[project_id] = card

        self._current_cols = 0
        self._rearrange_grid()

        self.audit_vm.audit_projects(projects, token=audit_token)

    def _on_project_audited(self, token: int, project_data: dict, hub_project) -> None:
        """Apply an audited ``HubProject`` to its card once the background audit resolves."""
        if token != self._audit_generation:
            return

        project_id = project_data.get("id", "")
        card = self._cards_by_id.get(project_id)
        if card is None:
            return

        status = self.vm.status_from_hub_project(project_data.get("name", ""), hub_project)
        card.apply_status(status)

        project_dir = status.get("project_dir")
        if project_dir is not None:
            self._cards_by_dir[str(project_dir)] = card

        if status.get("is_corrupted"):
            self._corrupted_projects.append({
                "name": project_data.get("name", ""),
                "id": project_id,
                "error_code": status.get("error_code"),
                "error_type": status.get("error_type"),
            })

    def _clear_grid(self) -> None:
        for widget in self._project_widgets:
            widget.hide()
            widget.deleteLater()
        self._project_widgets.clear()
        self._cards_by_dir.clear()
        self._cards_by_id.clear()
        self._corrupted_projects.clear()

        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _on_install_finished(self, project_dir, success: bool, message: str) -> None:
        card = self._cards_by_dir.get(str(project_dir))
        if card is not None:
            card.set_install_result(success, message)
