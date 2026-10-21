# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/vcs_audit_widget.py
# Architectural role: UI Widget / TD VCS audit viewer (PySide6)
# =========================================================================================

"""Read-only audit viewer for the TD dashboard."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.interfaces.qt.viewmodels.vcs_audit_viewmodel import VcsAuditViewModel


class VcsAuditWidget(QWidget):
    """Display recent VCS audit events and their details."""

    COLUMNS = (
        "Time",
        "Operation",
        "Project",
        "User",
        "Result",
        "Code",
        "Duration",
        "Paths",
    )

    def __init__(self, parent, viewmodel: VcsAuditViewModel) -> None:
        super().__init__(parent)
        self.vm = viewmodel
        self._events: list[dict] = []

        self.setObjectName("VcsAuditWidgetBase")
        self._build_ui()
        self.vm.events_loaded.connect(self._on_events)
        self.refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(self.tr("VCS Audit"))
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch()

        self.btn_open_log = QPushButton(self.tr("Open Log Folder"))
        self.btn_open_log.setObjectName("SecondaryButton")
        self.btn_open_log.clicked.connect(self._open_log_folder)
        header.addWidget(self.btn_open_log)
        layout.addLayout(header)

        self.lbl_path = QLabel(str(self.vm.audit_path))
        self.lbl_path.setStyleSheet("color: #64748B; font-size: 11px;")
        self.lbl_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.lbl_path)

        filters = QHBoxLayout()
        self.search_entry = QLineEdit()
        self.search_entry.setObjectName("FormInput")
        self.search_entry.setPlaceholderText(
            self.tr("Filter by operation, project, user, path or message")
        )
        self.search_entry.returnPressed.connect(self.refresh)
        filters.addWidget(self.search_entry, stretch=1)

        self.chk_failures = QCheckBox(self.tr("Failures only"))
        self.chk_failures.setStyleSheet("color: #94A3B8;")
        self.chk_failures.toggled.connect(self.refresh)
        filters.addWidget(self.chk_failures)

        self.btn_refresh = QPushButton(self.tr("Refresh"))
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.clicked.connect(self.refresh)
        filters.addWidget(self.btn_refresh)
        layout.addLayout(filters)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([self.tr(column) for column in self.COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setStyleSheet(
            "QTableWidget { background-color: #0F172A; color: #F8FAFC; "
            "border: 1px solid #334155; border-radius: 8px; "
            "alternate-background-color: #111C2E; gridline-color: #1E293B; }"
            "QHeaderView::section { background-color: #1E293B; color: #94A3B8; "
            "border: none; padding: 6px; font-weight: bold; }"
        )
        self.table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.table, stretch=1)

        detail_label = QLabel(self.tr("Event details"))
        detail_label.setStyleSheet("font-weight: bold; color: #E2E8F0;")
        layout.addWidget(detail_label)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setObjectName("FormInput")
        self.detail.setStyleSheet(
            "QPlainTextEdit { font-family: monospace; background-color: #0F172A; "
            "color: #E2E8F0; border: 1px solid #334155; border-radius: 8px; }"
        )
        self.detail.setFixedHeight(150)
        layout.addWidget(self.detail)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #94A3B8;")
        layout.addWidget(self.lbl_status)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.vm.load(
            limit=500,
            search=self.search_entry.text(),
            only_failures=self.chk_failures.isChecked(),
        )

    def _on_events(self, events: list) -> None:
        self._events = list(events or [])
        self.table.setRowCount(len(self._events))
        for row, event in enumerate(self._events):
            values = (
                self._format_time(str(event.get("timestamp", ""))),
                str(event.get("operation", "")),
                str(event.get("project", "")),
                str(event.get("user", "")),
                self.tr("OK") if event.get("ok", True) else self.tr("FAIL"),
                str(event.get("error_code", "")),
                f"{int(event.get('duration_ms', 0) or 0)} ms",
                ", ".join(str(path) for path in event.get("paths", []) or []),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4 and not event.get("ok", True):
                    item.setForeground(Qt.red)
                self.table.setItem(row, column, item)
        self.lbl_status.setText(self.tr("{0} event(s) shown.").format(len(self._events)))
        if self._events:
            self.table.selectRow(0)
        else:
            self.detail.clear()

    def _on_selection(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._events):
            self.detail.clear()
            return
        event = self._events[row]
        command = " ".join(str(part) for part in event.get("command", []) or [])
        lines = [
            self.tr("Time: {0}").format(event.get("timestamp", "")),
            self.tr("Operation: {0}").format(event.get("operation", "")),
            self.tr("Project: {0}").format(event.get("project", "")),
            self.tr("Server: {0}").format(event.get("server", "")),
            self.tr("User: {0}").format(event.get("user", "")),
            self.tr("Result: {0}").format(
                self.tr("OK") if event.get("ok", True) else self.tr("FAIL")
            ),
            self.tr("Return code: {0}").format(event.get("returncode", "")),
            self.tr("Error code: {0}").format(event.get("error_code", "")),
            self.tr("Revision: {0}").format(event.get("revision", "")),
            self.tr("Duration: {0} ms").format(event.get("duration_ms", 0)),
            self.tr("Paths: {0}").format(
                ", ".join(str(path) for path in event.get("paths", []) or [])
            ),
            self.tr("Message: {0}").format(event.get("message", "")),
            self.tr("Command: {0}").format(command),
        ]
        self.detail.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _format_time(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return value

    def _open_log_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.vm.audit_path.parent)))
