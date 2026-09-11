# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/base_viewmodel.py
# Architectural role: MVVM base (state + signals, no widgets)
# =========================================================================================

"""Base building blocks for the MVVM presentation layer.

A ``ViewModel`` is a pure ``QObject``: it owns application state, orchestrates
use cases through the application services, and communicates with the View
exclusively via native PySide6 signals. It never imports or touches widgets.

A ``StatusSink`` is a tiny shared channel so nested ViewModels can report
status messages that the shell routes to the single global status bar.
"""

from PySide6.QtCore import QObject, Signal


class StatusSink(QObject):
    """Shared channel that aggregates status messages from many ViewModels."""

    message = Signal(str, str)

    def emit_status(self, message: str, color: str = "white") -> None:
        self.message.emit(message, color)


class BaseViewModel(QObject):
    """Common signal surface for every ViewModel in the application."""

    status_message = Signal(str, str)
    busy_changed = Signal(bool)

    def __init__(self, status_sink: StatusSink | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._status_sink = status_sink or StatusSink()
        self._status_sink.message.connect(self.status_message)
        self._busy = False

    def report_status(self, message: str, color: str = "white") -> None:
        """Publish a status message through the shared sink."""
        self._status_sink.message.emit(message, color)

    def set_busy(self, busy: bool) -> None:
        if self._busy == busy:
            return
        self._busy = busy
        self.busy_changed.emit(busy)
