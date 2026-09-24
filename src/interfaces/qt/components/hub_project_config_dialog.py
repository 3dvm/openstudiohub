# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/hub_project_config_dialog.py
# Architectural role: UI Component / HubProject configuration dialog (PySide6)
# =========================================================================================

"""Modal dialog to inspect and edit a ``HubProject``'s local configuration.

Shows the project's VCS binding, splash screen, Blender version, template and
add-on configuration. Persistence, VCS topography probing and the Kitsu splash
upload are delegated to callbacks supplied by the parent ViewModel, keeping this
widget a passive view.
"""

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.shared_kernel.addon_contract import resolve_addon_entry
from src.interfaces.qt.widgets.addon_config_panel import AddonConfigPanel


class HubProjectConfigDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        config: dict,
        on_probe: Callable[[str, str], tuple],
        on_save: Callable[[dict], tuple],
        vault_service=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Project Configuration"))
        self.setFixedSize(680, 860)
        self.setSizeGripEnabled(True)
        self.setModal(True)
        self.setObjectName("ViewLoginBase")

        self.config = config or {}
        self.project_name = str(self.config.get("project_name", ""))
        self.project_id = str(self.config.get("project_id", ""))
        self.project_dir = self.config.get("project_dir")
        self.is_mounted = bool(self.config.get("is_mounted"))
        self.blueprint = self.config.get("blueprint") or {}
        self.bound_server_id = str(self.config.get("bound_server_id", ""))
        self.servers = self.config.get("servers") or []
        self.on_probe = on_probe
        self.on_save = on_save

        self.vault_service = vault_service
        self.vault_data = {}
        if vault_service is not None:
            try:
                self.vault_data = vault_service.load_inventory() or {}
            except Exception:  # noqa: BLE001
                self.vault_data = {}

        self.splash_source_path = ""
        self.tool_checkboxes: dict = {}
        self.addon_config_panels: dict = {}
        self.template_group: Optional[QButtonGroup] = None
        self._vcs_probe_ok = False
        self._vcs_probe_server_id = ""

        self._build_ui()
        self._prefill()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 25, 30, 25)
        main_layout.setSpacing(12)

        lbl_title = QLabel(self.tr("Project Configuration"))
        lbl_title.setObjectName("CardTitle")
        lbl_title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(lbl_title)

        self.lbl_subtitle = QLabel(self.project_name)
        self.lbl_subtitle.setAlignment(Qt.AlignCenter)
        self.lbl_subtitle.setStyleSheet("color: #94A3B8; font-size: 12px;")
        main_layout.addWidget(self.lbl_subtitle)

        main_layout.addWidget(self._build_info_form())

        if not self.is_mounted:
            notice = QLabel(
                self.tr(
                    "This project is not mounted on the NAS. VCS binding, splash and "
                    "component changes require a local copy."
                )
            )
            notice.setWordWrap(True)
            notice.setStyleSheet(
                "color: #F59E0B; font-size: 12px; padding: 8px; "
                "background-color: rgba(245, 158, 11, 0.08); "
                "border: 1px solid rgba(245, 158, 11, 0.25); border-radius: 6px;"
            )
            main_layout.addWidget(notice)

        main_layout.addWidget(self._build_vcs_section())
        main_layout.addWidget(self._build_components_section(), stretch=1)
        main_layout.addWidget(self._build_splash_section())

        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.hide()
        main_layout.addWidget(self.lbl_status)

        buttons = QHBoxLayout()
        buttons.addStretch()

        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setObjectName("SecondaryButton")
        btn_cancel.setFixedHeight(38)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_cancel)

        self.btn_save = QPushButton(self.tr("Save Configuration"))
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.setFixedHeight(38)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._execute_save)
        buttons.addWidget(self.btn_save)

        main_layout.addLayout(buttons)

    def _build_info_form(self) -> QWidget:
        form = QFormLayout()
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        topography = (self.blueprint.get("topography_signature") or {}) if isinstance(self.blueprint, dict) else {}

        rows = [
            (self.tr("Project:"), self.project_name or "—"),
            (self.tr("Kitsu ID:"), self.project_id or "—"),
            (self.tr("Location:"), str(self.project_dir) if self.project_dir else self.tr("Not mounted")),
            (
                self.tr("Topography:"),
                ", ".join(
                    f"{key}={topography.get(key, '?')}"
                    for key in ("vfs_svn", "vfs_shared", "vfs_local", "vfs_pipeline")
                )
                or "—",
            ),
        ]

        for label_text, value in rows:
            label = QLabel(label_text)
            label.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 11px;")
            widget = QLabel(value)
            widget.setWordWrap(True)
            widget.setStyleSheet("color: #F8FAFC; font-size: 12px;")
            form.addRow(label, widget)

        container = QWidget()
        container.setLayout(form)
        return container

    def _build_vcs_section(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 5, 0, 0)
        layout.setSpacing(6)

        label = QLabel(self.tr("Version Control System (VCS):"))
        label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        layout.addWidget(label)

        row = QHBoxLayout()
        self.combo_vcs = QComboBox()
        self.combo_vcs.setFixedHeight(36)
        self.combo_vcs.setStyleSheet(
            "QComboBox { background-color: #0F172A; border: 1px solid #475569; "
            "border-radius: 8px; color: #F8FAFC; padding: 5px; }"
        )
        self._populate_vcs_servers()
        row.addWidget(self.combo_vcs, stretch=1)

        self.btn_check_vcs = QPushButton(self.tr("Check Topography"))
        self.btn_check_vcs.setObjectName("SecondaryButton")
        self.btn_check_vcs.setFixedSize(150, 36)
        self.btn_check_vcs.setCursor(Qt.PointingHandCursor)
        self.btn_check_vcs.clicked.connect(self._on_check_vcs)
        row.addWidget(self.btn_check_vcs)
        layout.addLayout(row)

        self.lbl_vcs_status = QLabel("")
        self.lbl_vcs_status.setWordWrap(True)
        self.lbl_vcs_status.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(self.lbl_vcs_status)

        return container

    def _build_components_section(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 5, 0, 0)
        layout.setSpacing(6)

        label = QLabel(self.tr("Blender Version & Vault Components:"))
        label.setStyleSheet("font-weight: bold;")
        layout.addWidget(label)

        self.combo_version = QComboBox()
        self.combo_version.setFixedHeight(36)
        self.combo_version.setStyleSheet(
            "QComboBox { background-color: #0F172A; border: 1px solid #475569; "
            "border-radius: 8px; color: #F8FAFC; padding: 5px; }"
        )
        versions = list(self.vault_data.keys()) if self.vault_data else []
        current_version = str(self.blueprint.get("blender_version", "") or "")
        if current_version and current_version not in versions:
            versions.insert(0, current_version)
        self.combo_version.addItems(versions)
        self.combo_version.currentTextChanged.connect(self._draw_dynamic_dependencies)
        layout.addWidget(self.combo_version)

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
        layout.addWidget(self.scroll_addons, stretch=1)

        return container

    def _build_splash_section(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 5, 0, 0)
        layout.setSpacing(6)

        label = QLabel(self.tr("Splash Screen (1000x500px):"))
        label.setStyleSheet("font-weight: bold;")
        layout.addWidget(label)

        row = QHBoxLayout()
        self.lbl_splash_preview = QLabel()
        self.lbl_splash_preview.setFixedSize(220, 110)
        self.lbl_splash_preview.setAlignment(Qt.AlignCenter)
        self.lbl_splash_preview.setStyleSheet(
            "background-color: #0F172A; border: 1px dashed #334155; "
            "border-radius: 8px; color: #64748B; font-size: 11px;"
        )
        self._set_splash_preview(self.config.get("splash_path") or "")
        row.addWidget(self.lbl_splash_preview)

        controls = QVBoxLayout()
        controls.setContentsMargins(10, 0, 0, 0)
        self.btn_splash = QPushButton(self.tr("Browse PNG"))
        self.btn_splash.setObjectName("SecondaryButton")
        self.btn_splash.setFixedSize(140, 36)
        self.btn_splash.setCursor(Qt.PointingHandCursor)
        self.btn_splash.clicked.connect(self._select_splash)
        self.btn_splash.setEnabled(self.is_mounted)
        controls.addWidget(self.btn_splash)

        self.lbl_splash_name = QLabel(
            Path(self.config.get("splash_path")).name if self.config.get("splash_path") else self.tr("Keeping current")
        )
        self.lbl_splash_name.setStyleSheet("color: #64748B; font-size: 11px;")
        self.lbl_splash_name.setWordWrap(True)
        controls.addWidget(self.lbl_splash_name)
        controls.addStretch()
        row.addLayout(controls)
        row.addStretch()

        layout.addLayout(row)
        return container

    # ------------------------------------------------------------------
    # Population / prefill
    # ------------------------------------------------------------------
    def _populate_vcs_servers(self) -> None:
        for server in self.servers:
            if server.get("adapter", "").lower() == "none":
                continue
            label = server.get("name", server.get("id", "Server"))
            label += f"  ({server.get('repository_url', '')})"
            if server.get("id") == self.bound_server_id:
                label += self.tr("  — current")
            elif server.get("is_default"):
                label += self.tr("  (default)")
            self.combo_vcs.addItem(label, server.get("id", ""))
        self.combo_vcs.addItem(self.tr("None (NAS only)"), "")

        index = self.combo_vcs.findData(self.bound_server_id)
        if index >= 0:
            self.combo_vcs.setCurrentIndex(index)
        else:
            default_index = self.combo_vcs.findData("")
            if default_index >= 0:
                self.combo_vcs.setCurrentIndex(default_index)

    def _prefill(self) -> None:
        self._draw_dynamic_dependencies(self.combo_version.currentText())

    def _clear_addons_layout(self) -> None:
        while self.addons_layout.count():
            child = self.addons_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _draw_dynamic_dependencies(self, selected_version: str) -> None:
        self._clear_addons_layout()
        self.tool_checkboxes.clear()
        self.addon_config_panels.clear()
        self.template_group = QButtonGroup(self)
        if not selected_version:
            return

        available_categories = self.vault_data.get(selected_version, {})
        if not available_categories:
            hint = QLabel(
                self.tr("No vault components found for Blender {0}.").format(selected_version)
            )
            hint.setStyleSheet("color: #64748B; font-size: 11px;")
            self.addons_layout.addWidget(hint)
            return

        saved_dependencies = self.blueprint.get("dependencies") or {}
        saved_addons = self.blueprint.get("addon_configuration") or {}
        saved_template = str(self.blueprint.get("template", "") or "")

        for category, items in available_categories.items():
            lbl_cat = QLabel(f"[{category.upper()}]")
            lbl_cat.setStyleSheet("color: #10B981; font-weight: bold; margin-top: 10px;")
            self.addons_layout.addWidget(lbl_cat)
            self.tool_checkboxes[category] = {}

            selected_in_category = saved_dependencies.get(category) or {}

            for item_name, data in items.items():
                entry = resolve_addon_entry(item_name, data)
                item_version = entry.get("version", "1.0")
                is_mandatory = entry.get("mandatory", False)
                label_text = f"{item_name} v{item_version} - {entry.get('description', '')}"

                if category == "templates":
                    cb = QRadioButton(label_text)
                    cb.setStyleSheet("QRadioButton { color: #F8FAFC; padding: 5px; }")
                    self.template_group.addButton(cb)
                    should_check = item_name == saved_template
                else:
                    cb = QCheckBox(label_text)
                    cb.setStyleSheet("QCheckBox { color: #F8FAFC; padding: 5px; }")
                    should_check = item_name in selected_in_category

                requires = entry.get("requires", [])
                cb.toggled.connect(
                    lambda checked, c=category, n=item_name, r=requires: self._resolve_sub_dependencies(checked, c, n, r)
                )
                self.addons_layout.addWidget(cb)

                config_schema = entry.get("config_schema")
                if config_schema:
                    default_config = entry.get("default_config") or {}
                    existing = (saved_addons.get(item_name) or {}).get("settings") or {}
                    panel = AddonConfigPanel(config_schema, default_config.get("settings") or {})
                    panel.set_values(existing)
                    cb.toggled.connect(panel.set_editable)
                    panel.set_editable(cb.isChecked())
                    self.addons_layout.addWidget(panel)
                    self.addon_config_panels[item_name] = panel

                if should_check:
                    cb.setChecked(True)
                if is_mandatory:
                    cb.setChecked(True)
                    cb.setEnabled(False)

                self.tool_checkboxes[category][item_name] = {
                    "checkbox": cb,
                    "version": item_version,
                    "meta": entry,
                }

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

    def _set_splash_preview(self, path: str) -> None:
        if path and Path(path).is_file():
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.lbl_splash_preview.setPixmap(
                    pixmap.scaled(220, 110, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                )
                return
        self.lbl_splash_preview.setText(self.tr("No splash"))

    def _select_splash(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select Splash Screen"), "", self.tr("PNG Images (*.png)")
        )
        if path:
            self.splash_source_path = path
            self._set_splash_preview(path)
            self.lbl_splash_name.setText(Path(path).name)
            self.lbl_splash_name.setStyleSheet("color: #F8FAFC; font-size: 11px;")

    # ------------------------------------------------------------------
    # VCS probe / save
    # ------------------------------------------------------------------
    def _on_check_vcs(self) -> None:
        server_id = self.combo_vcs.currentData() or ""
        if not server_id:
            self._vcs_probe_ok = True
            self._vcs_probe_server_id = ""
            self._set_vcs_status(self.tr("Version Control is disabled (NAS only)."), ok=True)
            return
        if not self.project_name:
            self._set_vcs_status(self.tr("Missing project name."), ok=False)
            return

        self._set_vcs_status(self.tr("Checking target repository topography..."), ok=None)
        QApplication.processEvents()
        try:
            ok, message = self.on_probe(server_id, self.project_name)
        except Exception as error:  # noqa: BLE001
            ok, message = False, str(error)
        self._vcs_probe_ok = bool(ok)
        self._vcs_probe_server_id = server_id if ok else ""
        self._set_vcs_status(message, ok=bool(ok))

    def _set_vcs_status(self, message: str, ok: Optional[bool]) -> None:
        if ok is True:
            color = "#10B981"
        elif ok is False:
            color = "#EF4444"
        else:
            color = "#F59E0B"
        self.lbl_vcs_status.setText(message)
        self.lbl_vcs_status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _collect_payload(self) -> dict:
        # No vault data for the selected version: preserve what the project
        # already declares instead of wiping its dependencies.
        if not self.tool_checkboxes:
            return {
                "server_id": self.combo_vcs.currentData() or "",
                "blender_version": self.combo_version.currentText().strip(),
                "template": str(self.blueprint.get("template", "") or ""),
                "dependencies": self.blueprint.get("dependencies") or {},
                "addon_configuration": self.blueprint.get("addon_configuration") or {},
                "splash_source_path": self.splash_source_path,
            }

        dependencies: dict = {}
        addon_configuration: dict = {}
        template = ""

        for category, items in self.tool_checkboxes.items():
            dependencies[category] = {}
            for item_name, data in items.items():
                if not data["checkbox"].isChecked():
                    continue
                dependencies[category][item_name] = data["version"]
                if category == "templates":
                    template = item_name
                    continue
                addon_configuration[item_name] = self._build_addon_config(item_name, data.get("meta", {}))

        if not template:
            template = str(self.blueprint.get("template", "") or "")
            saved_templates = (self.blueprint.get("dependencies") or {}).get("templates")
            if saved_templates and not dependencies.get("templates"):
                dependencies["templates"] = dict(saved_templates)

        return {
            "server_id": self.combo_vcs.currentData() or "",
            "blender_version": self.combo_version.currentText().strip(),
            "template": template,
            "dependencies": dependencies,
            "addon_configuration": addon_configuration,
            "splash_source_path": self.splash_source_path,
        }

    def _build_addon_config(self, addon_name: str, meta: dict) -> dict:
        default_config = meta.get("default_config") or {}
        panel = self.addon_config_panels.get(addon_name)
        if panel is not None and panel.schema:
            settings = panel.values()
        else:
            settings = dict(default_config.get("settings") or {})
        return {
            "enabled": True,
            "module_match": meta.get("module_match", addon_name),
            "settings": settings,
            "behaviors": list(default_config.get("behaviors") or []),
        }

    def _execute_save(self) -> None:
        server_id = self.combo_vcs.currentData() or ""
        binding_changed = server_id != self.bound_server_id

        if binding_changed and server_id:
            if not (self._vcs_probe_ok and self._vcs_probe_server_id == server_id):
                self._on_check_vcs()
            if not (self._vcs_probe_ok and self._vcs_probe_server_id == server_id):
                self._show_status(self.lbl_vcs_status.text() or self.tr("Target topography is not healthy."), ok=False)
                return
            answer = QMessageBox.question(
                self,
                self.tr("Bind VCS Server"),
                self.tr(
                    "The target repository topography is healthy.\n\n"
                    "Bind this project to the selected VCS server? The repository "
                    "history is not moved (use 'Migrate VCS…' for that)."
                ),
            )
            if answer != QMessageBox.Yes:
                return

        payload = self._collect_payload()
        self.btn_save.setEnabled(False)
        self.btn_save.setText(self.tr("Saving..."))
        self._show_status(self.tr("Saving project configuration..."), ok=None)
        try:
            success, message = self.on_save(payload)
        except Exception as error:  # noqa: BLE001
            success, message = False, str(error)

        if success:
            self._show_status(message, ok=True)
            self.accept()
        else:
            self.btn_save.setEnabled(True)
            self.btn_save.setText(self.tr("Save Configuration"))
            self._show_status(message, ok=False)

    def _show_status(self, message: str, ok: Optional[bool]) -> None:
        if ok is True:
            color = "#10B981"
        elif ok is False:
            color = "#EF4444"
        else:
            color = "#F59E0B"
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.lbl_status.show()
