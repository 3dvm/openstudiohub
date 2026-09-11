"""Unit tests for the QThread keep-alive registry."""

import gc
import time

from PySide6.QtCore import QThread

from src.interfaces.qt.workers import worker_keepalive as wk


class SlowWorker(QThread):
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
