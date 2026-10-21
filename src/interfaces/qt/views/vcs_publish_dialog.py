# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/vcs_publish_dialog.py
# Architectural role: UI View / VCS publish checklist (PySide6)
# =========================================================================================

"""Modal checklist to confirm which local files are published to the VCS.

Versioned changes are selected by default. Untracked files are shown in a
separate, collapsed-by-choice section and are never added to Subversion unless
the user explicitly selects them. The commit message is editable and includes
the completed checklist items of the task automatically.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
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
        self.setFixedSize(720, 680)
        self.setModal(True)
        self.setObjectName("ViewLoginBase")

        self.vm = viewmodel
        self.card = card
        self.changes = list(changes)
        self.task_id = str(card.task_data.get("id", ""))
        self.project_name = str(getattr(card, "project_name", "") or "project")
        self.file_name = (
            Path(card.task_file_path).name
            if getattr(card, "task_file_path", "")
            else "task files"
        )
        self.checklist_items = self._completed_checklist_items()
        self._auto_message = ""
        self._busy = False
        self._connected = False
        self._conflict_connected = False

        self._build_ui(task_label)
        self._populate_changes()
        self._refresh_auto_message()
        self.vm.vcs_publish_finished.connect(self._on_publish_finished)
        self._connected = True
        if hasattr(self.vm, "vcs_conflict_resolved"):
            self.vm.vcs_conflict_resolved.connect(self._on_conflict_resolved)
            self._conflict_connected = True

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self, task_label: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        title = QLabel(self.tr("Uncommitted Changes Detected"))
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        subtitle = task_label or self.tr("Select the files that should be published to the VCS.")
        info = QLabel(subtitle)
        info.setStyleSheet("color: #94A3B8;")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.lbl_tracked = QLabel(self.tr("Versioned changes"))
        self.lbl_tracked.setStyleSheet("font-weight: bold; color: #E2E8F0;")
        layout.addWidget(self.lbl_tracked)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155; border-radius: 8px; }"
        )
        self.list_widget.setMaximumHeight(150)
        self.list_widget.itemChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget)

        self.lbl_conflicts = QLabel(self.tr("Conflicts (resolve before publishing)"))
        self.lbl_conflicts.setStyleSheet("font-weight: bold; color: #EF4444;")
        self.lbl_conflicts.hide()
        layout.addWidget(self.lbl_conflicts)

        self.conflict_list = QListWidget()
        self.conflict_list.setStyleSheet(
            "QListWidget { background-color: #0F172A; color: #F8FAFC; border: 1px solid #7F1D1D; border-radius: 8px; }"
        )
        self.conflict_list.setMaximumHeight(90)
        self.conflict_list.currentItemChanged.connect(self._on_conflict_selection_changed)
        self.conflict_list.hide()
        layout.addWidget(self.conflict_list)

        self.btn_resolve_conflict = QPushButton(self.tr("Resolve selected conflict..."))
        self.btn_resolve_conflict.setObjectName("SecondaryButton")
        self.btn_resolve_conflict.setEnabled(False)
        self.btn_resolve_conflict.clicked.connect(self._resolve_conflict)
        self.btn_resolve_conflict.hide()
        layout.addWidget(self.btn_resolve_conflict)

        self.chk_show_untracked = QCheckBox(self.tr("Show untracked files"))
        self.chk_show_untracked.setChecked(True)
        self.chk_show_untracked.toggled.connect(self._toggle_untracked)
        layout.addWidget(self.chk_show_untracked)

        self.untracked_container = QVBoxLayout()
        self.lbl_untracked = QLabel(
            self.tr("Untracked files (not added unless you select them)")
        )
        self.lbl_untracked.setStyleSheet("font-weight: bold; color: #F59E0B;")
        self.untracked_container.addWidget(self.lbl_untracked)

        self.untracked_list = QListWidget()
        self.untracked_list.setStyleSheet(
            "QListWidget { background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155; border-radius: 8px; }"
        )
        self.untracked_list.setMaximumHeight(120)
        self.untracked_list.itemChanged.connect(self._on_selection_changed)
        self.untracked_container.addWidget(self.untracked_list)
        layout.addLayout(self.untracked_container)

        self.lbl_checklist = QLabel("")
        self.lbl_checklist.setWordWrap(True)
        self.lbl_checklist.setStyleSheet(
            "background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; "
            "padding: 10px; color: #10B981;"
        )
        self.lbl_checklist.hide()
        layout.addWidget(self.lbl_checklist)

        lbl_message = QLabel(self.tr("Commit message"))
        lbl_message.setStyleSheet("font-weight: bold; color: #E2E8F0;")
        layout.addWidget(lbl_message)

        self.entry_message = QPlainTextEdit()
        self.entry_message.setObjectName("FormInput")
        self.entry_message.setPlaceholderText(self.tr("Describe the published work..."))
        self.entry_message.setFixedHeight(110)
        layout.addWidget(self.entry_message)

        hint = QLabel(
            self.tr(
                "Completed checklist items are included automatically. "
                "New files are added to version control only when selected."
            )
        )
        hint.setStyleSheet("color: #64748B; font-size: 11px;")
        hint.setWordWrap(True)
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

    def _populate_changes(self) -> None:
        conflicted = [
            change for change in self.changes if getattr(change, "is_conflicted", False)
        ]
        tracked = [
            change
            for change in self.changes
            if not change.is_unversioned and not getattr(change, "is_conflicted", False)
        ]
        untracked = [change for change in self.changes if change.is_unversioned]

        for change in conflicted:
            item = QListWidgetItem(self._label_for(change))
            item.setData(Qt.UserRole, change)
            self.conflict_list.addItem(item)

        has_conflicts = bool(conflicted)
        self.lbl_conflicts.setVisible(has_conflicts)
        self.conflict_list.setVisible(has_conflicts)
        resolves = callable(getattr(self.vm, "resolve_vcs_conflict", None))
        self.btn_resolve_conflict.setVisible(has_conflicts and resolves)
        if has_conflicts and not resolves:
            self.lbl_conflicts.setText(
                self.tr("Conflicts must be resolved from the task dashboard before publishing.")
            )

        for change in tracked:
            item = QListWidgetItem(self._label_for(change))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, change)
            self.list_widget.addItem(item)

        for change in untracked:
            item = QListWidgetItem(self._label_for(change))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, change)
            self.untracked_list.addItem(item)

        self.lbl_tracked.setVisible(bool(tracked))
        self.list_widget.setVisible(bool(tracked))
        has_untracked = bool(untracked)
        self.chk_show_untracked.setVisible(has_untracked)
        self.untracked_container.setEnabled(has_untracked)
        if not has_untracked:
            self.lbl_untracked.hide()
            self.untracked_list.hide()

        if self.checklist_items:
            lines = "\n".join(f"- [x] {item}" for item in self.checklist_items)
            self.lbl_checklist.setText(
                self.tr("Completed checklist items included in the message:\n{0}").format(lines)
            )
            self.lbl_checklist.show()

    @staticmethod
    def _label_for(change) -> str:
        state = STATUS_LABELS.get(change.status, change.status or "Change")
        return f"[{state}]  {change.relative_path}"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def selected_changes(self) -> list:
        selected = []
        for widget in (self.list_widget, self.untracked_list):
            for index in range(widget.count()):
                item = widget.item(index)
                if item.checkState() == Qt.Checked:
                    selected.append(item.data(Qt.UserRole))
        return selected

    def commit_message(self) -> str:
        return self.entry_message.toPlainText().strip()

    def _completed_checklist_items(self) -> list[str]:
        getter = getattr(self.vm, "completed_checklist_items", None)
        if not callable(getter):
            return []
        try:
            return list(getter(self.task_id) or [])
        except Exception:  # noqa: BLE001 - the dialog must remain usable
            return []

    def _build_auto_message(self, file_count: int) -> str:
        message = (
            f"OpenStudioHub: {file_count} file(s) for {self.project_name} "
            f"({self.file_name})."
        )
        if self.checklist_items:
            checklist = "\n".join(f"- [x] {item}" for item in self.checklist_items)
            message += f"\n\nCompleted checklist:\n{checklist}"
        return message

    def _refresh_auto_message(self) -> None:
        self._auto_message = self._build_auto_message(len(self.selected_changes()))
        self.entry_message.setPlainText(self._auto_message)

    def _on_selection_changed(self, _item=None) -> None:
        current = self.entry_message.toPlainText()
        if current.strip() != self._auto_message.strip():
            return
        self._auto_message = self._build_auto_message(len(self.selected_changes()))
        self.entry_message.setPlainText(self._auto_message)

    def _toggle_untracked(self, checked: bool) -> None:
        visible = bool(checked) and self.untracked_list.count() > 0
        if not checked:
            for index in range(self.untracked_list.count()):
                self.untracked_list.item(index).setCheckState(Qt.Unchecked)
        self.lbl_untracked.setVisible(visible)
        self.untracked_list.setVisible(visible)

    def _on_conflict_selection_changed(self, current, _previous=None) -> None:
        self.btn_resolve_conflict.setEnabled(current is not None and not self._busy)

    def _resolve_conflict(self) -> None:
        item = self.conflict_list.currentItem()
        if item is None or self._busy:
            return
        change = item.data(Qt.UserRole)
        resolver = getattr(self.vm, "resolve_vcs_conflict", None)
        if not callable(resolver):
            self._show_status(
                self.tr("Conflicts must be resolved from the task dashboard."),
                error=True,
            )
            return

        box = QMessageBox(self)
        box.setWindowTitle(self.tr("Resolve Conflict"))
        box.setText(
            self.tr("Choose how to resolve the conflict for:\n{0}").format(
                change.relative_path
            )
        )
        mine = box.addButton(self.tr("Keep mine"), QMessageBox.AcceptRole)
        theirs = box.addButton(self.tr("Take theirs"), QMessageBox.DestructiveRole)
        working = box.addButton(self.tr("Mark resolved"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()

        clicked = box.clickedButton()
        if clicked is mine:
            strategy = "mine-full"
        elif clicked is theirs:
            strategy = "theirs-full"
        elif clicked is working:
            strategy = "working"
        else:
            return

        self._set_busy(True)
        self._show_status(self.tr("Resolving the conflict..."))
        if not resolver(self.card, change, strategy):
            self._set_busy(False)

    def _on_conflict_resolved(self, task_id: str, success: bool, message: str) -> None:
        if task_id != self.task_id:
            return
        self._set_busy(False)
        if success:
            self._show_status(message)
            self.accept()
        else:
            self._show_status(message, error=True)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_publish.setEnabled(not busy)
        self.btn_postpone.setEnabled(not busy)
        self.list_widget.setEnabled(not busy)
        self.untracked_list.setEnabled(not busy)
        self.conflict_list.setEnabled(not busy)
        self.btn_resolve_conflict.setEnabled(
            not busy and self.conflict_list.currentItem() is not None
        )
        self.chk_show_untracked.setEnabled(not busy)
        self.entry_message.setEnabled(not busy)

    def _show_status(self, message: str, error: bool = False) -> None:
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet(
            "color: #EF4444; font-weight: bold;" if error else "color: #10B981; font-weight: bold;"
        )

    def _publish(self) -> None:
        if self._busy:
            return
        selected = self.selected_changes()
        if not selected:
            self._show_status(self.tr("Select at least one file to publish."), error=True)
            return
        message = self.commit_message()
        if not message:
            self._show_status(self.tr("The commit message cannot be empty."), error=True)
            return
        self._set_busy(True)
        self._show_status(self.tr("Publishing selected files to the VCS..."))
        if not self.vm.publish_vcs_changes(self.card, selected, message=message):
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
        if self._conflict_connected:
            try:
                self.vm.vcs_conflict_resolved.disconnect(self._on_conflict_resolved)
            except (RuntimeError, TypeError):
                pass
            self._conflict_connected = False

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._disconnect()
        super().closeEvent(event)

    def accept(self) -> None:  # noqa: D102 (Qt override)
        self._disconnect()
        super().accept()

    def reject(self) -> None:  # noqa: D102 (Qt override)
        self._disconnect()
        super().reject()
