# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/offer_diagnostics_dialog.py
# Architectural role: UI component / Vast.ai offer diagnostics
# =========================================================================================

"""Read-only offer table with the exact limits every candidate failed."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class OfferDiagnosticsDialog(QDialog):
    """Show every candidate offer and what it needs to become valid."""

    def __init__(
        self,
        parent: QWidget | None,
        diagnostics,
        alternatives=(),
        *,
        on_use_profile=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Vast.ai offers"))
        self.resize(980, 520)
        self._diagnostics = diagnostics
        self._alternatives = list(alternatives or ())
        self._on_use_profile = on_use_profile

        layout = QVBoxLayout(self)
        title = QLabel(str(getattr(diagnostics, "message", "") or "No offer found."))
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        limits = getattr(diagnostics, "limits", None)
        if limits is not None:
            layout.addWidget(
                QLabel(
                    self.tr(
                        "Limits: max ${0:.3f}/h · host RAM >= {1:.0f} GB · "
                        "{2:.0f}/{3:.0f} Mbps · reliability >= {4:.2f}"
                    ).format(
                        float(getattr(limits, "max_price_per_hour", 0.0)),
                        float(getattr(limits, "min_cpu_ram_gb", 0.0)),
                        float(getattr(limits, "min_inet_down_mbps", 0.0)),
                        float(getattr(limits, "min_inet_up_mbps", 0.0)),
                        float(getattr(limits, "min_reliability", 0.0)),
                    )
                )
            )

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Offer"),
                self.tr("GPU"),
                self.tr("Price"),
                self.tr("Host RAM"),
                self.tr("Download"),
                self.tr("Upload"),
                self.tr("Reliability"),
                self.tr("Result"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self._fill_candidates()

        if self._alternatives:
            layout.addWidget(
                QLabel(self.tr("Other GPU profiles that match the limits:"))
            )
            self.alternate_table = QTableWidget(0, 7)
            self.alternate_table.setHorizontalHeaderLabels(
                [
                    self.tr("GPU profile"),
                    self.tr("Offer"),
                    self.tr("GPU"),
                    self.tr("Price"),
                    self.tr("Host RAM"),
                    self.tr("Network"),
                    self.tr("Action"),
                ]
            )
            self.alternate_table.verticalHeader().setVisible(False)
            self.alternate_table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.alternate_table.horizontalHeader().setStretchLastSection(True)
            self._fill_alternatives()
            layout.addWidget(self.alternate_table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _fill_candidates(self) -> None:
        reports = list(getattr(self._diagnostics, "candidates", ()) or ())
        reports.sort(key=lambda report: (not report.passing, report.score))
        self.table.setRowCount(len(reports))
        for row, report in enumerate(reports):
            offer = report.offer
            values = [
                str(offer.offer_id),
                offer.gpu_name,
                f"${offer.price_per_hour:.3f}/h",
                f"{offer.cpu_ram_gb:.1f} GB",
                f"{offer.inet_down_mbps:.0f} Mbps",
                f"{offer.inet_up_mbps:.0f} Mbps",
                f"{offer.reliability:.3f}",
                self.tr("Matches") if report.passing else report.failure_text,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (2, 3, 4, 5, 6):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()

    def _fill_alternatives(self) -> None:
        self.alternate_table.setRowCount(len(self._alternatives))
        for row, alternative in enumerate(self._alternatives):
            offer = alternative.offer
            values = [
                alternative.gpu_label,
                str(offer.offer_id),
                offer.gpu_name,
                f"${offer.price_per_hour:.3f}/h",
                f"{offer.cpu_ram_gb:.1f} GB",
                f"{offer.inet_down_mbps:.0f}/{offer.inet_up_mbps:.0f} Mbps",
            ]
            for column, value in enumerate(values):
                self.alternate_table.setItem(row, column, QTableWidgetItem(value))
            if callable(self._on_use_profile):
                button = QPushButton(self.tr("Use profile"))
                button.clicked.connect(
                    lambda _checked=False, key=alternative.gpu_profile: (
                        self._on_use_profile(key),
                        self.accept(),
                    )
                )
                self.alternate_table.setCellWidget(row, 6, button)
        self.alternate_table.resizeColumnsToContents()
