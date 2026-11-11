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


def test_preview_frame_spin_tracks_the_selected_shot(qapp):
    from pathlib import Path

    from src.domain.render.models import RenderQuality, RenderShot

    widget = _widget()
    shot = RenderShot(
        name="sh010",
        blend_path=Path("/project/sh010.blend"),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=128),
        frame_start=101,
        frame_end=196,
        object_count=20,
        mesh_count=10,
        has_camera=True,
    )
    widget._shots = [shot]

    widget._select_shot(shot.relative_path)
    assert widget.spin_preview_frame.minimum() == 101
    assert widget.spin_preview_frame.maximum() == 196
    assert widget.spin_preview_frame.value() == 148

    widget.spin_preview_frame.setValue(120)
    assert widget.vm.settings.preview_frame_for(shot.relative_path) == 120
    widget.deleteLater()


def test_preview_dialog_uses_the_preview_backend(qapp, monkeypatch):
    from pathlib import Path

    from PySide6.QtWidgets import QMessageBox

    from src.domain.render.models import RenderQuality, RenderSettings, RenderShot

    widget = _widget()
    shot = RenderShot(
        name="sh010",
        blend_path=Path("/project/sh010.blend"),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=128),
        frame_start=101,
        frame_end=196,
        object_count=20,
        mesh_count=10,
        has_camera=True,
    )
    widget._shots = [shot]
    widget._selected_shot = shot
    widget.vm.shots = [shot]
    widget.vm.settings = RenderSettings(
        render_backend="vast",
        preview_backend="vast",
        selected_shots=(shot.relative_path,),
    )
    _set_backend(widget.combo_preview_backend, "local")
    texts = []
    previews = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: texts.append(args[2]) or QMessageBox.Yes,
    )
    monkeypatch.setattr(
        widget.vm,
        "preview_shots",
        lambda shots: previews.append(shots) or True,
    )

    widget._preview_all()

    assert widget.vm.settings.preview_backend == "local"
    assert widget.vm.settings.render_backend == "vast"
    assert texts and "locally" in texts[0]
    assert "Vast.ai" not in texts[0]
    assert previews == [[shot]]
    widget.deleteLater()


def test_preview_dialog_reports_vast_for_the_vast_preview_backend(qapp, monkeypatch):
    from pathlib import Path

    from PySide6.QtWidgets import QMessageBox

    from src.domain.render.models import RenderQuality, RenderSettings, RenderShot

    widget = _widget()
    shot = RenderShot(
        name="sh010",
        blend_path=Path("/project/sh010.blend"),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=128),
        frame_start=101,
        frame_end=196,
        object_count=20,
        mesh_count=10,
        has_camera=True,
    )
    widget._shots = [shot]
    widget._selected_shot = shot
    widget.vm.shots = [shot]
    widget.vm.settings = RenderSettings(
        render_backend="local",
        preview_backend="local",
        selected_shots=(shot.relative_path,),
    )
    _set_backend(widget.combo_preview_backend, "vast")
    texts = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: texts.append(args[2]) or QMessageBox.Yes,
    )
    monkeypatch.setattr(widget.vm, "preview_shots", lambda shots: True)

    widget._preview_all()

    assert widget.vm.settings.preview_backend == "vast"
    assert widget.vm.settings.render_backend == "local"
    assert texts and "Vast.ai" in texts[0]
    widget.deleteLater()


def test_final_backend_combo_recalculates_the_plan(qapp, monkeypatch):
    widget = _widget()
    calls = []
    monkeypatch.setattr(
        widget.vm,
        "set_render_backend",
        lambda backend, settings=None: calls.append(backend),
    )

    _set_backend(widget.combo_backend, "local")
    _set_backend(widget.combo_backend, "vast")

    assert calls == ["local", "vast"]
    widget.deleteLater()


def _approval_widget(tmp_path):
    from pathlib import Path

    from src.domain.render.models import RenderQuality, RenderShot

    widget = _widget()
    shot = RenderShot(
        name="sh010",
        blend_path=Path("/project/sh010.blend"),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=128),
        frame_start=101,
        frame_end=101,
        object_count=20,
        mesh_count=10,
        has_camera=True,
    )
    frame = tmp_path / "frame_0101.png"
    frame.write_bytes(b"x")
    widget._shots = [shot]
    widget._selected_shot = shot
    widget._player_shot_path = shot.relative_path
    widget.player.set_sequence([(101, frame)], fps=24, autoplay=False)
    return widget, shot


def test_player_approve_refreshes_badge_and_buttons(qapp, tmp_path, monkeypatch):
    widget, shot = _approval_widget(tmp_path)
    monkeypatch.setattr(
        widget.vm,
        "approve_frames",
        lambda *args, **kwargs: (True, "1 frame(s) approved."),
    )
    monkeypatch.setattr(widget.vm, "approved_frames", lambda _shot: {101})

    widget._approve_frames([101], True)

    assert "Approved" in widget.player.lbl_badge.text()
    assert widget.player.btn_unapprove_selection.isEnabled() is True
    widget.deleteLater()


def test_approve_all_refreshes_the_open_player(qapp, tmp_path, monkeypatch):
    widget, shot = _approval_widget(tmp_path)
    monkeypatch.setattr(
        widget.vm,
        "approve_all_rendered",
        lambda _shot: (True, "1 frame(s) approved."),
    )
    monkeypatch.setattr(widget.vm, "approved_frames", lambda _shot: {101})

    widget._on_shot_action(shot.relative_path, "approve_all")

    assert "Approved" in widget.player.lbl_badge.text()
    assert widget.player.btn_unapprove_selection.isEnabled() is True
    widget.deleteLater()


def test_render_node_card_eta_uses_adaptive_duration(qapp):
    from src.interfaces.qt.components.render_node_card import RenderNodeCard
    from src.interfaces.qt.viewmodels.render_panel_viewmodel import RenderNodeCardModel

    widget = RenderNodeCard()
    widget.update_model(
        RenderNodeCardModel(
            node=0,
            status="rendering",
            frames_done=1,
            frames_expected=10,
            eta_seconds=3661,
        )
    )
    assert widget.lbl_eta.text() == "~1h 1m 1s remaining"

    widget.update_model(
        RenderNodeCardModel(
            node=0,
            status="rendering",
            frames_done=1,
            frames_expected=10,
            eta_seconds=45,
        )
    )
    assert widget.lbl_eta.text() == "~45s remaining"

    widget.update_model(
        RenderNodeCardModel(
            node=0,
            status="rendering",
            frames_done=1,
            frames_expected=10,
            eta_seconds=8 * 86400 + 3600,
        )
    )
    assert widget.lbl_eta.text() == "~1w 1d 1h remaining"
    widget.deleteLater()


def test_target_wall_time_uses_adaptive_duration(qapp):
    widget = _widget()

    assert widget.combo_target.itemText(0) == "1h"
    assert widget.combo_target.itemText(1) == "2h"

    widget.spin_hours.setValue(1.5)
    assert widget.lbl_target_duration.text() == "1h 30m"

    widget.spin_hours.setValue(0.25)
    assert widget.lbl_target_duration.text() == "15m"

    widget.spin_hours.setValue(30)
    assert widget.lbl_target_duration.text() == "1d 6h"
    widget.deleteLater()


def test_preview_section_only_keeps_the_all_buttons(qapp):
    widget = _widget()

    assert hasattr(widget, "btn_preview_all")
    assert hasattr(widget, "btn_benchmark_all")
    assert not hasattr(widget, "btn_preview_selected")
    assert not hasattr(widget, "btn_benchmark")
    assert not hasattr(widget, "btn_play_final")
    widget.deleteLater()


def test_benchmark_all_lists_the_frames_and_starts_one_batch(qapp, monkeypatch):
    from pathlib import Path

    from PySide6.QtWidgets import QMessageBox

    from src.domain.render.models import RenderQuality, RenderSettings, RenderShot

    widget = _widget()
    shot = RenderShot(
        name="sh010",
        blend_path=Path("/project/sh010.blend"),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=128),
        frame_start=101,
        frame_end=196,
        object_count=20,
        mesh_count=10,
        has_camera=True,
        task_type="layout",
    )
    widget.vm.shots = [shot]
    widget.vm.settings = RenderSettings(
        selected_shots=(shot.relative_path,), render_backend="local"
    )
    estimate = SimpleNamespace(
        shots=((shot, SimpleNamespace(frames=(101, 148, 196))),),
        frames=3,
        staging=SimpleNamespace(bytes=1_000, files=10, entries=()),
        plan=SimpleNamespace(estimated_cost=0.05),
    )
    monkeypatch.setattr(
        widget.vm, "benchmark_batch_estimate", lambda shots=None: estimate
    )
    started = []
    monkeypatch.setattr(
        widget.vm,
        "benchmark_shots",
        lambda shots, overwrite=False: started.append((shots, overwrite)) or True,
    )
    texts = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: texts.append(args[2]) or QMessageBox.Yes,
    )

    widget._benchmark_all()

    assert texts
    assert "sh010" in texts[0]
    assert "101, 148, 196" in texts[0]
    assert started and started[0][0] == [shot]
    widget.deleteLater()
