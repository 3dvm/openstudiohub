# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/creation_error_dialog.py
# Architectural role: UI View / Recovery Dialog (PySide6)
# =========================================================================================

"""Small recovery dialog shown when project creation fails.

Offers the user a retry (resume the failed step), a rollback (delete the data
already created) or a way back to the creation form when nothing was written.
"""

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.application.services.creation_saga import CreationOutcome


class CreationErrorAction(Enum):
    RETRY = "retry"
    ROLLBACK = "rollback"
    BACK = "back"


class CreationErrorDialog(QDialog):
    def __init__(self, parent: QWidget, outcome: CreationOutcome) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Project Creation Failed"))
        self.setModal(True)
        self.setMinimumWidth(460)
        self.action = CreationErrorAction.BACK
        self._build_ui(outcome)

    def _build_ui(self, outcome: CreationOutcome) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel(self.tr("We could not finish creating the project"))
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        message = QLabel(outcome.message or self.tr("Unknown error."))
        message.setWordWrap(True)
        message.setStyleSheet("color: #F8FAFC;")
        message.setMinimumHeight(50)
        message.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(message)

        if outcome.has_side_effects:
            hint_text = self.tr(
                "Data was already created (Kitsu project and/or workspace). "
                "You can retry the failed step or delete the created data."
            )
        else:
            hint_text = self.tr("No project data has been created yet.")
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        if outcome.can_retry:
            btn_retry = QPushButton(self.tr("Retry"))
            btn_retry.setObjectName("PrimaryButton")
            btn_retry.setFixedHeight(38)
            btn_retry.setCursor(Qt.PointingHandCursor)
            btn_retry.clicked.connect(lambda: self._choose(CreationErrorAction.RETRY))
            btn_row.addWidget(btn_retry)

        if outcome.can_rollback and outcome.has_side_effects:
            btn_delete = QPushButton(self.tr("Delete created data"))
            btn_delete.setFixedHeight(38)
            btn_delete.setCursor(Qt.PointingHandCursor)
            btn_delete.setStyleSheet(
                "QPushButton { background-color: #7F1D1D; color: #FEE2E2; "
                "border: 1px solid #B91C1C; border-radius: 6px; padding: 6px 14px; font-weight: bold; } "
                "QPushButton:hover { background-color: #991B1B; }"
            )
            btn_delete.clicked.connect(lambda: self._choose(CreationErrorAction.ROLLBACK))
            btn_row.addWidget(btn_delete)

        # A way back is always available when nothing was written, and as a last
        # resort if no recovery action is offered.
        if not outcome.has_side_effects or (not outcome.can_retry and not outcome.can_rollback):
            btn_back = QPushButton(self.tr("Back to creation"))
            btn_back.setObjectName("SecondaryButton")
            btn_back.setFixedHeight(38)
            btn_back.setCursor(Qt.PointingHandCursor)
            btn_back.clicked.connect(lambda: self._choose(CreationErrorAction.BACK))
            btn_row.addWidget(btn_back)

        layout.addLayout(btn_row)

    def _choose(self, action: CreationErrorAction) -> None:
        self.action = action
        self.accept()
