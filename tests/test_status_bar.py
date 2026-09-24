"""Unit tests for the status bar progress indicator."""

from src.interfaces.qt.components.status_bar import StatusBar


def test_progress_shows_value_and_clears(qapp):
    bar = StatusBar()

    bar.set_progress(42)
    assert bar.progress_bar.isHidden() is False
    assert bar.progress_bar.value() == 42
    assert bar.progress_bar.maximum() == 100

    bar.set_progress(-1)
    assert bar.progress_bar.isHidden() is True


def test_progress_indeterminate_mode(qapp):
    bar = StatusBar()

    bar.set_progress(-2)
    assert bar.progress_bar.isHidden() is False
    assert bar.progress_bar.minimum() == 0
    assert bar.progress_bar.maximum() == 0
