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
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.interfaces.qt.components.project_card import ProjectCard
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
        **kwargs,
    ) -> None:
        super().__init__(parent, **kwargs)

        self.vm = viewmodel
        self.audit_vm = audit_vm
        self.repair_vm = repair_vm
        self.on_open_wizard_callback = on_open_wizard_callback
        self.on_new_project_callback = on_new_project_callback
        self.on_repair_callback = on_repair_callback

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

            self.btn_new_project = QPushButton(self.tr("Create New Project"))
            self.btn_new_project.setObjectName("PrimaryButton")
            self.btn_new_project.setFixedSize(220, 40)
            self.btn_new_project.setCursor(Qt.PointingHandCursor)
            self.btn_new_project.clicked.connect(self._open_new_project)
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
        self.vm.migration_finished.connect(self._on_migration_finished)
        self.vm.cleanup_finished.connect(lambda name, ok, msg: QMessageBox.information(self, self.tr("VCS Cleanup"), msg))
        self.audit_vm.audit_completed.connect(self._on_project_audited)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.btn_refresh.setEnabled(False)
        self.vm.refresh()

    def _open_new_project(self) -> None:
        if self.on_new_project_callback:
            self.on_new_project_callback()

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

    def _request_migration(self, project_name: str, project_dir) -> None:
        """Ask which VCS server the project should migrate to, then run it."""
        servers = self.vm.list_servers()
        if not servers:
            QMessageBox.information(
                self, self.tr("Migrate VCS"),
                self.tr("No VCS server is configured. Add one in the Infrastructure panel."),
            )
            return

        labels = [server["name"] + ("  (default)" if server.get("is_default") else "") for server in servers]
        choice, accepted = QInputDialog.getItem(
            self, self.tr("Migrate VCS"), self.tr("Target server:"), labels, 0, False
        )
        if not accepted:
            return
        target = servers[labels.index(choice)]
        self.vm.migrate_project(project_name, project_dir, target_server_id=target["id"])

    def _on_migration_finished(self, project_name: str, success: bool, message: str) -> None:
        if not success:
            QMessageBox.critical(self, self.tr("VCS Migration Failed"), message)
            return

        QMessageBox.information(self, self.tr("VCS Migration"), message)
        answer = QMessageBox.question(
            self,
            self.tr("Delete Old Repository"),
            self.tr(
                "The old local repository can be deleted now.\n\n"
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
