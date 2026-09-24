# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/project_export_dialog.py
# Architectural role: UI Component / Kitsu project export (PySide6)
# =========================================================================================

"""Modal for exporting a Kitsu project to a ``.oshproject`` archive.

Collects the inclusion options, shows an approximate per-category size table and
then the live progress (bar, phase, log, Cancel), mirroring the VCS migration
progress window.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.application.services.oshproject_format import human_bytes

DEFAULT_MEDIA_CAP_MB = 200

_CATEGORY_LABELS = [
    ("kitsu", "Kitsu metadata (project/entities/tasks/comments)"),
    ("media_previews", "Preview media"),
    ("media_attachments", "Comment attachments"),
    ("files_pipeline", "Non-VCS files: pipeline/"),
    ("files_shared", "Non-VCS files: shared/"),
    ("vcs_dump", "Embedded SVN dump"),
]


class ProjectExportDialog(QDialog):
    estimate_requested = Signal(dict)
    start_requested = Signal(str, dict)
    cancel_requested = Signal()

    def __init__(self, parent, project_name: str, default_dir: Optional[Path] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export Kitsu Project"))
        self.resize(720, 640)
        self.setMinimumSize(560, 420)
        self.setModal(True)
        self.setObjectName("FloatingCard")
        self.project_name = project_name
        self._running = False
        self._finished = False
        self._build_ui(default_dir)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self, default_dir: Optional[Path]) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 12)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(26, 22, 26, 10)
        layout.setSpacing(12)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        title = QLabel(self.tr(f"Export '{self.project_name}'"))
        title.setObjectName("H2Title")
        layout.addWidget(title)

        notice = QLabel(
            self.tr(
                "Creates a portable .oshproject bundle (metadata + media). "
                "It never contains passwords, tokens or SSH keys."
            )
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(notice)

        dest_layout = QHBoxLayout()
        self.entry_dest = QLineEdit()
        self.entry_dest.setObjectName("FormInput")
        self.entry_dest.setFixedHeight(35)
        if default_dir is not None:
            self.entry_dest.setText(str(default_dir))
        self.entry_dest.setPlaceholderText(self.tr("Destination folder"))
        dest_layout.addWidget(self.entry_dest, stretch=1)

        self.btn_browse = QPushButton(self.tr("Browse..."))
        self.btn_browse.setObjectName("SecondaryButton")
        self.btn_browse.setFixedHeight(35)
        self.btn_browse.clicked.connect(self._browse)
        dest_layout.addWidget(self.btn_browse)
        layout.addLayout(dest_layout)

        options_layout = QHBoxLayout()

        self.chk_media = QCheckBox(self.tr("Include previews and attachments"))
        self.chk_media.setChecked(True)
        self.chk_media.toggled.connect(self._on_options_changed)
        options_layout.addWidget(self.chk_media)

        options_layout.addWidget(QLabel(self.tr("Media cap (MB):")))
        self.spin_cap = QSpinBox()
        self.spin_cap.setRange(0, 100000)
        self.spin_cap.setValue(DEFAULT_MEDIA_CAP_MB)
        self.spin_cap.setSuffix(" MB")
        self.spin_cap.valueChanged.connect(self._on_options_changed)
        options_layout.addWidget(self.spin_cap)
        options_layout.addStretch()

        self.chk_shared = QCheckBox(self.tr("Include shared/ (local/ excluded)"))
        self.chk_shared.toggled.connect(self._on_options_changed)
        options_layout.addWidget(self.chk_shared)

        self.chk_dump = QCheckBox(self.tr("Embed SVN dump (self-contained)"))
        self.chk_dump.toggled.connect(self._on_options_changed)
        options_layout.addWidget(self.chk_dump)
        layout.addLayout(options_layout)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([self.tr("Category"), self.tr("Approx. size")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setFixedHeight(220)
        self._populate_table({})
        layout.addWidget(self.table)

        self.lbl_approx = QLabel(self.tr("Sizes are approximate."))
        self.lbl_approx.setStyleSheet("color: #64748B; font-size: 11px;")
        layout.addWidget(self.lbl_approx)

        self.lbl_status = QLabel(self.tr("Configure the export and press Export."))
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

        self.btn_estimate = QPushButton(self.tr("Estimate Size"))
        self.btn_estimate.setObjectName("SecondaryButton")
        self.btn_estimate.setFixedHeight(35)
        self.btn_estimate.clicked.connect(lambda: self.estimate_requested.emit(self.options()))
        buttons.addWidget(self.btn_estimate)

        self.btn_cancel = QPushButton(self.tr("Cancel"))
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.setFixedHeight(35)
        self.btn_cancel.clicked.connect(self._on_cancel)
        buttons.addWidget(self.btn_cancel)

        self.btn_export = QPushButton(self.tr("Export"))
        self.btn_export.setObjectName("PrimaryButton")
        self.btn_export.setFixedHeight(35)
        self.btn_export.clicked.connect(self._on_export)
        buttons.addWidget(self.btn_export)

        buttons.setContentsMargins(26, 4, 26, 0)
        root.addLayout(buttons)

    def _populate_table(self, sizes: dict) -> None:
        self.table.setRowCount(0)
        for key, label in _CATEGORY_LABELS:
            if key == "vcs_dump" and not self.chk_dump.isChecked():
                continue
            self._add_row(label, sizes.get(key, 0))
        total = sizes.get("total")
        if total is None:
            total = sum(sizes.get(key, 0) for key, _ in _CATEGORY_LABELS if key in sizes)
        self._add_row(self.tr("TOTAL (approx.)"), total, bold=True)

    def _add_row(self, label: str, value, bold: bool = False) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(label))
        self.table.setItem(row, 1, QTableWidgetItem(human_bytes(value)))
        if bold:
            for column in (0, 1):
                item = self.table.item(row, column)
                font = item.font()
                font.setBold(True)
                item.setFont(font)

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------
    def options(self) -> dict:
        return {
            "include_media": self.chk_media.isChecked(),
            "include_shared": self.chk_shared.isChecked(),
            "embed_svn_dump": self.chk_dump.isChecked(),
            "media_cap_mb": int(self.spin_cap.value()),
        }

    def destination_dir(self) -> str:
        return self.entry_dest.text().strip()

    def _on_options_changed(self) -> None:
        self.spin_cap.setEnabled(self.chk_media.isChecked())
        self._populate_table({})

    def _browse(self) -> None:
        start = self.entry_dest.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, self.tr("Select destination folder"), start)
        if chosen:
            self.entry_dest.setText(chosen)

    def _on_export(self) -> None:
        destination = self.destination_dir()
        if not destination:
            self.lbl_status.setText(self.tr("Choose a destination folder first."))
            self.lbl_status.setStyleSheet("color: #EF4444; font-size: 12px;")
            return
        self._running = True
        self.btn_export.setEnabled(False)
        self.btn_estimate.setEnabled(False)
        self.entry_dest.setEnabled(False)
        self.chk_media.setEnabled(False)
        self.chk_shared.setEnabled(False)
        self.chk_dump.setEnabled(False)
        self.btn_cancel.setText(self.tr("Cancel Export"))
        self.progress.show()
        self.log_output.show()
        self.start_requested.emit(destination, self.options())

    def _on_cancel(self) -> None:
        if self._running and not self._finished:
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText(self.tr("Cancelling..."))
            self.cancel_requested.emit()
            return
        self.reject()

    # ------------------------------------------------------------------
    # Live updates (driven by the ViewModel)
    # ------------------------------------------------------------------
    def set_estimate(self, sizes: dict) -> None:
        self._populate_table(sizes or {})
        self.lbl_status.setText(self.tr("Approximate size updated."))
        self.lbl_status.setStyleSheet("color: #94A3B8; font-size: 12px;")

    def set_phase(self, message: str) -> None:
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet("color: #F59E0B; font-size: 12px;")

    def set_progress(self, percent: int) -> None:
        self.progress.setValue(max(0, min(100, int(percent))))

    def append_log(self, line: str) -> None:
        self.log_output.appendPlainText(line)
        self.log_output.moveCursor(QTextCursor.End)

    def on_export_finished(self, _project_name: str, success: bool, message: str) -> None:
        """Adapter slot for the ViewModel's ``export_finished`` signal."""
        self.finalize(success, message)

    def finalize(self, success: bool, message: str) -> None:
        self._running = False
        self._finished = True
        self.btn_cancel.setText(self.tr("Close"))
        self.btn_cancel.setEnabled(True)
        if success:
            self.progress.setValue(100)
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #10B981; font-weight: bold; font-size: 12px;")
        else:
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 12px;")
        self.append_log(("Exported: " if success else "Failed: ") + message)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._running and not self._finished:
            self._on_cancel()
            event.ignore()
            return
        super().closeEvent(event)
