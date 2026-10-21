# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/vcs_locks_dialog.py
# Architectural role: UI View / TD lock administration (PySide6)
# =========================================================================================

"""TD dialog for listing and breaking repository locks."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class VcsLocksDialog(QDialog):
    def __init__(self, parent, viewmodel, project_name: str, locks: list) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("VCS Locks"))
        self.setObjectName("ViewLoginBase")
        self.setFixedSize(720, 560)
        self.setModal(True)

        self.vm = viewmodel
        self.project_name = project_name
        self.locks = list(locks or [])
        self._connected = False

        self._build_ui()
        self.vm.vcs_lock_broken.connect(self._on_lock_broken)
        self._connected = True
        self._refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel(self.tr("Repository Locks"))
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            self.tr(
                "Project: {0}. Breaking a lock removes it from the server. "
                "Use it only for stale or abandoned locks."
            ).format(self.project_name)
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #94A3B8;")
        layout.addWidget(subtitle)

        self.lock_list = QListWidget()
        self.lock_list.setStyleSheet(
            "QListWidget { background-color: #0F172A; color: #F8FAFC; "
            "border: 1px solid #334155; border-radius: 8px; }"
        )
        self.lock_list.currentItemChanged.connect(self._update_actions)
        layout.addWidget(self.lock_list, stretch=1)

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: #94A3B8; font-size: 11px;")
        layout.addWidget(self.detail)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        actions = QHBoxLayout()
        self.btn_break = QPushButton(self.tr("Break selected lock"))
        self.btn_break.setObjectName("SecondaryButton")
        self.btn_break.clicked.connect(self._break_lock)
        actions.addWidget(self.btn_break)
        actions.addStretch()
        self.btn_close = QPushButton(self.tr("Close"))
        self.btn_close.setObjectName("PrimaryButton")
        self.btn_close.clicked.connect(self.accept)
        actions.addWidget(self.btn_close)
        layout.addLayout(actions)

        self._update_actions()

    def _refresh(self) -> None:
        self.lock_list.clear()
        for lock in self.locks:
            path = str(lock.get("path", ""))
            owner = str(lock.get("owner", "") or "unknown")
            item = QListWidgetItem(f"{path}\nLocked by {owner}")
            item.setData(Qt.UserRole, lock)
            self.lock_list.addItem(item)
        if self.locks:
            self.lock_list.setCurrentRow(0)
            self.lbl_status.setText(
                self.tr("{0} lock(s) found.").format(len(self.locks))
            )
        else:
            self.lbl_status.setText(self.tr("No locks were found in this repository."))
        self._update_actions()

    def _selected_lock(self):
        item = self.lock_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _update_actions(self, _current=None, _previous=None) -> None:
        lock = self._selected_lock()
        self.btn_break.setEnabled(lock is not None)
        if lock is None:
            self.detail.setText("")
            return
        lines = [
            self.tr("Path: {0}").format(lock.get("path", "")),
            self.tr("Owner: {0}").format(lock.get("owner", "") or "unknown"),
            self.tr("Created: {0}").format(lock.get("created", "") or "unknown"),
        ]
        if lock.get("comment"):
            lines.append(self.tr("Comment: {0}").format(lock.get("comment", "")))
        self.detail.setText("\n".join(lines))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _break_lock(self) -> None:
        lock = self._selected_lock()
        if lock is None:
            return
        path = str(lock.get("path", ""))
        answer = QMessageBox.question(
            self,
            self.tr("Break Lock"),
            self.tr(
                "Break the lock on '{0}'?\n\n"
                "The owner will no longer be able to commit until they lock again."
            ).format(path),
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.btn_break.setEnabled(False)
        self.lbl_status.setText(self.tr("Removing the lock..."))
        if not self.vm.break_vcs_lock(self.project_name, path):
            self.btn_break.setEnabled(True)
            self.lbl_status.setText(self.tr("Could not start the lock removal."))

    def _on_lock_broken(
        self, project_name: str, path: str, ok: bool, message: str
    ) -> None:
        if project_name != self.project_name:
            return
        if ok:
            self.locks = [lock for lock in self.locks if str(lock.get("path", "")) != path]
            self._refresh()
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet(
            "color: #10B981; font-weight: bold;"
            if ok
            else "color: #EF4444; font-weight: bold;"
        )

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------
    def _disconnect(self) -> None:
        if not self._connected:
            return
        try:
            self.vm.vcs_lock_broken.disconnect(self._on_lock_broken)
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
