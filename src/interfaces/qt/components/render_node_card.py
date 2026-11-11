# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/render_node_card.py
# Architectural role: UI component / render node status card
# =========================================================================================

"""Compact card that shows one render node from candidate to finished state."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from src.interfaces.qt.ui_format import format_bytes, format_duration, format_rate

_STATUS_COLORS = {
    "candidate": "#94A3B8",
    "queued": "#94A3B8",
    "creating": "#38BDF8",
    "booting": "#38BDF8",
    "ssh": "#38BDF8",
    "installing": "#38BDF8",
    "staging": "#38BDF8",
    "rendering": "#F59E0B",
    "syncing": "#F59E0B",
    "baking": "#F59E0B",
    "validating": "#F59E0B",
    "completed": "#10B981",
    "failed": "#EF4444",
    "destroyed": "#94A3B8",
    "cancelled": "#EF4444",
}


class RenderNodeCard(QFrame):
    relaunch_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("NodeCard")
        self.setMinimumWidth(210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        self.lbl_title = QLabel(self.tr("Node"))
        self.lbl_title.setStyleSheet("font-weight: bold; color: #F8FAFC;")
        layout.addWidget(self.lbl_title)

        self.lbl_status = QLabel(self.tr("candidate"))
        self.lbl_status.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lbl_status)

        self.lbl_details = QLabel("")
        self.lbl_details.setWordWrap(True)
        self.lbl_details.setStyleSheet("color: #CBD5E1; font-size: 11px;")
        layout.addWidget(self.lbl_details)

        self.lbl_meta = QLabel("")
        self.lbl_meta.setWordWrap(True)
        self.lbl_meta.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(self.lbl_meta)

        self.lbl_message = QLabel("")
        self.lbl_message.setWordWrap(True)
        self.lbl_message.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(self.lbl_message)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        layout.addWidget(self.progress)
        self.lbl_eta = QLabel("")
        self.lbl_eta.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(self.lbl_eta)

        self.btn_relaunch = QPushButton(self.tr("Relaunch node"))
        self.btn_relaunch.setObjectName("SecondaryButton")
        self.btn_relaunch.hide()
        self.btn_relaunch.clicked.connect(
            lambda _checked=False: self.relaunch_requested.emit(self._card_key)
        )
        layout.addWidget(self.btn_relaunch)

        self.logs_layout = QHBoxLayout()
        self.logs_layout.setSpacing(4)
        layout.addLayout(self.logs_layout)
        layout.addStretch()
        self._log_signature = ()
        self._card_key = ""

    def update_model(self, card) -> None:
        self._card_key = str(getattr(card, "key", "") or "")
        is_local = str(getattr(card, "gpu_name", "")).lower().startswith("local")
        title = (
            self.tr("Local workstation")
            if is_local
            else self.tr("Node {0}").format(card.node + 1)
        )
        run_label = str(getattr(card, "run_label", "") or "")
        if run_label and not is_local:
            title = f"{title} · {run_label}"
        self.lbl_title.setText(title)
        status = str(getattr(card, "status", "") or "candidate")
        self.lbl_status.setText(status.replace("_", " ").title())
        self.lbl_status.setStyleSheet(
            f"font-weight: bold; color: {_STATUS_COLORS.get(status, '#94A3B8')};"
        )
        details = [str(getattr(card, "gpu_name", "") or "")]
        if getattr(card, "region", ""):
            details.append(str(card.region))
        if getattr(card, "price_per_hour", 0):
            details.append(f"${float(card.price_per_hour):.2f}/h")
        if getattr(card, "current_shot", ""):
            details.append(f"shot {card.current_shot}")
        self.lbl_details.setText(" · ".join(part for part in details if part) or "—")
        meta = []
        if getattr(card, "instance_id", 0):
            meta.append(f"instance {card.instance_id}")
        done = int(getattr(card, "frames_done", 0) or 0)
        expected = int(getattr(card, "frames_expected", 0) or 0)
        percent = float(getattr(card, "progress_percent", 0.0) or 0.0)
        upload_total = int(getattr(card, "upload_bytes_total", 0) or 0)
        upload_done = int(getattr(card, "upload_bytes_done", 0) or 0)
        if upload_total > 0 and str(getattr(card, "stage", "")) == "stage":
            meta.append(
                f"{format_bytes(upload_done)} / {format_bytes(upload_total)} "
                f"· {percent:.0f}%"
            )
            files = int(getattr(card, "upload_files", 0) or 0)
            if files:
                meta.append(f"{files:,} file(s)")
        elif expected > 0:
            meta.append(f"{done}/{expected} frames · {percent:.0f}%")
        if getattr(card, "seconds_per_frame", 0):
            meta.append(f"{format_rate(float(card.seconds_per_frame))}/frame")
        if getattr(card, "cost", 0):
            meta.append(f"${float(card.cost):.3f}")
        self.lbl_meta.setText(" · ".join(meta))
        self.lbl_message.setText(str(getattr(card, "message", "") or ""))
        self.progress.setValue(max(0, min(100, int(percent))))
        eta = float(getattr(card, "eta_seconds", 0.0) or 0.0)
        has_assignment = bool(getattr(card, "assignment", ()) or ())
        self.btn_relaunch.setVisible(
            status == "failed" and has_assignment and not is_local
        )
        self.btn_relaunch.setEnabled(
            status == "failed" and has_assignment and not is_local
        )
        if getattr(card, "final", False):
            self.lbl_eta.setText("")
        elif eta > 0:
            self.lbl_eta.setText(
                self.tr("~{0} remaining").format(format_duration(eta))
            )
        elif status in ("rendering", "queued"):
            self.lbl_eta.setText(self.tr("Estimating remaining time..."))
        else:
            self.lbl_eta.setText("")
        if getattr(card, "final", False):
            self._sync_logs(card)
        elif self._log_signature:
            self._clear_logs()

    def _sync_logs(self, card) -> None:
        signature = (
            tuple(str(path) for path in getattr(card, "hub_logs", ())),
            tuple(str(path) for path in getattr(card, "summary_logs", ())),
            tuple(str(path) for path in getattr(card, "blender_logs", ())),
        )
        if signature == self._log_signature:
            return
        self._clear_logs()
        self._log_signature = signature
        for index, path in enumerate(card.hub_logs or ()):
            self._add_log_button(path, self.tr("Hub log") if index == 0 else f"Hub log {index + 1}")
        for index, path in enumerate(card.summary_logs or ()):
            self._add_log_button(path, self.tr("Summary") if index == 0 else f"Summary {index + 1}")
        for index, path in enumerate(card.blender_logs or ()):
            self._add_log_button(
                path, self.tr("Blender log") if index == 0 else f"Blender log {index + 1}"
            )

    def _add_log_button(self, path, label: str) -> None:
        candidate = Path(path)
        if not candidate.is_file():
            return
        button = QPushButton(label)
        button.setObjectName("SecondaryButton")
        button.clicked.connect(
            lambda _checked=False, target=candidate: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(target))
            )
        )
        self.logs_layout.addWidget(button)

    def _clear_logs(self) -> None:
        while self.logs_layout.count():
            item = self.logs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._log_signature = ()
