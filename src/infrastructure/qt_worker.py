# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/qt_worker.py
# Architectural role: Qt worker lifecycle guard (base class + registry)
# =========================================================================================

"""Shared lifetime management for every ``QThread`` worker in the app.

Python garbage-collecting a running ``QThread`` triggers
``QThread: Destroyed while thread '' is still running`` and aborts the whole
process. This happens whenever the only Python reference to a worker is dropped
while it is still running (an owner attribute is overwritten, a widget/card is
destroyed, ...).

Rather than relying on every call site to remember ``keep_worker_alive``,
worker classes inherit from :class:`ManagedWorker`, which registers itself in a
module-level registry on :meth:`start` and is released when it emits
``finished``. This makes the guard automatic and impossible to forget.
"""

from __future__ import annotations

import functools
import weakref
from typing import List, Set

from PySide6.QtCore import QThread

_ACTIVE: Set[object] = set()


def keep_worker_alive(worker) -> None:
    """Hold ``worker`` in memory until it emits ``finished``.

    Idempotent: calling it more than once for the same worker is a no-op.
    """
    if getattr(worker, "_keepalive_registered", False):
        return

    try:
        worker._keepalive_registered = True
    except Exception:  # noqa: BLE001 - exotic wrappers may reject attributes
        pass

    _ACTIVE.add(worker)
    worker.finished.connect(functools.partial(_release, weakref.ref(worker)))


def _release(worker_ref) -> None:
    worker = worker_ref()
    if worker is not None:
        _ACTIVE.discard(worker)


def active_workers() -> List[object]:
    """Return the registered workers that are still running."""
    running = []
    for worker in list(_ACTIVE):
        try:
            if worker.isRunning():
                running.append(worker)
        except RuntimeError:
            # The underlying C++ object was already deleted by Qt.
            _ACTIVE.discard(worker)
    return running


def wait_for_all(timeout_ms: int = 3000) -> None:
    """Best-effort wait for every registered worker to finish."""
    for worker in list(_ACTIVE):
        try:
            worker.wait(timeout_ms)
        except RuntimeError:
            _ACTIVE.discard(worker)


class ManagedWorker(QThread):
    """Base ``QThread`` that can never be garbage-collected while running."""

    def start(self, *args, **kwargs) -> None:  # noqa: D102 (Qt override)
        keep_worker_alive(self)
        super().start(*args, **kwargs)
