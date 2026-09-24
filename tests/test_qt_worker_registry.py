"""Unit tests for the Qt worker keep-alive / critical registry."""

import threading

from PySide6.QtCore import QThread

from src.infrastructure.qt_worker import (
    active_critical_workers,
    active_workers,
    keep_worker_alive,
)
from src.interfaces.qt.workers.worker_manager import WorkerManager


class _BlockingWorker(QThread):
    def __init__(self, gate: threading.Event) -> None:
        super().__init__()
        self._gate = gate

    def run(self) -> None:  # noqa: D102
        self._gate.wait(3)


def test_critical_worker_is_tracked_and_released(qapp):
    gate = threading.Event()
    worker = _BlockingWorker(gate)
    keep_worker_alive(worker, critical=True)
    worker.start()
    try:
        assert worker in active_workers()
        assert worker in active_critical_workers()
    finally:
        gate.set()
        worker.wait(3000)

    assert worker not in active_critical_workers()


def test_non_critical_worker_not_in_critical_registry(qapp):
    gate = threading.Event()
    worker = _BlockingWorker(gate)
    keep_worker_alive(worker, critical=False)
    worker.start()
    try:
        assert worker in active_workers()
        assert worker not in active_critical_workers()
    finally:
        gate.set()
        worker.wait(3000)


def test_worker_manager_marks_worker_critical(qapp):
    gate = threading.Event()
    worker = _BlockingWorker(gate)
    manager = WorkerManager()
    assert manager.start("op", worker, critical=True) is True
    try:
        assert worker in active_critical_workers()
    finally:
        gate.set()
        worker.wait(3000)
