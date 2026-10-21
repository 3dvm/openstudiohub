"""Unit tests for the startup auto-launch of the initial setup wizard."""

from PySide6.QtCore import QObject, Signal

from src.interfaces.qt.views.login_view import ViewLogin


class FakeLoginViewModel(QObject):
    error_message = Signal(str)
    config_state_changed = Signal(bool)
    setup_state_changed = Signal(bool)
    host_set = Signal(str)
    busy_changed = Signal(bool)
    status_message = Signal(str, str)

    def __init__(self, needs_setup: bool = True) -> None:
        super().__init__()
        self.needs_setup = needs_setup

    def load_config_state(self) -> None:
        self.config_state_changed.emit(False)
        self.setup_state_changed.emit(self.needs_setup)


def test_view_login_auto_opens_setup_when_configuration_is_missing(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(ViewLogin, "_open_initial_setup", lambda self: opened.append(True))
    view = ViewLogin(None, FakeLoginViewModel(needs_setup=True))

    qapp.processEvents()

    assert opened == [True]
    assert view.btn_initial_setup.isHidden() is False
    view.deleteLater()


def test_view_login_does_not_auto_open_when_configuration_is_complete(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(ViewLogin, "_open_initial_setup", lambda self: opened.append(True))
    view = ViewLogin(None, FakeLoginViewModel(needs_setup=False))

    qapp.processEvents()

    assert opened == []
    assert view.btn_initial_setup.isHidden() is True
    view.deleteLater()
