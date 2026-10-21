# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/vcs_update_dialog.py
# Architectural role: UI View / VCS update cleanup (PySide6)
# =========================================================================================

"""Review dialog for conflicts and obstructions left by a VCS update."""

from __future__ import annotations

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
    "C": "Conflicted",
    "~": "Obstructed",
    "B": "Broken lock",
    "!": "Missing",
}


class VcsUpdateDialog(QDialog):
    def __init__(self, parent, viewmodel, project_id: str, project_root, report) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("VCS Update Needs Attention"))
        self.setObjectName("ViewLoginBase")
        self.setMinimumSize(680, 520)
        self.resize(680, 520)
        self.setSizeGripEnabled(True)
        self.setModal(True)

        self.vm = viewmodel
        self.project_id = str(project_id)
        self.project_root = project_root
        self.message = str(getattr(report, "message", "") or "")
        self.issues = list(getattr(report, "issues", ()) or [])

        self._build_ui()
        self._refresh_list()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(self.tr("VCS Update Needs Attention"))
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        message = QLabel(
            self.message
            or self.tr(
                "The update found local conflicts or obstructing files. "
                "Move them aside or ignore them, then retry the update."
            )
        )
        message.setObjectName("WarningLabel")
        message.setWordWrap(True)
        layout.addWidget(message)

        self.issue_list = QListWidget()
        self.issue_list.setObjectName("DataList")
        self.issue_list.currentItemChanged.connect(self._update_actions)
        layout.addWidget(self.issue_list, stretch=1)

        hint = QLabel(
            self.tr(
                "Move aside keeps a timestamped copy under .openstudio_aside and "
                "unblocks the update. Ignore only hides the path locally. "
                "Conflicts must be resolved from the task's publish window."
            )
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        actions = QHBoxLayout()
        self.btn_move = QPushButton(self.tr("Move aside"))
        self.btn_move.setObjectName("SecondaryButton")
        self.btn_move.clicked.connect(self._move_aside)
        actions.addWidget(self.btn_move)

        self.btn_ignore = QPushButton(self.tr("Ignore"))
        self.btn_ignore.setObjectName("SecondaryButton")
        self.btn_ignore.clicked.connect(self._ignore)
        actions.addWidget(self.btn_ignore)

        self.btn_retry = QPushButton(self.tr("Retry update"))
        self.btn_retry.setObjectName("PrimaryButton")
        self.btn_retry.clicked.connect(self._retry)
        actions.addWidget(self.btn_retry)

        actions.addStretch()
        self.btn_close = QPushButton(self.tr("Close"))
        self.btn_close.setObjectName("SecondaryButton")
        self.btn_close.clicked.connect(self.reject)
        actions.addWidget(self.btn_close)
        layout.addLayout(actions)

        self._update_actions()

    def _refresh_list(self) -> None:
        self.issue_list.clear()
        for issue in self.issues:
            status = STATUS_LABELS.get(issue.status, issue.status or "Issue")
            item = QListWidgetItem(f"[{status}]  {issue.relative_path}")
            item.setData(Qt.UserRole, issue)
            self.issue_list.addItem(item)
        if self.issues:
            self.issue_list.setCurrentRow(0)
            self.lbl_status.setText(
                self.tr("{0} path(s) need attention.").format(len(self.issues))
            )
        else:
            self.lbl_status.setText(
                self.tr("All reported issues have been handled. You can retry the update.")
            )
        self._update_actions()

    def _selected_issue(self):
        item = self.issue_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _update_actions(self, _current=None, _previous=None) -> None:
        issue = self._selected_issue()
        can_cleanup = issue is not None and not getattr(
            issue, "is_conflicted", issue.status == "C"
        )
        self.btn_move.setEnabled(can_cleanup)
        self.btn_ignore.setEnabled(can_cleanup)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _move_aside(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            return
        ok, message = self.vm.move_vcs_path_aside(
            self.project_root, issue.relative_path
        )
        self._show_result(ok, message)
        if ok:
            self._remove_issue(issue)

    def _ignore(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            return
        ok, message = self.vm.ignore_vcs_path(
            self.project_root, issue.relative_path
        )
        self._show_result(ok, message)

    def _retry(self) -> None:
        if self.vm.update_vcs(self.project_id, self.project_root):
            self.accept()

    def _remove_issue(self, issue) -> None:
        self.issues = [candidate for candidate in self.issues if candidate is not issue]
        self._refresh_list()

    def _show_result(self, ok: bool, message: str) -> None:
        from src.interfaces.qt.ui_style import set_ui_state

        self.lbl_status.setText(message)
        set_ui_state(self.lbl_status, "success" if ok else "error")
