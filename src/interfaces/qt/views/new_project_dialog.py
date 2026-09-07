# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/new_project_dialog.py
# Architectural role: UI View / Modal Dialog (PySide6)
# =========================================================================================

"""Modal wizard for creating new projects (TD wizard).

Collects the form inputs and forwards them to ``NewProjectViewModel``.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.infrastructure.dev_defaults import DEV_SVN_PASSWORD, DEV_SVN_USER
from src.interfaces.qt.viewmodels.new_project_viewmodel import NewProjectViewModel


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget, viewmodel: NewProjectViewModel, on_success_callback) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("New Project"))
        self.setFixedSize(500, 700)
        self.setModal(True)

        self.vm = viewmodel
        self.on_success = on_success_callback

        self.splash_path = ""
        self.vault_data = self.vm.vault_data
        self.tool_checkboxes = {}
        self.template_group = None

        self.setObjectName("ViewLoginBase")
        self._build_ui()
        self.vm.templates_loaded.connect(self._on_templates_loaded)
        self.vm.creation_finished.connect(self._on_creation_finished)
        self.vm.load_templates()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 30, 40, 30)
        main_layout.setSpacing(15)

        lbl_title = QLabel(self.tr("Initial Setup"))
        lbl_title.setObjectName("CardTitle")
        lbl_title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(lbl_title)

        main_layout.addSpacing(10)

        self.entry_name = QLineEdit()
        self.entry_name.setObjectName("FormInput")
        self.entry_name.setPlaceholderText(self.tr("Name (e.g., p0004-new-project)"))
        self.entry_name.setFixedHeight(45)
        main_layout.addWidget(self.entry_name)

        lbl_kitsu_template = QLabel(self.tr("Kitsu Template:"))
        lbl_kitsu_template.setStyleSheet("font-weight: bold; margin-top: 10px;")
        main_layout.addWidget(lbl_kitsu_template)

        self.combo_kitsu_template = QComboBox()
        self.combo_kitsu_template.setFixedHeight(40)
        self.combo_kitsu_template.setStyleSheet("QComboBox { background-color: #0F172A; border: 1px solid #475569; border-radius: 8px; color: #F8FAFC; padding: 5px; }")
        self.combo_kitsu_template.addItem(self.tr("Loading templates..."))
        self.combo_kitsu_template.setEnabled(False)
        main_layout.addWidget(self.combo_kitsu_template)

        self.lbl_vcs = QLabel(self.tr("Version Control System (VCS):"))
        main_layout.addWidget(self.lbl_vcs)
        self.combo_vcs = QComboBox()
        self.combo_vcs.addItems(["Settings Default", "SVN", "Git-LFS", "None (NAS only)"])
        main_layout.addWidget(self.combo_vcs)

        lbl_version = QLabel(self.tr("Target Blender Version:"))
        lbl_version.setStyleSheet("font-weight: bold; margin-top: 10px;")
        main_layout.addWidget(lbl_version)

        versions = list(self.vault_data.keys()) if self.vault_data else []
        self.combo_version = QComboBox()
        self.combo_version.addItems(versions)
        self.combo_version.setFixedHeight(40)
        self.combo_version.setStyleSheet("QComboBox { background-color: #0F172A; border: 1px solid #475569; border-radius: 8px; color: #F8FAFC; padding: 5px; }")
        self.combo_version.currentTextChanged.connect(self._draw_dynamic_dependencies)
        main_layout.addWidget(self.combo_version)

        lbl_addons = QLabel(self.tr("Vault Components (vault_manifest.json):"))
        lbl_addons.setStyleSheet("font-weight: bold; margin-top: 15px;")
        main_layout.addWidget(lbl_addons)

        self.scroll_addons = QScrollArea()
        self.scroll_addons.setWidgetResizable(True)
        self.scroll_addons.setStyleSheet("QScrollArea { border: 1px solid #334155; border-radius: 8px; background-color: #1E293B; }")

        self.addons_widget = QWidget()
        self.addons_widget.setStyleSheet("background: transparent;")
        self.addons_layout = QVBoxLayout(self.addons_widget)
        self.addons_layout.setAlignment(Qt.AlignTop)
        self.scroll_addons.setWidget(self.addons_widget)
        main_layout.addWidget(self.scroll_addons, stretch=1)

        if versions:
            self._draw_dynamic_dependencies(self.combo_version.currentText())

        lbl_splash = QLabel(self.tr("Custom Splash Screen (1000x500px):"))
        lbl_splash.setStyleSheet("font-weight: bold; margin-top: 10px;")
        main_layout.addWidget(lbl_splash)

        splash_layout = QHBoxLayout()
        splash_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_splash = QPushButton(self.tr("Browse PNG"))
        self.btn_splash.setObjectName("SecondaryButton")
        self.btn_splash.setFixedSize(120, 35)
        self.btn_splash.setCursor(Qt.PointingHandCursor)
        self.btn_splash.clicked.connect(self._select_splash)
        splash_layout.addWidget(self.btn_splash)

        self.lbl_splash_name = QLabel(self.tr("No image"))
        self.lbl_splash_name.setStyleSheet("color: #64748B; padding-left: 10px;")
        splash_layout.addWidget(self.lbl_splash_name, stretch=1)
        main_layout.addLayout(splash_layout)

        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.hide()
        main_layout.addWidget(self.lbl_status)

        self.btn_create = QPushButton(self.tr("Generate Project"))
        self.btn_create.setObjectName("PrimaryButton")
        self.btn_create.setFixedHeight(50)
        self.btn_create.setCursor(Qt.PointingHandCursor)
        self.btn_create.clicked.connect(self._execute_creation)
        main_layout.addWidget(self.btn_create)

        if not self.vault_data:
            self.lbl_status.setText(self.tr("⚠️ OPERATION BLOCKED: Vault not initialized."))
            self.lbl_status.setStyleSheet("color: #EF4444; font-weight: bold; padding: 12px; background-color: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 6px;")
            self.lbl_status.show()
            self.entry_name.setEnabled(False)
            self.combo_version.setEnabled(False)
            self.btn_splash.setEnabled(False)
            self.btn_create.setEnabled(False)

    def _on_templates_loaded(self, templates: list) -> None:
        self.combo_kitsu_template.clear()
        if not templates:
            self.combo_kitsu_template.addItem("No templates found on Kitsu")
        else:
            for template in templates:
                self.combo_kitsu_template.addItem(template["name"])
        self.combo_kitsu_template.setEnabled(True)

    def _select_splash(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Select Splash Screen"), "", self.tr("PNG Images (*.png)"))
        if path:
            self.splash_path = path
            self.lbl_splash_name.setText(Path(path).name)
            self.lbl_splash_name.setStyleSheet("color: #F8FAFC; padding-left: 10px;")

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

                cb.toggled.connect(lambda checked, c=category, n=item_name, r=data.get("requires", []): self._resolve_sub_dependencies(checked, c, n, r))
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

    def _execute_creation(self) -> None:
        name = self.entry_name.text().strip()
        version_blender = self.combo_version.currentText().strip()
        kitsu_template = self.combo_kitsu_template.currentText().strip()

        if not name or not name.replace("-", "").replace("_", "").isalnum():
            self.lbl_status.setText(self.tr("Invalid name."))
            self.lbl_status.show()
            return

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

        vcs_config = self.vm.config_factory.get_raw_config().get("vcs_engine", {})
        vcs_user = vcs_config.get("vcs_username", DEV_SVN_USER)
        vcs_pwd = vcs_config.get("vcs_password", DEV_SVN_PASSWORD)

        vcs_selection = self.combo_vcs.currentIndex()
        vcs_enabled = True

        if vcs_selection == 3:
            vcs_enabled = False
        elif vcs_selection == 0:
            if vcs_config.get("active_adapter", "svn") == "none":
                vcs_enabled = False

        self.btn_create.setEnabled(False)
        self.btn_create.setText(self.tr("Creating..."))
        self.lbl_status.setText(self.tr("Forging structure and connecting repositories..."))
        self.lbl_status.setStyleSheet("color: #F59E0B; font-weight: bold;")
        self.lbl_status.show()

        self.vm.create_project(name, version_blender, final_dependencies, main_template, self.splash_path, vcs_user, vcs_pwd, vcs_enabled=vcs_enabled)

    def _on_creation_finished(self, success: bool, message: str) -> None:
        if success:
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #10B981; font-weight: bold;")
            self.on_success()
            self.close()
        else:
            self.btn_create.setEnabled(True)
            self.btn_create.setText(self.tr("Generate Project"))
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #EF4444; font-weight: bold;")
