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


def test_shot_review_card_shows_counts_and_actions(qapp):
    from src.interfaces.qt.components.shot_review_card import ShotReviewCard
    from src.interfaces.qt.viewmodels.render_panel_viewmodel import ShotReviewModel

    model = ShotReviewModel(
        name="sh010",
        sequence="sq010",
        status="with_renders",
        status_label="With renders",
        status_tooltip="Some frames are rendered.",
        selected=True,
        locked=False,
        ready=True,
        frames=140,
        rendered=120,
        approved=80,
        missing=20,
        frame_range="101–240 (step 1)",
        engine="CYCLES",
        resolution="1920×1080 (100%)",
        samples=256,
        image_format="PNG",
        measured_seconds=40.5,
        warnings=(),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
    )
    card = ShotReviewCard()
    card.update_model(model)

    assert "R 120/140" in card.lbl_progress.text()
    assert "A 80/140" in card.lbl_progress.text()
    assert card.lbl_status.toolTip() == "Some frames are rendered."
    assert card.check.isChecked() is True
    assert card.btn_view.isEnabled() is True
    assert card.btn_retry.isEnabled() is True
    card.deleteLater()


def test_final_image_format_controls_update_render_settings(qapp):
    widget = _widget()

    index = widget.combo_image_format.findData("OPEN_EXR")
    widget.combo_image_format.setCurrentIndex(index)
    widget.combo_color_mode.setCurrentText("RGBA")
    widget.combo_color_depth.setCurrentText("32")
    settings = widget._settings_from_ui()

    assert settings.final_quality.file_format == "OPEN_EXR"
    assert settings.final_quality.color_mode == "RGBA"
    assert settings.final_quality.color_depth == "32"
    assert settings.preview_quality.file_format == "PNG"
    widget.deleteLater()


def test_open_output_folder_is_re_enabled_after_busy(qapp):
    from src.interfaces.qt.components.shot_review_card import ShotReviewCard
    from src.interfaces.qt.viewmodels.render_panel_viewmodel import ShotReviewModel

    model = ShotReviewModel(
        name="sh010",
        sequence="sq010",
        status="rendering",
        status_label="Rendering",
        status_tooltip="",
        selected=True,
        locked=True,
        ready=True,
        frames=10,
        rendered=4,
        approved=0,
        missing=6,
        frame_range="101–110 (step 1)",
        engine="CYCLES",
        resolution="1920×1080 (100%)",
        samples=128,
        image_format="PNG",
        measured_seconds=None,
        warnings=(),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
    )
    card = ShotReviewCard()
    card.update_model(model)
    action = next(
        item for item in card.menu.actions() if item.text() == "Open output folder"
    )
    assert action.isEnabled()

    card.set_busy(True)
    assert not action.isEnabled()
    card.set_busy(False)
    assert action.isEnabled()
    card.deleteLater()


def test_preview_poster_offers_play_only_with_a_sequence(qapp, tmp_path):
    from src.interfaces.qt.components.preview_poster import PreviewPoster

    poster = PreviewPoster()
    image = tmp_path / "preview.png"
    image.write_bytes(b"x")
    poster.set_state(preview_path=image, has_sequence=False)
    assert poster.btn_play.isHidden() is True

    poster.set_state(fallback_frame=image, has_sequence=True)
    assert poster.btn_play.isHidden() is False
    assert poster.btn_play.isEnabled() is True
    poster.deleteLater()
