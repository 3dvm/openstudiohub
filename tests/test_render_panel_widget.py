"""Unit tests for the render panel layout and backend visibility."""

from types import SimpleNamespace

import src.interfaces.qt.views  # noqa: F401 - initializes the view/widget import graph
from src.application.services.render_service import RenderService
from src.interfaces.qt.components.collapsible_section import CollapsibleSection
from src.interfaces.qt.viewmodels.render_panel_viewmodel import RenderPanelViewModel
from src.interfaces.qt.widgets.render_panel_widget import RenderPanelWidget


def _widget() -> RenderPanelWidget:
    vm = RenderPanelViewModel(RenderService())
    project_list_vm = SimpleNamespace(_projects=[], refresh=lambda: None)
    return RenderPanelWidget(None, vm, project_list_vm)


def _set_backend(combo, value: str) -> None:
    combo.setCurrentIndex(combo.findData(value))


def test_vast_settings_are_hidden_when_both_backends_are_local(qapp):
    widget = _widget()

    _set_backend(widget.combo_backend, "local")
    _set_backend(widget.combo_preview_backend, "local")

    assert widget.vast_section.isHidden() is True
    widget.deleteLater()


def test_vast_settings_follow_either_backend(qapp):
    widget = _widget()

    _set_backend(widget.combo_backend, "local")
    _set_backend(widget.combo_preview_backend, "vast")
    assert widget.vast_section.isHidden() is False

    _set_backend(widget.combo_preview_backend, "local")
    _set_backend(widget.combo_backend, "vast")
    assert widget.vast_section.isHidden() is False
    widget.deleteLater()


def test_render_settings_are_split_into_final_and_preview_panels(qapp):
    widget = _widget()

    assert widget.combo_backend is not None
    assert widget.combo_preview_backend is not None
    assert widget.final_settings_section.button.text() == "Final render"
    assert widget.preview_settings_section.button.text() == "Preview render"
    widget.deleteLater()


def test_collapsible_section_toggles_its_content(qapp):
    section = CollapsibleSection("Section")
    assert section.is_expanded() is True
    assert section.content.isHidden() is False

    section.button.click()

    assert section.is_expanded() is False
    assert section.content.isHidden() is True
    section.deleteLater()


def test_render_node_card_shows_status_and_log_button(qapp, tmp_path):
    from src.interfaces.qt.components.render_node_card import RenderNodeCard
    from src.interfaces.qt.viewmodels.render_panel_viewmodel import RenderNodeCardModel

    log = tmp_path / "node-0.log"
    log.write_text("done", encoding="utf-8")
    card = RenderNodeCardModel(
        node=0,
        status="completed",
        gpu_name="RTX 4090",
        region="US",
        frames_done=10,
        frames_expected=10,
        hub_logs=(log,),
        final=True,
    )

    widget = RenderNodeCard()
    widget.update_model(card)

    assert "Node 1" in widget.lbl_title.text()
    assert "Completed" in widget.lbl_status.text()
    assert widget.logs_layout.count() == 1
    widget.deleteLater()
