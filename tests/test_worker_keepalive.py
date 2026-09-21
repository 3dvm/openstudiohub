"""Unit tests for the QThread keep-alive registry."""

import gc
import time

from PySide6.QtCore import QThread

from src.infrastructure.qt_worker import ManagedWorker
from src.interfaces.qt.workers import worker_keepalive as wk
from src.interfaces.qt.workers.worker_manager import WorkerManager


class SlowWorker(QThread):
    def run(self) -> None:
        time.sleep(0.05)


class AutoWorker(ManagedWorker):
    def run(self) -> None:
        time.sleep(0.05)


def test_worker_is_kept_alive_until_finished(qapp):
    worker = SlowWorker()
    wk.keep_worker_alive(worker)
    worker.start()

    assert worker in wk._ACTIVE

    # Drop the caller's reference and force GC: the registry must keep it alive.
    del worker
    gc.collect()

    held = next(iter(wk._ACTIVE))
    assert held.isRunning()

    held.wait(3000)
    qapp.processEvents()

    assert len(wk._ACTIVE) == 0


def test_managed_worker_registers_on_start(qapp):
    worker = AutoWorker()
    worker.start()

    assert worker in wk._ACTIVE

    del worker
    gc.collect()

    held = next(iter(wk._ACTIVE))
    assert held.isRunning()

    held.wait(3000)
    qapp.processEvents()

    assert len(wk._ACTIVE) == 0


def test_keep_worker_alive_is_idempotent(qapp):
    worker = SlowWorker()
    wk.keep_worker_alive(worker)
    wk.keep_worker_alive(worker)
    worker.start()

    worker.wait(3000)
    qapp.processEvents()

    assert len(wk._ACTIVE) == 0


def test_worker_manager_cleans_up_after_finish(qapp):
    manager = WorkerManager()
    worker = AutoWorker()

    assert manager.start("k", worker) is True
    assert manager.is_running("k") is True

    worker.wait(3000)
    qapp.processEvents()
    qapp.processEvents()

    assert manager.get("k") is None
