# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/repair_project_dialog.py
# Architectural role: UI View / Modal Dialogs (PySide6)
# =========================================================================================

"""Repair dialogs for damaged HubProjects.

``RepairProjectDialog`` collects the missing data from the TD and forwards it to
``ProjectRepairViewModel``. ``RepairBatchDialog`` lets the TD pick which damaged
projects to repair from a selectable list.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.workspace.blueprint import ProjectBlueprint
from src.domain.workspace.entities import (
    ERROR_INVALID_BLUEPRINT,
    ERROR_KITSU_ORPHAN,
    ERROR_MISSING_BLUEPRINT,
    ERROR_NAS_GHOST,
)
from src.interfaces.qt.viewmodels.project_repair_viewmodel import ProjectRepairViewModel
from src.interfaces.qt.workers.new_project_workers import FetchKitsuTemplatesWorker


class RepairProjectDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        repair_vm: ProjectRepairViewModel,
        production_service,
        vault_service,
        config_factory,
        project_name: str,
        project_id: str,
        error_code: str,
        on_success_callback,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Repair Project"))
        self.setFixedSize(500, 640)
        self.setModal(True)

        self.repair_vm = repair_vm
        self.production_service = production_service
        self.vault_service = vault_service
        self.config_factory = config_factory
        self.project_name = project_name
        self.project_id = project_id
        self.error_code = error_code
        self.on_success = on_success_callback

        self.vault_data = self.vault_service.load_inventory()
        self.tool_checkboxes = {}
        self.template_group = None
        self._templates_worker = None
        self._repair_connected = False

        self.setObjectName("ViewLoginBase")
        self._build_ui()

        if error_code == ERROR_NAS_GHOST:
            self._load_kitsu_templates()
        else:
            self._draw_dynamic_dependencies(self.combo_version.currentText())

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 30, 40, 30)
        main_layout.setSpacing(15)

        lbl_title = QLabel(self.tr("Repair Project"))
        lbl_title.setObjectName("CardTitle")
        lbl_title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(lbl_title)

        main_layout.addSpacing(5)

        lbl_name = QLabel(self.tr("Project:"))
        lbl_name.setStyleSheet("font-weight: bold; margin-top: 10px;")
        main_layout.addWidget(lbl_name)

        self.entry_name = QLineEdit(self.project_name)
        self.entry_name.setObjectName("FormInput")
        self.entry_name.setReadOnly(True)
        self.entry_name.setFixedHeight(45)
        main_layout.addWidget(self.entry_name)

        if self.error_code == ERROR_NAS_GHOST:
            self._build_nas_ghost_fields(main_layout)
        else:
            self._build_kitsu_orphan_fields(main_layout)

        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.hide()
        main_layout.addWidget(self.lbl_status)

        self.btn_repair = QPushButton(self.tr("Repair Project"))
        self.btn_repair.setObjectName("PrimaryButton")
        self.btn_repair.setFixedHeight(50)
        self.btn_repair.setCursor(Qt.PointingHandCursor)
        self.btn_repair.clicked.connect(self._execute_repair)
        main_layout.addWidget(self.btn_repair)

    def _build_nas_ghost_fields(self, main_layout) -> None:
        lbl_template = QLabel(self.tr("Kitsu Template:"))
        lbl_template.setStyleSheet("font-weight: bold; margin-top: 10px;")
        main_layout.addWidget(lbl_template)

        self.combo_kitsu_template = QComboBox()
        self.combo_kitsu_template.setFixedHeight(40)
        self.combo_kitsu_template.setStyleSheet(
            "QComboBox { background-color: #0F172A; border: 1px solid #475569; border-radius: 8px; color: #F8FAFC; padding: 5px; }"
        )
        self.combo_kitsu_template.addItem(self.tr("Loading templates..."))
        self.combo_kitsu_template.setEnabled(False)
        main_layout.addWidget(self.combo_kitsu_template)
        main_layout.addStretch(1)

    def _build_kitsu_orphan_fields(self, main_layout) -> None:
        lbl_version = QLabel(self.tr("Target Blender Version:"))
        lbl_version.setStyleSheet("font-weight: bold; margin-top: 10px;")
        main_layout.addWidget(lbl_version)

        versions = list(self.vault_data.keys()) if self.vault_data else []
        self.combo_version = QComboBox()
        self.combo_version.addItems(versions)
        self.combo_version.setFixedHeight(40)
        self.combo_version.setStyleSheet(
            "QComboBox { background-color: #0F172A; border: 1px solid #475569; border-radius: 8px; color: #F8FAFC; padding: 5px; }"
        )
        self.combo_version.currentTextChanged.connect(self._draw_dynamic_dependencies)
        main_layout.addWidget(self.combo_version)

        lbl_addons = QLabel(self.tr("Vault Components (vault_manifest.json):"))
        lbl_addons.setStyleSheet("font-weight: bold; margin-top: 15px;")
        main_layout.addWidget(lbl_addons)

        self.scroll_addons = QScrollArea()
        self.scroll_addons.setWidgetResizable(True)
        self.scroll_addons.setStyleSheet(
            "QScrollArea { border: 1px solid #334155; border-radius: 8px; background-color: #1E293B; }"
        )
        self.addons_widget = QWidget()
        self.addons_widget.setStyleSheet("background: transparent;")
        self.addons_layout = QVBoxLayout(self.addons_widget)
        self.addons_layout.setAlignment(Qt.AlignTop)
        self.scroll_addons.setWidget(self.addons_widget)
        main_layout.addWidget(self.scroll_addons, stretch=1)

        self.lbl_vcs = QLabel(self.tr("Version Control System (VCS):"))
        main_layout.addWidget(self.lbl_vcs)
        self.combo_vcs = QComboBox()
        self.combo_vcs.addItems(["Settings Default", "SVN", "Git-LFS", "None (NAS only)"])
        main_layout.addWidget(self.combo_vcs)

    # ------------------------------------------------------------------
    # Template / dependencies loaders
    # ------------------------------------------------------------------
    def _load_kitsu_templates(self) -> None:
        self._templates_worker = FetchKitsuTemplatesWorker(self.production_service)
        self._templates_worker.data_ready.connect(self._on_templates_loaded)
        self._templates_worker.finished.connect(self._on_templates_worker_finished)
        self._templates_worker.start()

    def _on_templates_worker_finished(self) -> None:
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        self._templates_worker = None

    def _on_templates_loaded(self, templates: list) -> None:
        self.combo_kitsu_template.clear()
        if not templates:
            self.combo_kitsu_template.addItem("")  # Kitsu default (no template)
        else:
            for template in templates:
                self.combo_kitsu_template.addItem(template["name"])
        self.combo_kitsu_template.setEnabled(True)

    def _clear_addons_layout(self) -> None:
        while self.addons_layout.count():
            child = self.addons_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _draw_dynamic_dependencies(self, selected_version: str) -> None:
        self._clear_addons_layout()
        self.tool_checkboxes.clear()
        self.template_group = QButtonGroup(self)
        if not selected_version:
            return

        available_categories = self.vault_data.get(selected_version, {})
        if not available_categories:
            return

        for category, items in available_categories.items():
            lbl_cat = QLabel(f"[{category.upper()}]")
            lbl_cat.setStyleSheet("color: #10B981; font-weight: bold; margin-top: 10px;")
            self.addons_layout.addWidget(lbl_cat)
            self.tool_checkboxes[category] = {}

            for item_name, data in items.items():
                item_version = data.get("version", "1.0")
                is_mandatory = data.get("mandatory", False)
                label_text = f"{item_name} v{item_version} - {data.get('description', '')}"

                if category == "templates":
                    cb = QRadioButton(label_text)
                    cb.setStyleSheet("QRadioButton { color: #F8FAFC; padding: 5px; }")
                    self.template_group.addButton(cb)
                else:
                    cb = QCheckBox(label_text)
                    cb.setStyleSheet("QCheckBox { color: #F8FAFC; padding: 5px; }")

                cb.toggled.connect(
                    lambda checked, c=category, n=item_name, r=data.get("requires", []): self._resolve_sub_dependencies(checked, c, n, r)
                )
                self.addons_layout.addWidget(cb)

                if is_mandatory:
                    cb.setChecked(True)
                    cb.setEnabled(False)

                self.tool_checkboxes[category][item_name] = {"checkbox": cb, "version": item_version}

    def _resolve_sub_dependencies(self, checked: bool, parent_category: str, parent_name: str, requires: list) -> None:
        for req in requires:
            parts = req.split("/")
            if len(parts) != 2:
                continue
            cat_req, name_req = parts[0], parts[1]
            if cat_req in self.tool_checkboxes and name_req in self.tool_checkboxes[cat_req]:
                cb_sub = self.tool_checkboxes[cat_req][name_req]["checkbox"]
                cb_sub.setChecked(checked)
                cb_sub.setEnabled(not checked)

    # ------------------------------------------------------------------
    # Repair dispatch
    # ------------------------------------------------------------------
    def _execute_repair(self) -> None:
        if self.repair_vm.is_busy():
            self._set_busy_status(self.tr("Another repair is already in progress..."))
            return

        self._connect_repair_signal()

        if self.error_code == ERROR_NAS_GHOST:
            template_name = self.combo_kitsu_template.currentText().strip()
            self.btn_repair.setEnabled(False)
            self.btn_repair.setText(self.tr("Repairing..."))
            self._set_busy_status(self.tr("Recreating the Kitsu project..."))
            self.repair_vm.repair_nas_ghost(self.project_name, template_name)
            return

        if self.error_code in (ERROR_MISSING_BLUEPRINT, ERROR_INVALID_BLUEPRINT):
            blueprint = self._collect_blueprint()
            self.btn_repair.setEnabled(False)
            self.btn_repair.setText(self.tr("Repairing..."))
            self._set_busy_status(self.tr("Rebuilding the blueprint..."))
            self.repair_vm.repair_blueprint(
                self.project_name,
                self.project_id,
                blueprint,
                error_code=self.error_code,
            )
            return

        if self.error_code == ERROR_KITSU_ORPHAN:
            blueprint = self._collect_blueprint()
            vcs_enabled = self._resolve_vcs_enabled()

            self.btn_repair.setEnabled(False)
            self.btn_repair.setText(self.tr("Repairing..."))
            self._set_busy_status(self.tr("Rebuilding the NAS topography..."))
            self.repair_vm.repair_kitsu_orphan(
                self.project_name,
                self.project_id,
                blueprint,
                vcs_enabled=vcs_enabled,
            )

    def _collect_blueprint(self) -> ProjectBlueprint:
        version_blender = self.combo_version.currentText().strip()
        final_dependencies, main_template = {}, None
        for category, items in self.tool_checkboxes.items():
            final_dependencies[category] = {}
            for item_name, data in items.items():
                if data["checkbox"].isChecked():
                    final_dependencies[category][item_name] = data["version"]
                    if category == "templates":
                        main_template = item_name

        if not main_template:
            main_template = "Macuare_Estudio"

        return ProjectBlueprint(
            project_name=self.project_name,
            kitsu_project_id=self.project_id,
            blender_version=version_blender,
            template=main_template,
            dependencies=final_dependencies,
            topography=self.config_factory.get_topography(),
            vcs_enabled=True,
        )

    def _resolve_vcs_enabled(self) -> bool:
        vcs_config = self.config_factory.get_raw_config().get("vcs_engine", {})
        vcs_selection = self.combo_vcs.currentIndex()
        if vcs_selection == 3:
            return False
        if vcs_selection == 0:
            return vcs_config.get("active_adapter", "svn") != "none"
        return True

    def _set_busy_status(self, message: str) -> None:
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet("color: #F59E0B; font-weight: bold;")
        self.lbl_status.show()

    # ------------------------------------------------------------------
    # Signal lifecycle / safe teardown
    # ------------------------------------------------------------------
    def _connect_repair_signal(self) -> None:
        """Subscribe to the shared repair VM only for the duration of this repair."""
        if not self._repair_connected:
            self.repair_vm.repair_finished.connect(self._on_repair_finished)
            self._repair_connected = True

    def _disconnect_repair_signal(self) -> None:
        if self._repair_connected:
            try:
                self.repair_vm.repair_finished.disconnect(self._on_repair_finished)
            except (RuntimeError, TypeError):
                pass
            self._repair_connected = False

    def try_safe_delete(self) -> None:
        """Delete the dialog without destroying a still-running worker thread."""
        worker = self._templates_worker
        if worker is not None and worker.isRunning():
            worker.finished.connect(self.deleteLater)
        else:
            self.deleteLater()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._disconnect_repair_signal()
        super().closeEvent(event)

    def _on_repair_finished(self, success: bool, message: str) -> None:
        self._disconnect_repair_signal()
        if success:
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #10B981; font-weight: bold;")
            self.on_success()
            self.close()
        else:
            self.btn_repair.setEnabled(True)
            self.btn_repair.setText(self.tr("Repair Project"))
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #EF4444; font-weight: bold;")


class RepairBatchDialog(QDialog):
    """Selectable list of damaged projects to repair."""

    def __init__(self, parent: QWidget, damaged_projects: list) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Repair Projects"))
        self.setFixedSize(480, 420)
        self.setModal(True)
        self._build_ui(damaged_projects)

    def _build_ui(self, damaged_projects: list) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        lbl_title = QLabel(self.tr("Select projects to repair"))
        lbl_title.setObjectName("CardTitle")
        layout.addWidget(lbl_title)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155; border-radius: 8px; }"
        )
        for project in damaged_projects:
            label = f"{project['name']} — {project['error_type']}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, project)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_projects(self) -> list:
        result = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result
