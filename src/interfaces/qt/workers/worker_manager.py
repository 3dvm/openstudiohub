# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/worker_manager.py
# Architectural role: MVVM / centralized Qt worker lifecycle
# =========================================================================================

"""Centralized owner-side worker lifecycle.

Replaces the repeated per-ViewModel pattern of a ``self._worker`` attribute plus
a hand-written ``_on_*_worker_finished`` slot. The manager:

* keeps a strong reference (backed by the global keep-alive registry),
* optionally refuses to start a new worker while the previous one is running,
* ``deleteLater``s the worker and clears the slot when it finishes,
* exposes ``is_running`` / ``active`` / ``shutdown`` for status and teardown.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QThread

from src.infrastructure.qt_worker import keep_worker_alive


class WorkerManager(QObject):
    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._workers: Dict[str, QThread] = {}

    def start(
        self,
        key: str,
        worker: QThread,
        *,
        skip_if_running: bool = True,
        on_finished: Optional[Callable[[], None]] = None,
        critical: bool = False,
    ) -> bool:
        """Start ``worker`` under ``key``.

        Returns ``False`` (and does not start) when a worker with the same key is
        already running and ``skip_if_running`` is set. ``critical`` marks
        long-running, data-mutating operations the shell must not interrupt by
        closing.
        """
        current = self._workers.get(key)
        if current is not None and self._is_running(current):
            if skip_if_running:
                return False

        try:
            worker._critical = critical
        except Exception:  # noqa: BLE001
            pass

        self._workers[key] = worker
        if on_finished is not None:
            worker.finished.connect(on_finished)
        worker.finished.connect(lambda k=key, w=worker: self._on_finished(k, w))
        keep_worker_alive(worker, critical=critical)
        worker.start()
        return True

    def _on_finished(self, key: str, worker: QThread) -> None:
        if self._workers.get(key) is worker:
            self._workers[key] = None
        try:
            worker.deleteLater()
        except RuntimeError:
            pass

    def get(self, key: str) -> Optional[QThread]:
        return self._workers.get(key)

    def is_running(self, key: str) -> bool:
        worker = self._workers.get(key)
        return worker is not None and self._is_running(worker)

    def active(self) -> List[QThread]:
        return [w for w in self._workers.values() if w is not None and self._is_running(w)]

    def shutdown(self, timeout_ms: int = 0) -> None:
        """Best-effort wait for every owned worker to finish."""
        for worker in list(self._workers.values()):
            if worker is None:
                continue
            try:
                worker.wait(timeout_ms)
            except RuntimeError:
                continue

    @staticmethod
    def _is_running(worker: QThread) -> bool:
        try:
            return worker.isRunning()
        except RuntimeError:
            return False
