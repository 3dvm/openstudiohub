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
    QWidget,
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
        self.setMinimumSize(720, 680)
        self.resize(720, 680)
        self.setSizeGripEnabled(True)
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
        self._checklist_items: list[dict] = []
        self._checklist_boxes: dict[tuple[str, int], QCheckBox] = {}
        self._checklist_saving = False
        self._auto_message = ""
        self._busy = False
        self._connected = False
        self._conflict_connected = False
        self._checklist_connected = False
        self._checklist_saving_connected = False
        self._paths_connected = False

        self._build_ui(task_label)
        self._populate_changes()
        self._load_checklist()
        self._refresh_auto_message()
        self.vm.vcs_publish_finished.connect(self._on_publish_finished)
        self._connected = True
        if hasattr(self.vm, "vcs_conflict_resolved"):
            self.vm.vcs_conflict_resolved.connect(self._on_conflict_resolved)
            self._conflict_connected = True
        if hasattr(self.vm, "task_checklist_ready"):
            self.vm.task_checklist_ready.connect(self._on_task_checklist_ready)
            self._checklist_connected = True
        if hasattr(self.vm, "task_checklist_saving"):
            self.vm.task_checklist_saving.connect(self._on_task_checklist_saving)
            self._checklist_saving_connected = True
        if hasattr(self.vm, "vcs_paths_handled"):
            self.vm.vcs_paths_handled.connect(self._on_vcs_paths_handled)
            self._paths_connected = True

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self, task_label: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(self.tr("Uncommitted Changes Detected"))
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        subtitle = task_label or self.tr("Select the files that should be published to the VCS.")
        info = QLabel(subtitle)
        info.setObjectName("MutedLabel")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.lbl_tracked = QLabel(self.tr("Versioned changes"))
        self.lbl_tracked.setObjectName("SectionTitle")
        layout.addWidget(self.lbl_tracked)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("DataList")
        self.list_widget.setMaximumHeight(150)
        self.list_widget.itemChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget)

        self.lbl_conflicts = QLabel(self.tr("Conflicts (resolve before publishing)"))
        self.lbl_conflicts.setObjectName("WarningLabel")
        self.lbl_conflicts.hide()
        layout.addWidget(self.lbl_conflicts)

        self.conflict_list = QListWidget()
        self.conflict_list.setObjectName("DataList")
        self.conflict_list.setProperty("severity", "error")
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

        self.lbl_missing = QLabel(self.tr("Missing files (deleted from disk)"))
        self.lbl_missing.setObjectName("WarningLabel")
        self.lbl_missing.hide()
        layout.addWidget(self.lbl_missing)

        self.missing_list = QListWidget()
        self.missing_list.setObjectName("DataList")
        self.missing_list.setMaximumHeight(110)
        self.missing_list.itemChanged.connect(self._on_missing_selection_changed)
        self.missing_list.hide()
        layout.addWidget(self.missing_list)

        self.missing_actions = QHBoxLayout()
        self.btn_select_all_missing = QPushButton(self.tr("Select all missing"))
        self.btn_select_all_missing.setObjectName("SecondaryButton")
        self.btn_select_all_missing.clicked.connect(self._select_all_missing)
        self.missing_actions.addWidget(self.btn_select_all_missing)

        self.btn_restore_missing = QPushButton(self.tr("Restore selected"))
        self.btn_restore_missing.setObjectName("SecondaryButton")
        self.btn_restore_missing.clicked.connect(self._restore_missing)
        self.missing_actions.addWidget(self.btn_restore_missing)

        self.btn_delete_missing = QPushButton(self.tr("Delete from repository"))
        self.btn_delete_missing.setObjectName("SecondaryButton")
        self.btn_delete_missing.clicked.connect(self._delete_missing)
        self.missing_actions.addWidget(self.btn_delete_missing)
        self.missing_actions.addStretch()
        layout.addLayout(self.missing_actions)
        self._set_missing_actions_visible(False)

        self.chk_show_untracked = QCheckBox(self.tr("Show untracked files"))
        self.chk_show_untracked.setChecked(True)
        self.chk_show_untracked.toggled.connect(self._toggle_untracked)
        layout.addWidget(self.chk_show_untracked)

        self.untracked_container = QVBoxLayout()
        self.lbl_untracked = QLabel(
            self.tr("Untracked files (not added unless you select them)")
        )
        self.lbl_untracked.setObjectName("WarningLabel")
        self.untracked_container.addWidget(self.lbl_untracked)

        self.untracked_list = QListWidget()
        self.untracked_list.setObjectName("DataList")
        self.untracked_list.setMaximumHeight(120)
        self.untracked_list.itemChanged.connect(self._on_selection_changed)
        self.untracked_container.addWidget(self.untracked_list)
        layout.addLayout(self.untracked_container)

        self.lbl_checklist = QLabel(self.tr("Tasks completed"))
        self.lbl_checklist.setObjectName("SectionTitle")
        self.lbl_checklist.hide()
        layout.addWidget(self.lbl_checklist)

        self.lbl_checklist_hint = QLabel(
            self.tr(
                "Tick the tasks you finished. Each tick is saved to Kitsu and only "
                "checked items are added to the commit message."
            )
        )
        self.lbl_checklist_hint.setObjectName("HintLabel")
        self.lbl_checklist_hint.setWordWrap(True)
        self.lbl_checklist_hint.hide()
        layout.addWidget(self.lbl_checklist_hint)

        self.checklist_container = QWidget()
        self.checklist_layout = QVBoxLayout(self.checklist_container)
        self.checklist_layout.setContentsMargins(0, 0, 0, 0)
        self.checklist_layout.setSpacing(4)
        self.checklist_container.hide()
        layout.addWidget(self.checklist_container)

        lbl_message = QLabel(self.tr("Commit message"))
        lbl_message.setObjectName("SectionTitle")
        layout.addWidget(lbl_message)

        self.entry_message = QPlainTextEdit()
        self.entry_message.setObjectName("FormInput")
        self.entry_message.setPlaceholderText(self.tr("Describe the published work..."))
        self.entry_message.setFixedHeight(110)
        layout.addWidget(self.entry_message)

        hint = QLabel(
            self.tr(
                "New files are added to version control only when selected. "
                "Only the tasks you tick are included in the commit message."
            )
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("StatusLabel")
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
        missing = [
            change
            for change in self.changes
            if not change.is_unversioned
            and not getattr(change, "is_conflicted", False)
            and getattr(change, "is_missing", change.status == "!")
        ]
        tracked = [
            change
            for change in self.changes
            if not change.is_unversioned
            and not getattr(change, "is_conflicted", False)
            and change not in missing
        ]
        untracked = [change for change in self.changes if change.is_unversioned]

        for change in conflicted:
            item = QListWidgetItem(self._label_for(change))
            item.setData(Qt.UserRole, change)
            self.conflict_list.addItem(item)

        for change in missing:
            item = QListWidgetItem(self._label_for(change))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, change)
            self.missing_list.addItem(item)

        has_missing = bool(missing)
        supports_restore = callable(getattr(self.vm, "restore_vcs_paths", None))
        supports_delete = callable(getattr(self.vm, "schedule_delete_vcs_paths", None))
        self.lbl_missing.setVisible(has_missing)
        self.missing_list.setVisible(has_missing)
        self._set_missing_actions_visible(has_missing)
        self.btn_restore_missing.setVisible(has_missing and supports_restore)
        self.btn_delete_missing.setVisible(has_missing and supports_delete)

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

    @staticmethod
    def _label_for(change) -> str:
        state = STATUS_LABELS.get(change.status, change.status or "Change")
        return f"[{state}]  {change.relative_path}"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def selected_changes(self) -> list:
        selected = []
        for widget in (self.list_widget, self.missing_list, self.untracked_list):
            for index in range(widget.count()):
                item = widget.item(index)
                if item.checkState() == Qt.Checked:
                    selected.append(item.data(Qt.UserRole))
        return selected

    def selected_missing_changes(self) -> list:
        selected = []
        for index in range(self.missing_list.count()):
            item = self.missing_list.item(index)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        return selected

    def _set_missing_actions_visible(self, visible: bool) -> None:
        self.btn_select_all_missing.setVisible(visible)
        self.btn_restore_missing.setVisible(visible)
        self.btn_delete_missing.setVisible(visible)
        self.btn_select_all_missing.setEnabled(visible)
        self.btn_restore_missing.setEnabled(False)
        self.btn_delete_missing.setEnabled(False)

    def _on_missing_selection_changed(self, _item=None) -> None:
        has_selection = bool(self.selected_missing_changes()) and not self._busy
        self.btn_restore_missing.setEnabled(
            has_selection and callable(getattr(self.vm, "restore_vcs_paths", None))
        )
        self.btn_delete_missing.setEnabled(
            has_selection and callable(getattr(self.vm, "schedule_delete_vcs_paths", None))
        )

    def _select_all_missing(self) -> None:
        for index in range(self.missing_list.count()):
            self.missing_list.item(index).setCheckState(Qt.Checked)

    def _restore_missing(self) -> None:
        self._handle_missing_paths(delete=False)

    def _delete_missing(self) -> None:
        self._handle_missing_paths(delete=True)

    def _handle_missing_paths(self, delete: bool) -> None:
        if self._busy:
            return
        selected = self.selected_missing_changes()
        if not selected:
            self._show_status(self.tr("Select at least one missing file."), error=True)
            return

        if delete:
            box = QMessageBox(self)
            box.setWindowTitle(self.tr("Delete from repository"))
            box.setText(
                self.tr(
                    "Schedule {0} file(s) for deletion? The deletion is committed "
                    "when you publish the selected changes."
                ).format(len(selected))
            )
            confirm = box.addButton(self.tr("Schedule deletion"), QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is not confirm:
                return

        handler = (
            getattr(self.vm, "schedule_delete_vcs_paths", None)
            if delete
            else getattr(self.vm, "restore_vcs_paths", None)
        )
        if not callable(handler):
            self._show_status(
                self.tr("This workspace does not support that action."), error=True
            )
            return

        self._set_busy(True)
        self._show_status(
            self.tr("Scheduling the deletions...")
            if delete
            else self.tr("Restoring the missing files...")
        )
        if not handler(self.card, selected):
            self._set_busy(False)

    def _on_vcs_paths_handled(self, task_id: str, success: bool, message: str) -> None:
        if task_id != self.task_id:
            return
        self._set_busy(False)
        if success:
            self._show_status(message)
            self.accept()
        else:
            self._show_status(message, error=True)

    def commit_message(self) -> str:
        return self.entry_message.toPlainText().strip()

    # ------------------------------------------------------------------
    # Task checklist (interactive, persisted to Kitsu)
    # ------------------------------------------------------------------
    def _checklist_supported(self) -> bool:
        return callable(getattr(self.vm, "task_checklist_items", None))

    def _load_checklist(self) -> None:
        if not self._checklist_supported() or self.task_id.startswith("__"):
            return
        getter = getattr(self.vm, "task_checklist_items", None)
        try:
            self._set_checklist_items(list(getter(self.task_id) or []))
        except Exception:  # noqa: BLE001 - the dialog must remain usable
            self._set_checklist_items([])
        refresh = getattr(self.vm, "refresh_task_checklist", None)
        if callable(refresh):
            try:
                refresh(self.card)
            except Exception:  # noqa: BLE001 - a stale list is better than no dialog
                pass

    def _set_checklist_items(self, items: list) -> None:
        self._checklist_items = [dict(item) for item in items or []]
        while self.checklist_layout.count():
            entry = self.checklist_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()
        self._checklist_boxes = {}

        for item in self._checklist_items:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            box = QCheckBox(text)
            box.setChecked(bool(item.get("checked")))
            box.setEnabled(bool(item.get("comment_id")) and not self._checklist_saving)
            box.toggled.connect(
                lambda checked, entry=dict(item): self._on_checklist_toggled(entry, checked)
            )
            self.checklist_layout.addWidget(box)
            self._checklist_boxes[(str(item.get("comment_id") or ""), int(item.get("index", 0)))] = box

        has_items = bool(self._checklist_items)
        self.lbl_checklist.setVisible(has_items)
        self.lbl_checklist_hint.setVisible(has_items)
        self.checklist_container.setVisible(has_items)

    def _checked_checklist_texts(self) -> list[str]:
        texts: list[str] = []
        seen: set[str] = set()
        for item in self._checklist_items:
            if not item.get("checked"):
                continue
            text = str(item.get("text") or "").strip()
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
        return texts

    def _on_checklist_toggled(self, item: dict, checked: bool) -> None:
        if self._checklist_saving or self._busy:
            return
        setter = getattr(self.vm, "set_task_checklist_item", None)
        if not callable(setter):
            return
        started = setter(
            self.task_id,
            str(item.get("comment_id") or ""),
            int(item.get("index", 0)),
            checked,
        )
        if not started:
            self._on_task_checklist_saving(self.task_id, False)

    def _on_task_checklist_ready(self, task_id: str, items: list) -> None:
        if str(task_id) != self.task_id:
            return
        self._set_checklist_items(items)
        self._refresh_auto_message()

    def _on_task_checklist_saving(self, task_id: str, saving: bool) -> None:
        if str(task_id) != self.task_id:
            return
        self._checklist_saving = bool(saving)
        for box in self._checklist_boxes.values():
            box.setEnabled(not saving and not self._busy)
        self.btn_publish.setEnabled(not saving and not self._busy)

    def _build_auto_message(self, file_count: int) -> str:
        message = (
            f"OpenStudioHub: {file_count} file(s) for {self.project_name} "
            f"({self.file_name})."
        )
        checklist = self._checked_checklist_texts()
        if checklist:
            lines = "\n".join(f"- [x] {item}" for item in checklist)
            message += f"\n\nCompleted checklist:\n{lines}"
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
        self.btn_publish.setEnabled(not busy and not self._checklist_saving)
        self.btn_postpone.setEnabled(not busy)
        self.list_widget.setEnabled(not busy)
        self.untracked_list.setEnabled(not busy)
        self.conflict_list.setEnabled(not busy)
        self.btn_resolve_conflict.setEnabled(
            not busy and self.conflict_list.currentItem() is not None
        )
        self.chk_show_untracked.setEnabled(not busy)
        self.entry_message.setEnabled(not busy)
        self.missing_list.setEnabled(not busy)
        self.btn_select_all_missing.setEnabled(not busy and self.missing_list.count() > 0)
        if busy:
            self.btn_restore_missing.setEnabled(False)
            self.btn_delete_missing.setEnabled(False)
        else:
            self._on_missing_selection_changed()
        for box in self._checklist_boxes.values():
            box.setEnabled(not busy and not self._checklist_saving)

    def _show_status(self, message: str, error: bool = False) -> None:
        from src.interfaces.qt.ui_style import set_ui_state

        self.lbl_status.setText(message)
        set_ui_state(self.lbl_status, "error" if error else "success")

    def _publish(self) -> None:
        if self._busy or self._checklist_saving:
            return
        selected = self.selected_changes()
        if not selected:
            self._show_status(self.tr("Select at least one file to publish."), error=True)
            return
        current = self.commit_message()
        if current.strip() == self._auto_message.strip():
            self._refresh_auto_message()
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
        if self._checklist_connected:
            try:
                self.vm.task_checklist_ready.disconnect(self._on_task_checklist_ready)
            except (RuntimeError, TypeError):
                pass
            self._checklist_connected = False
        if self._checklist_saving_connected:
            try:
                self.vm.task_checklist_saving.disconnect(self._on_task_checklist_saving)
            except (RuntimeError, TypeError):
                pass
            self._checklist_saving_connected = False
        if self._paths_connected:
            try:
                self.vm.vcs_paths_handled.disconnect(self._on_vcs_paths_handled)
            except (RuntimeError, TypeError):
                pass
            self._paths_connected = False

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._disconnect()
        super().closeEvent(event)

    def accept(self) -> None:  # noqa: D102 (Qt override)
        self._disconnect()
        super().accept()

    def reject(self) -> None:  # noqa: D102 (Qt override)
        self._disconnect()
        super().reject()
