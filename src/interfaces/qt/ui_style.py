# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/ui_style.py
# Architectural role: UI consistency / dynamic style properties
# =========================================================================================

"""Helpers for QSS-driven dynamic states."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


def set_ui_state(widget: QWidget, state: str) -> None:
    """Set a QSS ``state`` property (success, warning, error, or empty)."""
    widget.setProperty("state", state or "")
    _repolish(widget)


def set_ui_role(widget: QWidget, role: str) -> None:
    """Set a generic QSS ``role`` property."""
    widget.setProperty("role", role or "")
    _repolish(widget)


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()
