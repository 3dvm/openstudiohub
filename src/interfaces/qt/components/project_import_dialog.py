# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/project_import_dialog.py
# Architectural role: UI Component / Kitsu project import (PySide6)
# =========================================================================================

"""Modal for importing a ``.oshproject`` archive into the current Kitsu server.

Steps: choose the archive -> inspect -> map every referenced person (match by
email or create on target with no password) -> import with live progress and a
final report. Import stays blocked until the project name is free and every
person is mapped.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ProjectImportDialog(QDialog):
    inspect_requested = Signal(str)
    create_person_requested = Signal(dict)
    start_requested = Signal(dict, dict)  # person_map, options
    cancel_requested = Signal()
    checkout_requested = Signal()
    rollback_requested = Signal()
    repo_probe_requested = Signal(str)

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Import Kitsu Project"))
        self.resize(820, 720)
        self.setMinimumSize(580, 480)
        self.setModal(True)
        self.setObjectName("FloatingCard")
        self._plan = None
        self._target_persons: list = []
        self._default_topography: dict = {}
        self._repo_state = ""
        self._running = False
        self._finished = False
        self._conflict = ""
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 12)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(26, 22, 26, 10)
        layout.setSpacing(10)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        title = QLabel(self.tr("Import Project (.oshproject)"))
        title.setObjectName("H2Title")
        layout.addWidget(title)

        notice = QLabel(
            self.tr(
                "Import runs while logged into the TARGET Kitsu server with a super-admin "
                "account. People are matched by email only."
            )
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(notice)

        file_layout = QHBoxLayout()
        self.entry_archive = QLineEdit()
        self.entry_archive.setObjectName("FormInput")
        self.entry_archive.setFixedHeight(35)
        self.entry_archive.setPlaceholderText(self.tr("Path to a .oshproject archive"))
        file_layout.addWidget(self.entry_archive, stretch=1)

        self.btn_browse = QPushButton(self.tr("Browse..."))
        self.btn_browse.setObjectName("SecondaryButton")
        self.btn_browse.setFixedHeight(35)
        self.btn_browse.clicked.connect(self._browse)
        file_layout.addWidget(self.btn_browse)

        self.btn_inspect = QPushButton(self.tr("Inspect"))
        self.btn_inspect.setObjectName("SecondaryButton")
        self.btn_inspect.setFixedHeight(35)
        self.btn_inspect.clicked.connect(self._inspect)
        file_layout.addWidget(self.btn_inspect)
        layout.addLayout(file_layout)

        self.lbl_summary = QLabel(self.tr("Choose an archive and press Inspect."))
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(self.lbl_summary)

        self.lbl_conflict = QLabel("")
        self.lbl_conflict.setWordWrap(True)
        self.lbl_conflict.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 12px;")
        self.lbl_conflict.hide()
        layout.addWidget(self.lbl_conflict)

        vcs_layout = QHBoxLayout()
        vcs_layout.addWidget(QLabel(self.tr("Target VCS server:")))
        self.combo_vcs = QComboBox()
        self.combo_vcs.setObjectName("FormInput")
        self.combo_vcs.setFixedHeight(32)
        self.combo_vcs.currentIndexChanged.connect(self._on_vcs_changed)
        vcs_layout.addWidget(self.combo_vcs, stretch=1)
        self.chk_dry_run = QCheckBox(self.tr("Dry run (validate only)"))
        vcs_layout.addWidget(self.chk_dry_run)
        layout.addLayout(vcs_layout)

        self.lbl_repo = QLabel(self.tr("Repository: not checked yet."))
        self.lbl_repo.setWordWrap(True)
        self.lbl_repo.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(self.lbl_repo)

        self.chk_repo_rename = QCheckBox(self.tr("Rename repository folder"))
        self.chk_repo_rename.toggled.connect(lambda _checked: self._refresh_import_enabled())
        self.chk_repo_rename.hide()
        layout.addWidget(self.chk_repo_rename)

        lbl_topo = QLabel(self.tr("Topography mapping (source → target):"))
        lbl_topo.setStyleSheet("font-weight: bold; margin-top: 6px;")
        layout.addWidget(lbl_topo)

        self.table_topo = QTableWidget(0, 3)
        self.table_topo.setHorizontalHeaderLabels(
            [self.tr("Folder"), self.tr("Source"), self.tr("Target")]
        )
        self.table_topo.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_topo.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_topo.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_topo.verticalHeader().setVisible(False)
        self.table_topo.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_topo.setSelectionMode(QTableWidget.NoSelection)
        self.table_topo.setFixedHeight(150)
        layout.addWidget(self.table_topo)

        lbl_people = QLabel(self.tr("Person mapping (email match required):"))
        lbl_people.setStyleSheet("font-weight: bold; margin-top: 6px;")
        layout.addWidget(lbl_people)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Source person"), self.tr("Email"), self.tr("Target person"), ""]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(180)
        layout.addWidget(self.table)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("FormInput")
        self.log_output.setStyleSheet(
            "font-family: monospace; font-size: 11px; color: #94A3B8; background-color: #0F172A;"
        )
        self.log_output.hide()
        layout.addWidget(self.log_output, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.btn_rollback = QPushButton(self.tr("Rollback import"))
        self.btn_rollback.setObjectName("SecondaryButton")
        self.btn_rollback.setFixedHeight(35)
        self.btn_rollback.clicked.connect(self.rollback_requested.emit)
        self.btn_rollback.hide()
        buttons.addWidget(self.btn_rollback)

        self.btn_checkout = QPushButton(self.tr("Check out from VCS"))
        self.btn_checkout.setObjectName("SecondaryButton")
        self.btn_checkout.setFixedHeight(35)
        self.btn_checkout.clicked.connect(self.checkout_requested.emit)
        self.btn_checkout.hide()
        buttons.addWidget(self.btn_checkout)

        self.btn_cancel = QPushButton(self.tr("Close"))
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.setFixedHeight(35)
        self.btn_cancel.clicked.connect(self._on_cancel)
        buttons.addWidget(self.btn_cancel)

        self.btn_import = QPushButton(self.tr("Import"))
        self.btn_import.setObjectName("PrimaryButton")
        self.btn_import.setFixedHeight(35)
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self._on_import)
        buttons.addWidget(self.btn_import)

        buttons.setContentsMargins(26, 4, 26, 0)
        root.addLayout(buttons)

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def _browse(self) -> None:
        start = self.entry_archive.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select .oshproject"), start, self.tr("OpenStudio Project (*.oshproject)")
        )
        if path:
            self.entry_archive.setText(path)

    def _inspect(self) -> None:
        path = self.entry_archive.text().strip()
        if not path:
            return
        self.lbl_summary.setText(self.tr("Reading archive..."))
        self.inspect_requested.emit(path)

    def set_vcs_servers(self, servers: list, default_id: str = "") -> None:
        self.combo_vcs.clear()
        for server in servers:
            if not server.get("is_enabled", server.get("adapter") != "none"):
                continue
            label = server.get("name", server.get("id", "Server"))
            if server.get("repository_url"):
                label += f"  ({server['repository_url']})"
            self.combo_vcs.addItem(label, server.get("id", ""))
        index = self.combo_vcs.findData(default_id)
        if index >= 0:
            self.combo_vcs.setCurrentIndex(index)

    def selected_vcs_server_id(self) -> str:
        return self.combo_vcs.currentData() or ""

    # ------------------------------------------------------------------
    # Plan / mapping
    # ------------------------------------------------------------------
    def set_target_persons(self, persons: list) -> None:
        self._target_persons = list(persons or [])
        self._rebuild_table()

    def set_default_topography(self, topography: dict) -> None:
        self._default_topography = dict(topography or {})
        if self._plan is not None:
            self._rebuild_topography()

    def on_plan_ready(self, plan, persons: list) -> None:
        """Slot for the ViewModel: install the target people, then the plan."""
        self.set_target_persons(persons)
        self.set_plan(plan)
        self._request_repo_probe()

    def _request_repo_probe(self) -> None:
        if self._plan is None:
            return
        self.lbl_repo.setText(self.tr("Repository: checking..."))
        self.lbl_repo.setStyleSheet("color: #94A3B8; font-size: 12px;")
        self.lbl_repo.setToolTip("")
        if not self._running:
            self.log_output.clear()
            self.log_output.hide()
        self.repo_probe_requested.emit(self.selected_vcs_server_id())

    def _present_repo_diagnostics(self, status: dict) -> None:
        """Show the actual values used by the probe (transport, path, command)."""
        diagnostics = status.get("diagnostics") or {}
        detail = str(diagnostics.get("log") or "")
        reason = str(diagnostics.get("reason") or "")
        self.lbl_repo.setToolTip(detail or reason)
        if detail and not self._running:
            self.append_log(detail)
            self.log_output.show()

    def _repo_detail_hint(self, diagnostics: dict) -> str:
        parts = []
        if diagnostics.get("effective_mode"):
            parts.append(f"mode={diagnostics['effective_mode']}")
        if diagnostics.get("repository_url"):
            parts.append(f"url={diagnostics['repository_url']}")
        if diagnostics.get("mismatch"):
            parts.append(diagnostics["mismatch"])
        if diagnostics.get("repo_path"):
            parts.append(f"path={diagnostics['repo_path']}")
        return ", ".join(parts)

    def _on_vcs_changed(self, _index: int) -> None:
        self._request_repo_probe()

    def set_repo_status(self, status: dict) -> None:
        status = status or {}
        self._repo_state = str(status.get("state", "") or "")
        repo_name = status.get("repo_name", "")
        target = status.get("target", "")
        source = status.get("source", "")
        server_name = status.get("server_name", "")
        diagnostics = status.get("diagnostics") or {}
        hint = self._repo_detail_hint(diagnostics)

        if self._repo_state == "ok":
            self.lbl_repo.setText(self.tr(f"Repository '{repo_name}' is ready ('{target}')."))
            self.lbl_repo.setStyleSheet("color: #10B981; font-size: 12px;")
            self.chk_repo_rename.hide()
        elif self._repo_state == "rename_needed":
            self.lbl_repo.setText(
                self.tr(f"Repository '{repo_name}' contains '{source}'; rename it to '{target}'?")
            )
            self.lbl_repo.setStyleSheet("color: #F59E0B; font-weight: bold; font-size: 12px;")
            self.chk_repo_rename.setText(self.tr(f"Rename repository folder '{source}' → '{target}'"))
            self.chk_repo_rename.setChecked(True)
            self.chk_repo_rename.show()
        elif self._repo_state == "missing":
            message = self.tr(
                f"Repository '{repo_name}' was not found on '{server_name}'. Create/push it first."
            )
            if hint:
                message += self.tr(f"  [{hint}]")
            self.lbl_repo.setText(message)
            self.lbl_repo.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 12px;")
            self.chk_repo_rename.hide()
        else:
            reason = str(diagnostics.get("reason") or "")
            message = reason or self.tr("Repository could not be verified; import may fail at checkout.")
            if hint:
                message += self.tr(f"  [{hint}]")
            self.lbl_repo.setText(message)
            self.lbl_repo.setStyleSheet("color: #F59E0B; font-size: 12px;")
            self.chk_repo_rename.hide()
        self._present_repo_diagnostics(status)
        self._refresh_import_enabled()

    def _rebuild_topography(self) -> None:
        self.table_topo.setRowCount(0)
        if self._plan is None:
            return
        source = dict(getattr(self._plan, "source_topography", {}) or {})
        target = self._default_topography or {}
        rows = [
            ("svn", "vfs_svn"),
            ("shared", "vfs_shared"),
            ("local", "vfs_local"),
            ("pipeline", "vfs_pipeline"),
        ]
        for label, key in rows:
            self._add_topo_row(label, source.get(key, "—"), target.get(key, "—"))
        for custom in source.get("custom_dirs") or []:
            target_name = custom if custom in (target.get("custom_dirs") or []) else custom
            self._add_topo_row(f"custom: {custom}", custom, target_name)

    def _add_topo_row(self, label: str, source: str, target: str) -> None:
        row = self.table_topo.rowCount()
        self.table_topo.insertRow(row)
        self.table_topo.setItem(row, 0, QTableWidgetItem(str(label)))
        self.table_topo.setItem(row, 1, QTableWidgetItem(str(source)))
        self.table_topo.setItem(row, 2, QTableWidgetItem(str(target)))

    def topography_mapping(self) -> dict:
        return dict(self._default_topography or {})

    def set_plan(self, plan) -> None:
        self._plan = plan
        counts = plan.counts or {}
        summary = (
            f"Project: {plan.project_name}\n"
            f"Source: {plan.source_kitsu_url or 'unknown'}    "
            f"Counts: {counts.get('tasks', 0)} tasks, {counts.get('assets', 0)} assets, "
            f"{counts.get('shots', 0)} shots, {counts.get('comments', 0)} comments, "
            f"{counts.get('previews', 0)} previews."
        )
        self.lbl_summary.setText(summary)
        self._rebuild_topography()
        self._rebuild_table()
        self._refresh_import_enabled()

    def set_conflict(self, message: str) -> None:
        self._conflict = message or ""
        if self._conflict:
            self.lbl_conflict.setText(self._conflict)
            self.lbl_conflict.show()
        else:
            self.lbl_conflict.hide()
        self._refresh_import_enabled()

    def _rebuild_table(self) -> None:
        self.table.setRowCount(0)
        if self._plan is None:
            return
        by_email = {
            str(person.get("email", "") or "").strip().lower(): person
            for person in self._target_persons
            if isinstance(person, dict) and person.get("email")
        }
        for source in self._plan.persons_json:
            self._add_person_row(source, by_email.get(str(source.get("email", "") or "").strip().lower()))

    def _add_person_row(self, source: dict, target=None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = source.get("full_name") or f"{source.get('first_name', '')} {source.get('last_name', '')}".strip()
        name_item = QTableWidgetItem(name or source.get("email", ""))
        name_item.setData(Qt.UserRole, source)
        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, QTableWidgetItem(str(source.get("email", "") or "")))

        combo = QComboBox()
        combo.addItem(self.tr("— Not mapped —"), None)
        for person in self._target_persons:
            label = person.get("full_name") or person.get("email", "")
            combo.addItem(label, person)
        if target is not None:
            index = self._combo_index_for(combo, target)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(self._refresh_import_enabled)
        self.table.setCellWidget(row, 2, combo)

        btn = QPushButton(self.tr("Create on target"))
        btn.setObjectName("SecondaryButton")
        btn.clicked.connect(lambda _=False, s=source: self._request_create(s))
        self.table.setCellWidget(row, 3, btn)

    @staticmethod
    def _combo_index_for(combo: QComboBox, person: dict) -> int:
        person_id = str(person.get("id", "") or "")
        email = str(person.get("email", "") or "").strip().lower()
        for index in range(combo.count()):
            data = combo.itemData(index)
            if not isinstance(data, dict):
                continue
            if person_id and str(data.get("id", "")) == person_id:
                return index
            if email and str(data.get("email", "") or "").strip().lower() == email:
                return index
        return -1

    def _request_create(self, source: dict) -> None:
        self.lbl_status.setText(self.tr(f"Creating '{source.get('email', '')}' on the target..."))
        self.create_person_requested.emit(source)

    def on_person_created(self, source: dict, target: dict) -> None:
        source_id = str(source.get("id", "") or "")
        if target and target not in self._target_persons:
            self._target_persons.append(target)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            row_source = item.data(Qt.UserRole) or {}
            if str(row_source.get("id", "") or "") != source_id:
                continue
            combo = self.table.cellWidget(row, 2)
            if isinstance(combo, QComboBox):
                if target and self._combo_index_for(combo, target) < 0:
                    combo.addItem(target.get("full_name") or target.get("email", ""), target)
                index = self._combo_index_for(combo, target)
                if index >= 0:
                    combo.setCurrentIndex(index)
        self.lbl_status.setText(self.tr("Person created. The studio admin finishes password setup in Kitsu."))
        self._refresh_import_enabled()

    def person_map(self) -> dict:
        mapping: dict = {}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            combo = self.table.cellWidget(row, 2)
            if item is None or not isinstance(combo, QComboBox):
                continue
            source = item.data(Qt.UserRole) or {}
            target = combo.currentData()
            source_id = str(source.get("id", "") or "")
            if source_id and isinstance(target, dict) and target.get("id"):
                mapping[source_id] = target
        return mapping

    def _all_mapped(self) -> bool:
        if self._plan is None:
            return False
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 2)
            if not isinstance(combo, QComboBox) or not isinstance(combo.currentData(), dict):
                return False
        return True

    def _repo_ready(self) -> bool:
        # An unprobed repo ("") is allowed so the flow still works if the probe
        # could not run; "missing"/"unknown" are blocked.
        if self._repo_state in ("", "ok"):
            return True
        if self._repo_state == "rename_needed":
            return self.chk_repo_rename.isChecked()
        return False

    def _refresh_import_enabled(self) -> None:
        self.btn_import.setEnabled(
            self._plan is not None
            and not self._conflict
            and self._all_mapped()
            and not self._running
            and self._repo_ready()
        )

    def options(self) -> dict:
        return {
            "target_vcs_server_id": self.selected_vcs_server_id(),
            "dry_run": self.chk_dry_run.isChecked(),
            "topography": self.topography_mapping(),
            "rename_repository": bool(self.chk_repo_rename.isChecked() and self._repo_state == "rename_needed"),
        }

    def _on_import(self) -> None:
        if self._plan is None:
            return
        self._running = True
        self.btn_import.setEnabled(False)
        self.btn_inspect.setEnabled(False)
        self.btn_import.setText(self.tr("Importing..."))
        self.btn_cancel.setText(self.tr("Cancel Import"))
        self.progress.show()
        self.log_output.show()
        self.start_requested.emit(self.person_map(), self.options())

    def _on_cancel(self) -> None:
        if self._running and not self._finished:
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText(self.tr("Cancelling..."))
            self.cancel_requested.emit()
            return
        self.reject()

    # ------------------------------------------------------------------
    # Live updates
    # ------------------------------------------------------------------
    def set_phase(self, message: str) -> None:
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet("color: #F59E0B; font-size: 12px;")

    def set_progress(self, percent: int) -> None:
        self.progress.setValue(max(0, min(100, int(percent))))

    def append_log(self, line: str) -> None:
        self.log_output.appendPlainText(line)
        self.log_output.moveCursor(QTextCursor.End)

    def finalize(self, report) -> None:
        self._running = False
        self._finished = True
        self.btn_cancel.setText(self.tr("Close"))
        self.btn_cancel.setEnabled(True)
        self.btn_import.setEnabled(False)
        if getattr(report, "success", False):
            self.progress.setValue(100)
            self.lbl_status.setText(report.message)
            self.lbl_status.setStyleSheet("color: #10B981; font-weight: bold; font-size: 12px;")
            if getattr(report, "needs_checkout", False):
                self.btn_checkout.show()
        else:
            self.lbl_status.setText(report.message)
            self.lbl_status.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 12px;")
            if getattr(report, "rollback_available", False) and getattr(report, "project_id", ""):
                self.btn_rollback.show()
        self.append_log(report.message)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._running and not self._finished:
            self._on_cancel()
            event.ignore()
            return
        super().closeEvent(event)
