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


def test_bake_checkbox_sets_an_explicit_setting(qapp):
    from src.domain.render.models import RenderSettings

    widget = _widget()
    widget.vm.settings = RenderSettings()

    widget.chk_bake_geometry_nodes.setChecked(True)

    assert widget.vm.settings.bake_geometry_nodes is True
    assert widget._bake_touched is True
    widget.deleteLater()


def test_node_card_shows_relaunch_only_for_assigned_failures(qapp):
    from src.interfaces.qt.components.render_node_card import RenderNodeCard
    from src.interfaces.qt.viewmodels.render_panel_viewmodel import (
        RenderNodeCardModel,
    )

    card = RenderNodeCard()
    failed = RenderNodeCardModel(
        node=5,
        status="failed",
        run_id="run",
        assignment=(("pro/shots/sq010/sh010/sh010-layout.blend", (101, 102)),),
    )
    card.update_model(failed)
    assert card.btn_relaunch.isHidden() is False

    no_assignment = RenderNodeCardModel(node=5, status="failed", run_id="run2")
    card.update_model(no_assignment)
    assert card.btn_relaunch.isHidden() is True
    card.deleteLater()


def test_min_ram_spin_round_trips(qapp):
    from src.domain.render.models import RenderSettings

    widget = _widget()
    widget.vm.settings = RenderSettings(min_cpu_ram_gb=64.0)
    widget._apply_settings_to_ui()

    assert widget.spin_min_ram.value() == 64.0
    widget.spin_min_ram.setValue(32.0)
    assert widget._settings_from_ui().min_cpu_ram_gb == 32.0
    widget.deleteLater()


def test_nodes_section_uses_the_new_title(qapp):
    widget = _widget()
    titles = [
        section.button.text()
        for section in widget.findChildren(CollapsibleSection)
    ]
    assert "Nodes" in titles
    widget.deleteLater()


def test_active_run_summary_does_not_show_an_empty_plan(qapp):
    from src.interfaces.qt.viewmodels.render_panel_viewmodel import (
        RenderActivitySummary,
    )

    widget = _widget()
    widget.vm.activity_summary = lambda: RenderActivitySummary(
        active_runs=1,
        nodes=2,
        frames_done=2,
        frames_expected=70,
        gpu_hours=0.4,
        cost=0.1,
        eta_seconds=300,
        shot_names=("sh040", "sh060"),
    )
    plan = SimpleNamespace(
        total_frames=0,
        required_nodes=0,
        estimated_wall_seconds=0.0,
        estimated_cost=0.0,
    )

    html = widget._summary_html(plan, None)

    assert "2/70" in html
    assert "sh040" in html
    assert "All selected shots are rendering" in html
    assert "0 frames" not in html
    widget.deleteLater()


def test_offer_issue_panel_shows_near_offers_and_actions(qapp):
    from src.domain.render.offers import (
        OfferCandidateReport,
        OfferDiagnostics,
        OfferLimits,
        OfferMiss,
        OfferSnapshot,
        OfferSuggestion,
    )

    widget = _widget()
    offer = OfferSnapshot(
        offer_id=57993278,
        gpu_name="RTX 4070",
        gpu_ram_gb=12.0,
        cpu_ram_gb=31.3,
        disk_space_gb=700.0,
        cuda_version="13.2",
        reliability=0.99,
        price_per_hour=0.135,
        inet_down_mbps=940,
        inet_up_mbps=115,
        geolocation="Washington, US",
    )
    report = OfferCandidateReport(
        offer=offer,
        misses=(
            OfferMiss(
                field="min_cpu_ram_gb",
                label="Host RAM",
                actual_text="31.3 GB",
                required_text="32 GB",
                relation="<",
            ),
        ),
    )
    diagnostics = OfferDiagnostics(
        limits=OfferLimits(
            gpu_profile="rtx_4070",
            gpu_label="RTX 4070 12 GB",
            min_gpu_ram_gb=12.0,
            max_price_per_hour=0.18,
            min_cpu_ram_gb=32.0,
        ),
        candidates=(report,),
        near_offers=(report,),
        suggestions=(
            OfferSuggestion(
                field="min_cpu_ram_gb",
                value=31.0,
                label="Lower Min RAM to 31 GB",
                reason="One offer would match.",
                offer_ids=(57993278,),
            ),
        ),
    )
    widget.vm.offer = None
    widget.vm.offer_diagnostics = diagnostics

    widget._render_offer_issue()

    assert widget.offer_issue_frame.isHidden() is False
    assert "31.3 GB" in widget.lbl_offer_issue_details.text() or any(
        "31.3 GB" in label.text()
        for label in widget.offer_issue_frame.findChildren(type(widget.lbl_summary))
    )
    labels = [
        button.text()
        for button in widget.offer_issue_frame.findChildren(
            type(widget.btn_refresh_candidates)
        )
    ]
    assert "Lower Min RAM to 31 GB" in labels
    assert "Search other GPU profiles" in labels
    widget.deleteLater()


def test_similar_gpu_fill_controls_are_opt_in(qapp):
    widget = _widget()

    assert widget.chk_fill_similar.isChecked() is False
    assert widget.combo_similar_mode.isEnabled() is False
    assert widget.combo_similar_mode.currentData() == "floor"
    assert widget.chk_allow_less_vram.isEnabled() is False

    widget.chk_fill_similar.setChecked(True)
    _set_backend(widget.combo_similar_mode, "ceiling")

    assert widget.combo_similar_mode.isEnabled() is True
    assert widget.chk_allow_less_vram.isEnabled() is True
    widget.deleteLater()


def test_shortfall_panel_offers_similar_fill_and_cap(qapp):
    from types import SimpleNamespace

    widget = _widget()
    widget.vm.settings = SimpleNamespace(
        render_backend="vast",
        similar_gpu_mode="floor",
        fill_similar_gpus=False,
        fill_allow_less_vram=False,
    )
    widget.vm.offer = SimpleNamespace(gpu_name="RTX 3080")
    widget.vm.offer_diagnostics = None
    widget.vm.plan = SimpleNamespace(required_nodes=8)
    widget.vm.candidate_offers = [
        SimpleNamespace(
            gpu_name="RTX 3080",
            gpu_label="RTX 3080 10 GB",
            price_per_hour=0.12,
        )
        for _ in range(4)
    ]

    widget._render_offer_issue()

    assert widget.offer_issue_frame.isHidden() is False
    assert "4 of 8" in widget.lbl_offer_issue_title.text()
    labels = [
        button.text()
        for button in widget.offer_issue_frame.findChildren(
            type(widget.btn_refresh_candidates)
        )
    ]
    assert "Fill with similar GPUs" in labels
    assert "Use 4 nodes instead" in labels
    widget.deleteLater()


def test_start_render_dialog_shows_upload_size(qapp, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    widget = _widget()
    widget.vm.settings = SimpleNamespace(
        render_backend="vast",
        bake_geometry_nodes=None,
    )
    widget._plan = SimpleNamespace(
        shots=(SimpleNamespace(geometry_bakes=(), dependencies_audited=True),),
        total_frames=96,
        required_nodes=2,
        estimated_wall_seconds=3600.0,
        estimated_cost=1.25,
    )
    monkeypatch.setattr(widget.vm, "bake_geometry_nodes_effective", lambda *_a: False)
    monkeypatch.setattr(
        widget.vm,
        "staging_estimate",
        lambda shots=None: SimpleNamespace(
            bytes=1_000_000,
            files=10,
            exists=True,
            entries=(),
            images=(("prod/assets/studio.hdr", 1000),),
        ),
    )
    monkeypatch.setattr(widget.vm, "start_render", lambda retry=False: False)
    texts = []
    monkeypatch.setattr(
        QMessageBox,
        "exec",
        lambda box: texts.append((box.text(), box.detailedText())) or QMessageBox.No,
    )

    widget._start_render()

    assert texts
    assert "Upload: 1.0 MB" in texts[0][0]
    assert "10 file(s)" in texts[0][0]
    assert "Images in upload: 1" in texts[0][0]
    assert "prod/assets/studio.hdr" in texts[0][1]
    widget.deleteLater()


def test_vast_preview_dialog_shows_upload_size(qapp, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

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
    widget.vm.shots = [shot]
    widget.vm.settings = RenderSettings(
        render_backend="vast",
        preview_backend="vast",
        selected_shots=(shot.relative_path,),
    )
    _set_backend(widget.combo_preview_backend, "vast")
    monkeypatch.setattr(
        widget.vm,
        "staging_estimate",
        lambda shots=None: SimpleNamespace(
            bytes=2_000_000, files=20, exists=True, entries=()
        ),
    )
    monkeypatch.setattr(widget.vm, "preview_shots", lambda shots: True)
    texts = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: texts.append(args[2]) or QMessageBox.Yes,
    )

    widget._preview_all()

    assert texts
    assert "Upload: 2.0 MB" in texts[0]
    assert "20 file(s)" in texts[0]
    widget.deleteLater()


def test_shots_label_shows_cached_data_notice(qapp):
    widget = _widget()

    widget._on_shots_cache_loaded(True)
    assert widget.lbl_shots_source.isHidden() is False
    assert "Cached data" in widget.lbl_shots_source.text()

    widget._on_shots_cache_loaded(False)
    assert widget.lbl_shots_source.isHidden() is True
    assert widget.lbl_shots_source.text() == ""
    widget.deleteLater()


def test_scan_and_vast_refresh_are_separate_buttons(qapp, monkeypatch):
    widget = _widget()
    scans = []
    vast = []
    monkeypatch.setattr(widget.vm, "scan", lambda **kwargs: scans.append(kwargs) or True)
    monkeypatch.setattr(
        widget.vm, "refresh_offer", lambda: vast.append(True) or True
    )

    widget.btn_refresh.click()
    assert scans == [{"force": True}]
    assert vast == []

    widget.btn_refresh_candidates.click()
    assert vast == [True]
    assert scans == [{"force": True}]
    assert "Refresh Vast" in widget.btn_refresh_candidates.text()
    assert "Scan shots" in widget.btn_refresh.text()
    widget.deleteLater()


def test_vast_balance_signal_updates_the_label(qapp):
    widget = _widget()
    widget.vm.settings = SimpleNamespace(render_backend="vast", preview_backend="local")

    widget.vm.vast_balance_ready.emit(12.5)

    assert "12.50" in widget.lbl_balance.text()
    widget.deleteLater()


def test_node_card_shows_live_frame_thumbnail(qapp, tmp_path):
    from PySide6.QtGui import QColor, QPixmap

    from src.interfaces.qt.components.render_node_card import RenderNodeCard
    from src.interfaces.qt.viewmodels.render_panel_viewmodel import RenderNodeCardModel

    image = tmp_path / "frame.png"
    pixmap = QPixmap(20, 10)
    pixmap.fill(QColor("red"))
    pixmap.save(str(image), "PNG")
    card = RenderNodeCardModel(
        node=6,
        status="rendering",
        frames_done=1,
        frames_expected=22,
        live_frame_path=str(image),
    )

    widget = RenderNodeCard()
    widget.update_model(card)

    assert widget.btn_frame.isHidden() is False
    widget.deleteLater()


def test_live_frame_signal_adds_a_thumbnail_and_updates_preview(qapp, tmp_path):
    from PySide6.QtGui import QColor, QPixmap

    widget = _widget()
    image = tmp_path / "live.png"
    pixmap = QPixmap(20, 10)
    pixmap.fill(QColor("blue"))
    pixmap.save(str(image), "PNG")

    widget._on_live_frame_ready("sh040", 120, str(image), 2)

    assert widget.live_strip_layout.count() >= 2  # thumbnail + stretch
    assert widget._current_preview == str(image)
    widget.deleteLater()


def test_dependencies_block_start_render(qapp, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    from src.domain.render.models import DependencyIssue

    widget = _widget()
    shot = SimpleNamespace(
        name="sh040",
        dependencies_audited=True,
        dependency_issues=(
            DependencyIssue(
                path="/outside/studio.hdr",
                kind="image",
                status="external",
                owner="pro/shots/sq010/sh040/sh040.blend",
            ),
        ),
    )
    widget._plan = SimpleNamespace(
        shots=(shot,),
        total_frames=10,
        required_nodes=1,
        estimated_wall_seconds=60.0,
        estimated_cost=0.1,
    )
    widget.vm.settings = SimpleNamespace(render_backend="vast", bake_geometry_nodes=None)
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[2]),
    )

    widget._start_render()

    assert warnings and "unresolved dependency" in warnings[0]
    widget.deleteLater()


def test_start_render_runs_pending_dependency_audit_first(qapp, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    widget = _widget()
    widget._plan = SimpleNamespace(
        shots=(SimpleNamespace(dependencies_audited=False),),
        total_frames=10,
        required_nodes=1,
        estimated_wall_seconds=60.0,
        estimated_cost=0.1,
    )
    widget.vm.settings = SimpleNamespace(render_backend="vast", bake_geometry_nodes=None)
    audits = []
    infos = []
    monkeypatch.setattr(
        widget.vm, "audit_dependencies", lambda: audits.append(True) or True
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args, **kwargs: infos.append(args[2])
    )

    widget._start_render()

    assert audits == [True]
    assert infos and "audit" in infos[0].lower()
    widget.deleteLater()


def test_dependency_rows_use_blocking_checkboxes(qapp):
    from types import SimpleNamespace

    from src.domain.render.models import DependencyIssue

    widget = _widget()
    issue = DependencyIssue(
        path="/outside/studio.hdr",
        kind="image",
        status="external",
        owner="pro/shots/sq010/sh040/sh040.blend",
        blocking=False,
    )
    shot = SimpleNamespace(
        relative_path="pro/shots/sq010/sh040/sh040.blend",
        dependencies_audited=True,
        dependency_issues=(issue,),
    )
    widget._plan = SimpleNamespace(shots=(shot,), required_nodes=1)
    monkeypatch = None
    widget.vm.shots = [shot]
    widget.vm.plan = widget._plan

    widget._refresh_dependencies()

    assert widget.dependency_rows_layout.count() >= 2
    assert "0 marked blocking" in widget.lbl_dependencies.text()
    widget.deleteLater()


def test_unchecked_dependency_does_not_block_start_render(qapp, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    from src.domain.render.models import DependencyIssue

    widget = _widget()
    issue = DependencyIssue(
        path="/outside/studio.hdr",
        kind="image",
        status="external",
        owner="pro/shots/sq010/sh040/sh040.blend",
        blocking=False,
    )
    shot = SimpleNamespace(
        geometry_bakes=(),
        dependencies_audited=True,
        dependency_issues=(issue,),
    )
    widget._plan = SimpleNamespace(
        shots=(shot,),
        total_frames=10,
        required_nodes=1,
        estimated_wall_seconds=60.0,
        estimated_cost=0.1,
    )
    widget.vm.settings = SimpleNamespace(render_backend="vast", bake_geometry_nodes=None)
    monkeypatch.setattr(widget.vm, "bake_geometry_nodes_effective", lambda *_a: False)
    monkeypatch.setattr(
        widget.vm,
        "staging_estimate",
        lambda shots=None: SimpleNamespace(
            bytes=1, files=1, exists=True, entries=(), images=()
        ),
    )
    monkeypatch.setattr(widget.vm, "start_render", lambda retry=False: False)
    warnings = []
    dialogs = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2])
    )
    monkeypatch.setattr(
        QMessageBox, "exec", lambda box: dialogs.append(box.text()) or QMessageBox.No
    )

    widget._start_render()

    assert warnings == []
    assert dialogs and "Render 10 frame(s)" in dialogs[0]
    widget.deleteLater()


def test_shot_review_card_starts_collapsed_and_exposes_inspector_actions(qapp):
    from src.interfaces.qt.components.shot_review_card import ShotReviewCard
    from src.interfaces.qt.viewmodels.render_panel_viewmodel import ShotReviewModel

    model = ShotReviewModel(
        name="sh040",
        sequence="sq010",
        status="ready",
        status_label="Ready",
        status_tooltip="",
        selected=True,
        locked=False,
        ready=True,
        frames=10,
        rendered=10,
        approved=0,
        missing=0,
        frame_range="1–10",
        engine="CYCLES",
        resolution="1920×1080",
        samples=128,
        image_format="PNG",
        measured_seconds=None,
        warnings=(),
        relative_path="pro/shots/sq010/sh040/sh040.blend",
    )
    card = ShotReviewCard()
    card.update_model(model)
    captured = []
    card.inspector_requested.connect(lambda path, tab: captured.append((path, tab)))

    assert card.content.isHidden() is True
    card.btn_comments.click()
    card.btn_dependencies.click()

    assert captured == [
        (model.relative_path, "comments"),
        (model.relative_path, "dependencies"),
    ]
    card.deleteLater()


def test_publish_tab_and_inspector_exist(qapp):
    widget = _widget()

    assert widget.inspector_tabs.count() == 3
    assert [widget.inspector_tabs.tabText(i) for i in range(3)] == [
        "Comments",
        "Shot Dependencies",
        "Publish Shot",
    ]
    assert widget.inspector_tabs.isHidden() is False
    widget.btn_inspector_toggle.click()
    assert widget.inspector_tabs.isHidden() is True
    widget.deleteLater()


def test_dependency_checkbox_uses_the_viewmodel_plan(qapp):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QCheckBox

    from src.domain.render.models import DependencyIssue

    widget = _widget()
    issue = DependencyIssue(
        path="/outside/studio.hdr",
        kind="image",
        status="external",
        owner="pro/shots/sq010/sh040/sh040.blend",
        blocking=False,
    )
    shot = SimpleNamespace(
        relative_path="pro/shots/sq010/sh040/sh040.blend",
        dependencies_audited=True,
        dependency_issues=(issue,),
    )
    widget.vm.shots = [shot]
    widget.vm.plan = SimpleNamespace(shots=(shot,))
    widget._plan = SimpleNamespace(
        shots=(
            SimpleNamespace(
                relative_path=shot.relative_path,
                dependencies_audited=True,
                dependency_issues=(
                    DependencyIssue(
                        path=issue.path,
                        kind=issue.kind,
                        status=issue.status,
                        owner=issue.owner,
                        blocking=True,
                    ),
                ),
            ),
        )
    )

    widget._refresh_dependencies()

    checkboxes = widget.dependency_rows_widget.findChildren(QCheckBox)
    assert checkboxes and checkboxes[0].isChecked() is False
    widget.deleteLater()


def test_publish_tab_enables_with_one_rendered_frame(qapp, monkeypatch):
    from types import SimpleNamespace

    widget = _widget()
    shot = SimpleNamespace(
        name="sh040",
        relative_path="pro/shots/sq010/sh040/sh040.blend",
        frames=10,
        frames_override=None,
    )
    widget._selected_shot = shot
    widget.vm.kitsu_tasks = [
        {
            "id": "task-1",
            "entity_name": "sh040",
            "task_type_name": "render",
            "task_status": {"name": "WIP"},
            "assignees": [{"full_name": "Ernesto"}],
        }
    ]
    widget.vm.kitsu_statuses = [{"id": "status-1", "name": "Review"}]
    monkeypatch.setattr(widget.vm, "rendered_frame_numbers", lambda _shot: [101])
    monkeypatch.setattr(widget.vm, "suggested_publish_version", lambda _shot: "v001")

    widget._refresh_publish_tab()

    assert widget.btn_publish.isEnabled() is True
    assert "101–101" in widget.lbl_publish_range.text()
    assert widget.combo_publish_task.count() == 1
    widget.deleteLater()
