# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/vcs_publish_dialog.py
# Architectural role: UI View / VCS publish checklist (PySide6)
# =========================================================================================

"""Modal checklist to confirm which local files are published to the VCS.

Opened automatically when a DCC session ends with uncommitted changes, or from
the ``Update VCS (N)`` task-card button. Every ``FileChange`` is checked by
default; the artist can untick anything that should not be committed. New
(unversioned) files are clearly flagged and will be ``add``ed on publish.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

STATUS_LABELS = {
    "M": "Modified",
    "A": "Added",
    "D": "Deleted",
    "R": "Replaced",
    "C": "Conflicted",
    "!": "Missing",
    "~": "Type changed",
    "?": "New (add)",
}


class VcsPublishDialog(QDialog):
    def __init__(self, parent, viewmodel, card, changes: list, task_label: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Publish Task Files to VCS"))
        self.setFixedSize(620, 460)
        self.setModal(True)
        self.setObjectName("ViewLoginBase")

        self.vm = viewmodel
        self.card = card
        self.changes = list(changes)
        self.task_id = str(card.task_data.get("id", ""))
        self._busy = False
        self._connected = False

        self._build_ui(task_label)
        self.vm.vcs_publish_finished.connect(self._on_publish_finished)
        self._connected = True

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self, task_label: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel(self.tr("Uncommitted Changes Detected"))
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        subtitle = task_label or self.tr("Select the files that should be published to the VCS.")
        info = QLabel(subtitle)
        info.setStyleSheet("color: #94A3B8;")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155; border-radius: 8px; }"
        )
        for change in self.changes:
            item = QListWidgetItem(self._label_for(change))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, change)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, stretch=1)

        hint = QLabel(self.tr("New files are added to version control when published."))
        hint.setStyleSheet("color: #64748B; font-size: 11px;")
        layout.addWidget(hint)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        footer = QHBoxLayout()
        footer.addStretch()

        self.btn_postpone = QPushButton(self.tr("Postpone"))
        self.btn_postpone.setObjectName("SecondaryButton")
        self.btn_postpone.clicked.connect(self.reject)
        footer.addWidget(self.btn_postpone)

        self.btn_publish = QPushButton(self.tr("Publish selected"))
        self.btn_publish.setObjectName("PrimaryButton")
        self.btn_publish.clicked.connect(self._publish)
        footer.addWidget(self.btn_publish)

        layout.addLayout(footer)

    @staticmethod
    def _label_for(change) -> str:
        state = STATUS_LABELS.get(change.status, change.status or "Change")
        return f"[{state}]  {change.relative_path}"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def selected_changes(self) -> list:
        selected = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        return selected

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_publish.setEnabled(not busy)
        self.btn_postpone.setEnabled(not busy)
        self.list_widget.setEnabled(not busy)

    def _show_status(self, message: str, error: bool = False) -> None:
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet("color: #EF4444; font-weight: bold;" if error else "color: #10B981; font-weight: bold;")

    def _publish(self) -> None:
        if self._busy:
            return
        selected = self.selected_changes()
        if not selected:
            self._show_status(self.tr("Select at least one file to publish."), error=True)
            return
        self._set_busy(True)
        self._show_status(self.tr("Publishing selected files to the VCS..."))
        if not self.vm.publish_vcs_changes(self.card, selected):
            self._set_busy(False)

    def _on_publish_finished(self, task_id: str, success: bool, message: str) -> None:
        if task_id != self.task_id:
            return
        self._set_busy(False)
        if success:
            self._show_status(message)
            self.accept()
        else:
            self._show_status(message, error=True)

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------
    def _disconnect(self) -> None:
        if self._connected:
            try:
                self.vm.vcs_publish_finished.disconnect(self._on_publish_finished)
            except (RuntimeError, TypeError):
                pass
            self._connected = False

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._disconnect()
        super().closeEvent(event)

    def accept(self) -> None:  # noqa: D102 (Qt override)
        self._disconnect()
        super().accept()

    def reject(self) -> None:  # noqa: D102 (Qt override)
        self._disconnect()
        super().reject()
