# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/migration_progress_dialog.py
# Architectural role: UI Component / VCS migration progress (PySide6)
# =========================================================================================

"""Modal progress window for a VCS repository migration.

Shows the live phase, a progress bar, revision/throughput/ETA statistics and a
log tail, and allows the user to cancel the running dump/load.
"""

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


class MigrationProgressDialog(QDialog):
    cancel_requested = Signal()

    def __init__(self, parent, project_name: str, source: dict, target: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Migrating VCS Repository"))
        self.setFixedSize(680, 460)
        self.setModal(True)
        self.setObjectName("FloatingCard")
        self.project_name = project_name
        self._finished = False
        self._build_ui(source, target)

    def _build_ui(self, source: dict, target: dict) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel(self.tr(f"Migrating '{self.project_name}'"))
        title.setObjectName("H2Title")
        layout.addWidget(title)

        route = QLabel(
            self.tr(f"{source.get('name', '?')}  →  {target.get('name', '?')}")
        )
        route.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 13px;")
        layout.addWidget(route)

        self.lbl_status = QLabel(self.tr("Starting..."))
        self.lbl_status.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.lbl_stats = QLabel(self.tr("Preparing..."))
        self.lbl_stats.setStyleSheet("color: #94A3B8; font-size: 11px; font-family: monospace;")
        layout.addWidget(self.lbl_stats)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("FormInput")
        self.log_output.setStyleSheet(
            "font-family: monospace; font-size: 11px; color: #94A3B8; background-color: #0F172A;"
        )
        layout.addWidget(self.log_output, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.btn_cancel = QPushButton(self.tr("Cancel Migration"))
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.setFixedHeight(35)
        self.btn_cancel.clicked.connect(self._on_cancel)
        buttons.addWidget(self.btn_cancel)

        self.btn_close = QPushButton(self.tr("Close"))
        self.btn_close.setObjectName("PrimaryButton")
        self.btn_close.setFixedHeight(35)
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.hide()
        buttons.addWidget(self.btn_close)

        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    def set_phase(self, message: str) -> None:
        self.lbl_status.setText(message)

    def update_detail(self, detail: dict) -> None:
        percent = int(detail.get("percent", 0))
        self.progress.setValue(max(0, min(100, percent)))

        total = detail.get("total") or 0
        revision = detail.get("revision") or 0
        speed = detail.get("speed") or 0.0
        eta = detail.get("eta")
        elapsed = detail.get("elapsed") or 0.0

        eta_text = self._format_seconds(eta) if eta is not None else "--:--"
        self.lbl_stats.setText(
            f"rev {revision}/{total or '?'}   {self._human_bytes(speed)}/s   "
            f"ETA {eta_text}   elapsed {self._format_seconds(elapsed)}"
        )

    def append_log(self, text: str) -> None:
        self.log_output.appendPlainText(text)
        self.log_output.moveCursor(QTextCursor.End)

    def finalize(self, success: bool, message: str) -> None:
        self._finished = True
        self.btn_cancel.hide()
        self.btn_close.show()
        if success:
            self.progress.setValue(100)
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #10B981; font-weight: bold; font-size: 12px;")
        else:
            self.lbl_status.setText(message)
            self.lbl_status.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 12px;")
        self.append_log(("✅ " if success else "❌ ") + message)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _on_cancel(self) -> None:
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText(self.tr("Cancelling..."))
        self.cancel_requested.emit()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Prevent closing while the operation is still running.
        if not self._finished:
            self._on_cancel()
            event.ignore()
            return
        super().closeEvent(event)

    @staticmethod
    def _format_seconds(seconds) -> str:
        try:
            total = int(seconds)
        except (TypeError, ValueError):
            return "--:--"
        return f"{total // 60:02d}:{total % 60:02d}"

    @staticmethod
    def _human_bytes(value: float) -> str:
        size = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
