"""Shared pytest fixtures."""

import gc

import pytest


@pytest.fixture(autouse=True)
def _isolate_ssh_logs(monkeypatch, tmp_path):
    """Redirect always-on SSH diagnostics and user state out of the real home."""
    monkeypatch.setenv("OPENSTUDIO_LOG_DIR", str(tmp_path / "openstudio_logs"))
    monkeypatch.setenv("OPENSTUDIO_STATE_DIR", str(tmp_path / "openstudio_state"))


@pytest.fixture(autouse=True)
def _flush_qt_deletions():
    """Flush ``deleteLater`` widgets and Python cycles while Qt is still alive.

    Without this, widgets created by a test can survive until interpreter
    shutdown; PySide6 then destroys them after ``QApplication`` is gone and the
    process can segfault while exiting.
    """
    yield
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in list(app.topLevelWidgets()):
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            continue
    app.processEvents()
    gc.collect()
    app.processEvents()
