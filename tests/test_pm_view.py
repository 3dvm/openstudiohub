"""Regression test for the PM dashboard's production service wiring."""

from types import SimpleNamespace

from PySide6.QtWidgets import QWidget

# Import the views package first: the widgets package has an eager import cycle.
import src.interfaces.qt.views  # noqa: F401
import src.interfaces.qt.views.pm_view as pm_mod


class FakeAuth:
    current_user = SimpleNamespace(id="u1", first_name="Ada")

    def current_role(self):
        return SimpleNamespace(label="Manager", value="manager")


class FakeConfig:
    def get_studio_name(self):
        return "Test Studio"


def _patch_heavy_widgets(monkeypatch):
    def fake_project_list(*_args, **_kwargs):
        widget = QWidget()
        widget.refresh = lambda: None
        return widget

    monkeypatch.setattr(pm_mod, "ProjectListWidget", fake_project_list)
    monkeypatch.setattr(pm_mod, "TaskBoardWidget", lambda *a, **k: QWidget())
    monkeypatch.setattr(pm_mod, "BlendBuilderWidget", lambda *a, **k: QWidget())


def _make_view(monkeypatch, production_service):
    fallback = object()
    project_list_vm = SimpleNamespace(production_service=fallback)
    view = pm_mod.ViewPM(
        parent=None,
        project_list_vm=project_list_vm,
        blend_builder_vm=object(),
        audit_vm=object(),
        repair_vm=object(),
        auth_service=FakeAuth(),
        config_factory=FakeConfig(),
        production_service=production_service,
        on_logout=lambda: None,
    )
    return view, fallback


def test_viewpm_uses_explicit_production_service(qapp, monkeypatch):
    _patch_heavy_widgets(monkeypatch)
    service = object()

    view, _fallback = _make_view(monkeypatch, service)

    assert view.production_service is service
    assert view.task_board_vm.production_service is service


def test_viewpm_falls_back_to_project_list_service(qapp, monkeypatch):
    _patch_heavy_widgets(monkeypatch)

    view, fallback = _make_view(monkeypatch, None)

    assert view.production_service is fallback
    assert view.task_board_vm.production_service is fallback
