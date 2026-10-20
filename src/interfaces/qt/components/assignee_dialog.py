# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/assignee_dialog.py
# Architectural role: UI Component / Multi-select task assignees
# =========================================================================================

"""Searchable multi-select dialog for a task's responsible people."""

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


class AssigneeDialog(QDialog):
    def __init__(self, parent, persons: list, selected_ids=None, title: str = "Responsibles") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(420, 480)
        self._selected = {str(pid) for pid in (selected_ids or [])}
        self._build_ui(persons or [])

    def _build_ui(self, persons: list) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        hint = QLabel(self.tr("Select one or more responsible people."))
        hint.setStyleSheet("color: #94A3B8;")
        layout.addWidget(hint)

        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Search by name or email…"))
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget { background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155;"
            " border-radius: 6px; }"
            "QListWidget::item { padding: 6px; }"
        )
        for person in sorted(
            persons, key=lambda p: str(p.get("full_name") or p.get("email") or "").lower()
        ):
            person_id = str(person.get("id", "") or "")
            if not person_id:
                continue
            name = person.get("full_name") or person.get("email") or person_id
            email = person.get("email") or ""
            label = f"{name}  ({email})" if email and email != name else name
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, person_id)
            item.setData(Qt.UserRole + 1, label.lower())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if person_id in self._selected else Qt.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setObjectName("SecondaryButton")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton(self.tr("Apply"))
        btn_ok.setObjectName("PrimaryButton")
        btn_ok.clicked.connect(self.accept)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_ok)
        layout.addLayout(buttons)

    def _filter(self, text: str) -> None:
        needle = (text or "").strip().lower()
        for index in range(self.list.count()):
            item = self.list.item(index)
            haystack = str(item.data(Qt.UserRole + 1) or item.text().lower())
            item.setHidden(bool(needle) and needle not in haystack)

    def selected_ids(self) -> List[str]:
        selected = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == Qt.Checked:
                selected.append(str(item.data(Qt.UserRole)))
        return selected
