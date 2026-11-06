# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/collapsible_section.py
# Architectural role: UI component / collapsible card section
# =========================================================================================

"""Reusable collapsible section used by dense dashboard panels."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CollapsibleSection(QFrame):
    """Card-like section with a clickable title that shows or hides its content."""

    def __init__(self, title: str, parent=None, *, expanded: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("CardFrame")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        self.button = QToolButton(self)
        self.button.setObjectName("SectionToggle")
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setChecked(expanded)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.button.clicked.connect(self._sync_state)
        outer.addWidget(self.button)

        self.content = QWidget(self)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        outer.addWidget(self.content)

        self._sync_state(expanded)

    def add_widget(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.content_layout.addLayout(layout)

    def set_expanded(self, expanded: bool) -> None:
        self.button.setChecked(bool(expanded))
        self._sync_state()

    def is_expanded(self) -> bool:
        return self.button.isChecked()

    def _sync_state(self, _checked=None) -> None:
        expanded = self.button.isChecked()
        self.button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)
