# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/worker_keepalive.py
# Architectural role: UI worker lifecycle guard
# =========================================================================================

"""Keeps short-lived ``QThread`` workers alive until they finish.

Python garbage-collecting a running ``QThread`` triggers
``QThread: Destroyed while thread '' is still running`` and aborts the whole
process. Widgets that own a worker can be destroyed before the worker finishes
(for example, a responsive grid rebuilding its cards), which drops the only
Python reference to the thread.

``keep_worker_alive`` stores a strong reference in a module-level registry and
releases it when the thread emits ``finished``. This decouples the worker's
lifetime from the widget that created it, so the widget can be safely destroyed
while the background operation completes.
"""

import functools
import weakref
from typing import Set

_ACTIVE: Set[object] = set()


def keep_worker_alive(worker) -> None:
    """Hold ``worker`` in memory until it emits ``finished``."""
    _ACTIVE.add(worker)
    worker.finished.connect(functools.partial(_release, weakref.ref(worker)))


def _release(worker_ref) -> None:
    worker = worker_ref()
    if worker is not None:
        _ACTIVE.discard(worker)
