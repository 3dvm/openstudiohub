# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/worker_keepalive.py
# Architectural role: UI worker lifecycle guard (compatibility shim)
# =========================================================================================

"""Backward-compatible re-export of the shared Qt worker lifecycle guard.

The implementation now lives in :mod:`src.infrastructure.qt_worker` so that both
the interface and infrastructure layers can use it without a dependency
inversion. New worker classes should inherit from ``ManagedWorker`` instead of
calling ``keep_worker_alive`` manually.
"""

from src.infrastructure.qt_worker import (  # noqa: F401
    _ACTIVE,
    _release,
    ManagedWorker,
    active_workers,
    keep_worker_alive,
    wait_for_all,
)

__all__ = [
    "ManagedWorker",
    "keep_worker_alive",
    "active_workers",
    "wait_for_all",
]
