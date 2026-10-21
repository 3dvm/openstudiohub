# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/vcs_history_dialog.py
# Architectural role: UI View / VCS history and diff viewer (PySide6)
# =========================================================================================

"""Non-modal VCS history viewer for a task file.

Shows the revision log, a textual diff and a safe export action. Export always
writes to a user-selected file; it never overwrites the working-copy file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class VcsHistoryDialog(QDialog):
    def __init__(self, parent, viewmodel, card, task_label: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("VCS History"))
        self.setObjectName("ViewLoginBase")
        self.setMinimumSize(780, 720)
        self.resize(780, 720)
        self.setSizeGripEnabled(True)
        self.setModal(False)

        self.vm = viewmodel
        self.card = card
        self.task_id = str(card.task_data.get("id", ""))
        self.file_name = Path(card.task_file_path).name if card.task_file_path else ""
        self._connected = False

        self._build_ui(task_label)
        self._connect_signals()
        self._refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self, task_label: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(self.tr("File History"))
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        subtitle = QLabel(task_label or self.file_name)
        subtitle.setObjectName("MutedLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.revision_list = QListWidget()
        self.revision_list.setObjectName("DataList")
        self.revision_list.setFixedHeight(210)
        self.revision_list.currentItemChanged.connect(self._update_actions)
        layout.addWidget(self.revision_list)

        actions = QHBoxLayout()
        self.btn_diff = QPushButton(self.tr("Show diff"))
        self.btn_diff.setObjectName("SecondaryButton")
        self.btn_diff.clicked.connect(self._show_diff)
        actions.addWidget(self.btn_diff)

        self.btn_working = QPushButton(self.tr("Working copy diff"))
        self.btn_working.setObjectName("SecondaryButton")
        self.btn_working.clicked.connect(self._show_working_copy_diff)
        actions.addWidget(self.btn_working)

        self.btn_export = QPushButton(self.tr("Export revision..."))
        self.btn_export.setObjectName("SecondaryButton")
        self.btn_export.clicked.connect(self._export_revision)
        actions.addWidget(self.btn_export)

        self.btn_refresh = QPushButton(self.tr("Refresh"))
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.clicked.connect(self._refresh)
        actions.addWidget(self.btn_refresh)

        actions.addStretch()
        self.btn_close = QPushButton(self.tr("Close"))
        self.btn_close.setObjectName("PrimaryButton")
        self.btn_close.clicked.connect(self.close)
        actions.addWidget(self.btn_close)
        layout.addLayout(actions)

        lbl_diff = QLabel(self.tr("Diff"))
        lbl_diff.setObjectName("SectionTitle")
        layout.addWidget(lbl_diff)

        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setObjectName("CodeView")
        self.diff_view.setPlaceholderText(
            self.tr("Select a revision and press 'Show diff'.")
        )
        layout.addWidget(self.diff_view, stretch=1)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        self._update_actions()

    def _connect_signals(self) -> None:
        self.vm.vcs_history_ready.connect(self._on_history_ready)
        self.vm.vcs_history_failed.connect(self._on_history_failed)
        self.vm.vcs_diff_ready.connect(self._on_diff_ready)
        self.vm.vcs_export_finished.connect(self._on_export_finished)
        self._connected = True

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        self._set_status("", "neutral")
        self.lbl_status.setText(self.tr("Loading history..."))
        if not self.vm.request_vcs_history(self.card):
            self.lbl_status.setText(self.tr("Could not start the history request."))

    def _update_actions(self, _current=None, _previous=None) -> None:
        enabled = self.revision_list.currentItem() is not None
        self.btn_diff.setEnabled(enabled)
        self.btn_export.setEnabled(enabled)

    def _selected_revision(self) -> Optional[int]:
        item = self.revision_list.currentItem()
        if item is None:
            return None
        try:
            return int(item.data(Qt.UserRole))
        except (TypeError, ValueError):
            return None

    def _show_diff(self) -> None:
        revision = self._selected_revision()
        if revision is None:
            return
        self.diff_view.setPlainText(self.tr("Loading diff..."))
        self._set_status("", "neutral")
        self.lbl_status.setText(self.tr("Loading the diff for r{0}...").format(revision))
        if not self.vm.request_vcs_diff(self.card, revision):
            self.lbl_status.setText(self.tr("Could not start the diff request."))

    def _show_working_copy_diff(self) -> None:
        self.diff_view.setPlainText(self.tr("Loading diff..."))
        self._set_status("", "neutral")
        self.lbl_status.setText(self.tr("Loading the working copy diff..."))
        if not self.vm.request_vcs_diff(self.card, None):
            self.lbl_status.setText(self.tr("Could not start the diff request."))

    def _export_revision(self) -> None:
        revision = self._selected_revision()
        if revision is None:
            return
        suffix = Path(self.file_name).suffix
        stem = Path(self.file_name).stem or "revision"
        default_name = f"{stem}.r{revision}{suffix}"
        destination, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export Revision"),
            default_name,
        )
        if not destination:
            return
        self._set_status("", "neutral")
        self.lbl_status.setText(
            self.tr("Exporting revision {0}...").format(revision)
        )
        if not self.vm.export_vcs_revision(self.card, revision, Path(destination)):
            self.lbl_status.setText(self.tr("Could not start the revision export."))

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    def _on_history_ready(self, task_id: str, revisions: list) -> None:
        if task_id != self.task_id:
            return
        self.revision_list.clear()
        for revision in revisions or []:
            rev = str(revision.get("revision", ""))
            author = str(revision.get("author", "") or "unknown")
            date = str(revision.get("date", "") or "")
            message = str(revision.get("message", "") or "").replace("\n", " ").strip()
            label = f"r{rev}  {author}  {date}\n{message or self.tr('(no message)')}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, rev)
            self.revision_list.addItem(item)
        self._set_status("", "neutral")
        if self.revision_list.count():
            self.revision_list.setCurrentRow(0)
            self.lbl_status.setText(
                self.tr("{0} revision(s) loaded.").format(self.revision_list.count())
            )
        else:
            self.lbl_status.setText(self.tr("No revisions were found for this file."))
        self._update_actions()

    def _on_history_failed(self, task_id: str, message: str) -> None:
        if task_id != self.task_id:
            return
        self.lbl_status.setText(message)
        self._set_status(self.lbl_status.text(), "error")

    def _on_diff_ready(self, task_id: str, revision: str, diff: str) -> None:
        if task_id != self.task_id:
            return
        self.diff_view.setPlainText(diff or self.tr("(empty diff)"))
        if revision:
            self.lbl_status.setText(self.tr("Diff loaded for r{0}.").format(revision))
        else:
            self.lbl_status.setText(self.tr("Working copy diff loaded."))
        self._set_status(self.lbl_status.text(), "success")

    def _on_export_finished(self, task_id: str, success: bool, message: str) -> None:
        if task_id != self.task_id:
            return
        self._set_status(message, "success" if success else "error")

    def _set_status(self, message: str, state: str = "neutral") -> None:
        from src.interfaces.qt.ui_style import set_ui_state

        if message:
            self.lbl_status.setText(message)
        set_ui_state(self.lbl_status, "" if state == "neutral" else state)

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------
    def _disconnect(self) -> None:
        if not self._connected:
            return
        for signal, slot in (
            (self.vm.vcs_history_ready, self._on_history_ready),
            (self.vm.vcs_history_failed, self._on_history_failed),
            (self.vm.vcs_diff_ready, self._on_diff_ready),
            (self.vm.vcs_export_finished, self._on_export_finished),
        ):
            try:
                signal.disconnect(slot)
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
