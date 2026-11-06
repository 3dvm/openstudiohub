"""Unit tests for the render panel ViewModel plan recalculation."""

from pathlib import Path

from src.application.services.render_service import RenderService
from src.domain.render.models import RenderQuality, RenderSettings, RenderShot
from src.interfaces.qt.viewmodels.render_panel_viewmodel import RenderPanelViewModel


def _shot():
    return RenderShot(
        name="sh010",
        blend_path=Path("/project/pro/shots/sq010/sh010/sh010-layout.blend"),
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(samples=256),
        frame_start=101,
        frame_end=196,
        object_count=639,
        mesh_count=625,
        has_camera=True,
        measured_seconds=40.5,
    )


def test_local_recalculation_uses_one_node_and_zero_cost(qapp, tmp_path):
    viewmodel = RenderPanelViewModel(RenderService())
    shot = _shot()
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,),
        target_hours=1.0,
        render_backend="local",
        local_speed_factor=8.0,
    )
    captured = {}
    viewmodel.shots_ready.connect(
        lambda shots, plan, offer, balance: captured.update(plan=plan)
    )

    viewmodel.recalculate()

    plan = captured["plan"]
    assert plan.required_nodes == 1
    assert plan.estimated_cost == 0.0
    assert plan.estimated_wall_seconds > plan.total_gpu_seconds
    assert plan.total_frames == 96


def test_candidate_offers_build_one_card_per_node(qapp, tmp_path):
    from types import SimpleNamespace

    from src.interfaces.qt.viewmodels.render_panel_viewmodel import RenderNodeCardModel

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.settings = RenderSettings(render_backend="vast")
    viewmodel.candidate_offers = [
        SimpleNamespace(
            id=10,
            gpu_name="RTX 4090",
            geolocation="US",
            price_per_hour=0.42,
            reliability=0.99,
            inet_down_mbps=500,
            inet_up_mbps=100,
        ),
        SimpleNamespace(
            id=11,
            gpu_name="RTX 3090",
            geolocation="CA",
            price_per_hour=0.31,
            reliability=0.97,
            inet_down_mbps=300,
            inet_up_mbps=80,
        ),
    ]

    viewmodel._build_node_cards(SimpleNamespace(required_nodes=2))

    assert [card.node for card in viewmodel.node_cards] == [0, 1]
    assert viewmodel.node_cards[0].gpu_name == "RTX 4090"
    assert viewmodel.node_cards[1].offer_id == 11
    assert viewmodel.node_cards[0].status == "candidate"


def test_burst_progress_updates_the_matching_node_card(qapp):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel._ensure_node_card(0)

    viewmodel._on_burst_progress_status(
        SimpleNamespace(
            node=0,
            stage="render",
            message="rendering sh010",
            frames_done=4,
            frames_total=10,
            instance_id=77,
            gpu_name="RTX 4090",
            region="US",
            price_per_hour=0.42,
            offer_id=10,
        )
    )

    card = viewmodel.node_cards[0]
    assert card.status == "rendering"
    assert card.instance_id == 77
    assert card.frames_done == 4
    assert card.gpu_name == "RTX 4090"


def test_benchmark_starts_without_a_precomputed_offer(qapp, tmp_path, monkeypatch):
    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.shots = [_shot()]
    viewmodel.settings = RenderSettings(render_backend="local")
    started = []
    monkeypatch.setattr(
        viewmodel.workers,
        "start",
        lambda key, worker, **kwargs: started.append(key) or True,
    )

    assert viewmodel.benchmark_selected(_shot()) is True
    assert started == ["render_benchmark"]


def _review_vm(tmp_path, frames_rendered=0, approved=0):
    viewmodel = RenderPanelViewModel(RenderService())
    shot = _shot()
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,), render_backend="local"
    )
    output = viewmodel.service.shot_output_dir(tmp_path, shot)
    output.mkdir(parents=True)
    for index in range(frames_rendered):
        (output / f"frame_{101 + index:04d}.png").write_bytes(b"x")
    if approved:
        viewmodel.service.approve_frames(
            tmp_path, shot, list(range(101, 101 + approved)), True
        )
    return viewmodel, shot


def test_shot_status_reflects_rendered_and_approved_frames(qapp, tmp_path):
    viewmodel, shot = _review_vm(tmp_path)
    assert viewmodel.shot_reviews()[0].status == "ready"

    viewmodel, shot = _review_vm(tmp_path / "partial", frames_rendered=2)
    review = viewmodel.shot_reviews()[0]
    assert review.status == "with_renders"
    assert review.rendered == 2 and review.approved == 0

    viewmodel, shot = _review_vm(tmp_path / "review", frames_rendered=96)
    assert viewmodel.shot_reviews()[0].status == "in_review"

    viewmodel, shot = _review_vm(
        tmp_path / "finished", frames_rendered=96, approved=96
    )
    assert viewmodel.shot_reviews()[0].status == "finished"


def test_locked_shot_reports_rendering_and_cannot_be_rendered_again(qapp, tmp_path):
    viewmodel, shot = _review_vm(tmp_path)
    viewmodel._locked_shots = {shot.relative_path}

    assert viewmodel.shot_reviews()[0].status == "rendering"
    assert viewmodel.shot_reviews()[0].locked is True
    assert viewmodel.shot_reviews()[0].status_tooltip
    assert viewmodel.render_single_shot(shot) is False


def test_unapprove_and_delete_unapproved_use_the_frame_sidecar(qapp, tmp_path):
    viewmodel, shot = _review_vm(tmp_path / "frames", frames_rendered=3, approved=1)

    ok, _message = viewmodel.unapprove_all(shot)
    assert ok is True
    assert viewmodel.shot_reviews()[0].approved == 0

    ok, _message = viewmodel.delete_unapproved(shot)
    assert ok is True
    assert viewmodel.shot_reviews()[0].rendered == 0


def test_pending_shots_exclude_approved_frames(qapp, tmp_path):
    viewmodel, shot = _review_vm(tmp_path, frames_rendered=20, approved=20)

    pending = viewmodel.service.pending_shots(tmp_path, [shot])

    assert pending and pending[0].frames == 76
    assert pending[0].frame_start == shot.frame_start


def test_recalculate_plans_only_pending_frames(qapp, tmp_path):
    viewmodel, shot = _review_vm(tmp_path, frames_rendered=20, approved=20)
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,), render_backend="local"
    )
    captured = {}
    original = viewmodel.service.plan

    def spy(*args, **kwargs):
        captured["shots"] = list(kwargs.get("shots") or [])
        return original(*args, **kwargs)

    viewmodel.service.plan = spy

    viewmodel.recalculate()

    assert captured["shots"][0].frames == 76


def test_preview_message_uses_the_selected_backend(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.shots = [_shot()]
    viewmodel.settings = RenderSettings(preview_backend="vast")
    viewmodel.offer = SimpleNamespace(price_per_hour=0.4)
    messages = []
    viewmodel.status_message.connect(lambda message, _color: messages.append(message))
    monkeypatch.setattr(viewmodel.workers, "start", lambda *args, **kwargs: True)

    assert viewmodel.preview_shots([viewmodel.shots[0]]) is True

    assert any("on Vast.ai" in message for message in messages)


def test_preview_paths_persist_in_the_project_index(qapp, tmp_path):
    from src.infrastructure.render.status import RenderStatusStore

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.status_store = RenderStatusStore.for_project(tmp_path)
    viewmodel.shots = [_shot()]
    image = tmp_path / "preview.png"
    image.write_bytes(b"x")

    viewmodel._on_preview_ready("sh010", str(image))

    second = RenderPanelViewModel(RenderService())
    second.project_root = tmp_path
    second.status_store = RenderStatusStore.for_project(tmp_path)
    second._load_preview_paths()

    assert second.preview_paths["sh010"] == image


def test_latest_preview_path_finds_run_level_vast_previews(qapp, tmp_path):
    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    shot = _shot()
    image = (
        viewmodel.service.render_root(tmp_path)
        / ".previews"
        / "20261106-182230"
        / "shots"
        / "sq010"
        / "sh010.render"
        / "frame_0101.png"
    )
    image.parent.mkdir(parents=True)
    image.write_bytes(b"x")

    assert viewmodel.latest_preview_path(shot) == image
