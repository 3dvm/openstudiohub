"""Unit tests for the render panel ViewModel plan recalculation."""

from dataclasses import replace
from pathlib import Path

from src.application.services.render_service import RenderService
from src.domain.render.models import (
    RenderPlan,
    RenderQuality,
    RenderSettings,
    RenderShot,
)
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
    viewmodel._ensure_node_card("", 0)

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


def test_node_progress_tracks_real_frame_time_and_eta(qapp):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel._ensure_node_card("", 0)
    viewmodel._on_burst_progress_status(
        SimpleNamespace(
            node=0,
            stage="render",
            message="rendering sh010",
            shot="sh010",
            frames_done=0,
            frames_total=10,
            instance_id=1,
            gpu_name="RTX 4080",
            region="US",
            price_per_hour=0.4,
            offer_id=1,
        )
    )
    for done in (1, 2):
        viewmodel._on_burst_progress_status(
            SimpleNamespace(
                node=0,
                stage="frame",
                message='{"frame": 101, "seconds": 60}',
                shot="sh010",
                frames_done=done,
                frames_total=10,
                instance_id=1,
                gpu_name="",
                region="",
                price_per_hour=0,
                offer_id=0,
            )
        )

    card = viewmodel.node_cards[0]
    assert card.current_shot == "sh010"
    assert card.seconds_per_frame == 60
    assert card.eta_seconds == 8 * 60
    assert card.progress_percent == 20


def test_terminal_node_event_marks_completed_and_destroy_does_not_downgrade(
    qapp, tmp_path
):
    from types import SimpleNamespace

    from src.infrastructure.render.run_audit import RenderRunAuditLogger
    from src.infrastructure.render.status import RenderStatusStore

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.status_store = RenderStatusStore.for_project(tmp_path)
    viewmodel.audit = RenderRunAuditLogger(tmp_path / "audit.jsonl")
    viewmodel._active_run_id = "runtest"
    viewmodel._ensure_node_card("", 0)
    viewmodel._on_burst_progress_status(
        SimpleNamespace(
            node=0,
            stage="render",
            message="rendering sh010",
            frames_done=0,
            frames_total=10,
            instance_id=7,
            gpu_name="RTX 4080",
            region="US",
            price_per_hour=0.4,
            offer_id=1,
            shot="sh010",
        )
    )
    viewmodel._on_burst_progress_status(
        SimpleNamespace(
            node=0,
            stage="finished",
            message="completed",
            frames_done=10,
            frames_total=10,
            instance_id=7,
            ok=True,
            blender_logs=("/tmp/blender.log",),
        )
    )

    card = viewmodel.node_cards[0]
    assert card.status == "completed"
    assert card.final is True
    assert card.eta_seconds == 0
    assert card.hub_logs
    assert card.summary_logs
    assert card.blender_logs == (Path("/tmp/blender.log"),)

    viewmodel._on_burst_progress_status(
        SimpleNamespace(
            node=0,
            stage="destroy",
            message="instance 7 destroyed (cleanup)",
            frames_done=0,
            frames_total=0,
            instance_id=7,
        )
    )

    assert card.status == "completed"
    assert card.message == "completed"

    viewmodel._ensure_node_card("", 1)
    viewmodel._on_burst_progress_status(
        SimpleNamespace(
            node=1,
            stage="failed",
            message="boom",
            frames_done=3,
            frames_total=10,
            instance_id=8,
            ok=False,
        )
    )
    assert viewmodel.node_cards[1].status == "failed"
    assert viewmodel.node_cards[1].final is True


def test_burst_status_uses_total_assigned_frames(qapp, tmp_path):
    from types import SimpleNamespace

    from src.infrastructure.render.status import RenderStatusStore

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.status_store = RenderStatusStore.for_project(tmp_path)
    viewmodel.plan = SimpleNamespace(total_frames=57)
    viewmodel._ensure_node_card("", 0)
    viewmodel._ensure_node_card("", 1)
    for node in (0, 1):
        viewmodel._on_burst_progress_status(
            SimpleNamespace(
                node=node,
                stage="render",
                message="rendering",
                frames_done=0,
                frames_total=132,
                instance_id=node + 1,
                gpu_name="",
                region="",
                price_per_hour=0,
                offer_id=0,
                shot="sh010",
            )
        )

    data = viewmodel.status_store.read()

    assert data["frames_expected"] == 264


def test_set_preview_frame_persists_per_shot(qapp, monkeypatch):
    viewmodel = RenderPanelViewModel(RenderService())
    shot = _shot()
    saved = []
    monkeypatch.setattr(viewmodel, "_save_settings", lambda: saved.append(True))

    viewmodel.set_preview_frame(shot, 150)

    assert viewmodel.settings.preview_frames == ((shot.relative_path, 150),)
    assert viewmodel.preview_frame_for(shot) == 150
    assert saved

    viewmodel.set_preview_frame(shot, 9999)
    assert viewmodel.preview_frame_for(shot) == shot.frame_end


def test_concurrent_runs_lock_only_their_own_shots(qapp, tmp_path, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace

    from src.infrastructure.render.run_audit import RenderRunAuditLogger
    from src.infrastructure.render.status import RenderStatusStore

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.status_store = RenderStatusStore.for_project(tmp_path)
    viewmodel.audit = RenderRunAuditLogger(tmp_path / "audit.jsonl")
    first = replace(
        _shot(),
        name="070",
        relative_path="pro/shots/sq010/070/070-layout.blend",
        blend_path=Path("/project/pro/shots/sq010/070/070-layout.blend"),
    )
    second = replace(
        _shot(),
        name="sh020",
        relative_path="pro/shots/sq010/sh020/sh020-layout.blend",
        blend_path=Path("/project/pro/shots/sq010/sh020/sh020-layout.blend"),
    )
    viewmodel.shots = [first, second]
    viewmodel.settings = RenderSettings(
        selected_shots=(first.relative_path, second.relative_path),
        render_backend="vast",
    )
    viewmodel.offer = SimpleNamespace(price_per_hour=0.2)
    viewmodel.balance = 50.0
    started = []
    monkeypatch.setattr(
        viewmodel.workers,
        "start",
        lambda key, worker, **kwargs: started.append(key) or True,
    )

    assert viewmodel._start_render_plan(viewmodel._plan_for_shots([first]))
    assert viewmodel.is_shot_locked(first)
    assert not viewmodel.is_shot_locked(second)

    assert viewmodel._start_render_plan(viewmodel._plan_for_shots([second]))
    assert viewmodel.is_shot_locked(second)
    assert len(viewmodel._runs) == 2
    assert len(started) == 2

    finished_run = next(
        run_id for run_id, run in viewmodel._runs.items() if first.relative_path in run.locked_shots
    )
    viewmodel._handle_burst_finished(
        SimpleNamespace(
            run_id=finished_run,
            ok=True,
            frames_rendered=1,
            cost=0.0,
            nodes=(),
            message="ok",
        )
    )

    assert not viewmodel.is_shot_locked(first)
    assert viewmodel.is_shot_locked(second)
    assert len(viewmodel._runs) == 1


def test_burst_progress_routes_to_run_cards(qapp, tmp_path, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace

    from src.infrastructure.render.run_audit import RenderRunAuditLogger
    from src.infrastructure.render.status import RenderStatusStore

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.status_store = RenderStatusStore.for_project(tmp_path)
    viewmodel.audit = RenderRunAuditLogger(tmp_path / "audit.jsonl")
    shot = replace(
        _shot(),
        name="070",
        relative_path="pro/shots/sq010/070/070-layout.blend",
        blend_path=Path("/project/pro/shots/sq010/070/070-layout.blend"),
    )
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,), render_backend="vast"
    )
    viewmodel.offer = SimpleNamespace(price_per_hour=0.2)
    viewmodel.balance = 50.0
    monkeypatch.setattr(
        viewmodel.workers, "start", lambda key, worker, **kwargs: True
    )
    assert viewmodel._start_render_plan(viewmodel._plan_for_shots([shot]))
    run_id = next(iter(viewmodel._runs))

    viewmodel._on_burst_progress_status(
        SimpleNamespace(
            run_id=run_id,
            node=0,
            stage="frame",
            message='{"frame": 101, "seconds": 30}',
            shot=shot.name,
            frames_done=1,
            frames_total=2,
        )
    )

    card = viewmodel._runs[run_id].cards[0]
    assert card.status == "rendering"
    assert card.frames_done == 1
    assert viewmodel._runs[run_id].frame_seconds[shot.name] == [30.0]
    assert any(item.key == card.key for item in viewmodel.node_cards)


def test_run_measurements_are_stored_per_backend(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src.interfaces.qt.viewmodels.render_panel_viewmodel import (
        RenderNodeCardModel,
        RenderRunState,
    )

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    shot = _shot()
    remote = RenderRunState(
        run_id="remote",
        backend="vast",
        plan=SimpleNamespace(shots=(shot,)),
        gpu_profile="rtx_3080",
    )
    remote.frame_seconds[shot.name] = [30.0, 40.0, 50.0]
    remote.cards[0] = RenderNodeCardModel(
        node=0, run_id="remote", gpu_name="RTX 3080"
    )
    local = RenderRunState(
        run_id="local",
        backend="local",
        plan=SimpleNamespace(shots=(shot,)),
        gpu_profile="rtx_3080",
    )
    local.frame_seconds[shot.name] = [120.0, 160.0]
    local.cards[0] = RenderNodeCardModel(
        node=0, run_id="local", gpu_name="Local workstation"
    )
    recorded = []
    monkeypatch.setattr(
        viewmodel.service,
        "record_measurement",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    monkeypatch.setattr(
        viewmodel, "measurement_for", lambda shot, backend="remote": None
    )

    viewmodel._store_run_measurements(remote)
    viewmodel._store_run_measurements(local)

    assert recorded[0][0][2] == "rtx_3080"
    assert recorded[0][0][3] == 40.0
    assert recorded[1][0][2] == "local"
    assert recorded[1][0][3] == 140.0


def test_run_measurements_ask_before_overwriting_an_existing_benchmark(
    qapp, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from src.interfaces.qt.viewmodels.render_panel_viewmodel import (
        RenderNodeCardModel,
        RenderRunState,
    )

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    shot = _shot()
    run = RenderRunState(
        run_id="remote",
        backend="vast",
        plan=SimpleNamespace(shots=(shot,)),
        gpu_profile="rtx_3080",
    )
    run.frame_seconds[shot.name] = [35.0, 45.0]
    run.cards[0] = RenderNodeCardModel(
        node=0, run_id="remote", gpu_name="RTX 3080"
    )
    conflicts = []
    viewmodel.measurement_conflicts.connect(lambda items: conflicts.extend(items))
    monkeypatch.setattr(
        viewmodel,
        "measurement_for",
        lambda shot, backend="remote": {
            "seconds": 25.0,
            "measured_at": "2026-01-01T00:00:00+00:00",
        },
    )
    recorded = []
    monkeypatch.setattr(
        viewmodel.service,
        "record_measurement",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )

    viewmodel._store_run_measurements(run)

    assert recorded == []
    assert conflicts and conflicts[0]["seconds"] == 40.0
    assert conflicts[0]["existing"]["seconds"] == 25.0


def test_set_render_backend_recalculates_and_refreshes_vast_offers(
    qapp, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    shot = _shot()
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,),
        render_backend="local",
        gpu_profile="rtx_3080",
    )
    started = []
    monkeypatch.setattr(
        viewmodel.workers,
        "start",
        lambda key, worker, **kwargs: started.append((key, worker)) or True,
    )

    viewmodel.set_render_backend("vast")

    assert viewmodel.settings.render_backend == "vast"
    assert viewmodel.settings.preview_backend == "local"
    assert any(key == "render_offer" for key, _worker in started)
    assert viewmodel.plan is not None

    offer = SimpleNamespace(gpu_name="RTX 3080", price_per_hour=0.2)
    viewmodel._on_offers_ready([offer], 12.5)

    assert viewmodel.offer is offer
    assert viewmodel.balance == 12.5
    assert viewmodel.plan.price_per_hour == 0.2

    viewmodel.set_render_backend("local")

    assert viewmodel.settings.render_backend == "local"
    assert viewmodel.plan.required_nodes == 1
    assert viewmodel.plan.estimated_cost == 0.0


def test_approve_frames_emits_shot_reviews_only_on_success(
    qapp, tmp_path, monkeypatch
):
    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    shot = _shot()
    emitted = []
    viewmodel.shot_reviews_ready.connect(lambda reviews: emitted.append(reviews))

    monkeypatch.setattr(
        viewmodel.service,
        "approve_frames",
        lambda *args, **kwargs: (True, "1 frame(s) approved."),
    )
    ok, _message = viewmodel.approve_frames(shot, [101], True)
    assert ok is True
    assert len(emitted) == 1

    emitted.clear()
    monkeypatch.setattr(
        viewmodel.service,
        "approve_frames",
        lambda *args, **kwargs: (False, "Only rendered frames can be approved."),
    )
    ok, _message = viewmodel.approve_frames(shot, [101], True)
    assert ok is False
    assert emitted == []


def test_stage_progress_reports_upload_bytes(qapp):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel._ensure_node_card("", 0)

    viewmodel._on_burst_progress_status(
        SimpleNamespace(
            node=0,
            stage="stage",
            message="Uploading 45% · 450.0 MB / 1.0 GB",
            bytes_done=450_000_000,
            bytes_total=1_000_000_000,
            files_total=22_949,
        )
    )

    card = viewmodel.node_cards[0]
    assert card.upload_bytes_done == 450_000_000
    assert card.upload_bytes_total == 1_000_000_000
    assert card.upload_files == 22_949
    assert card.progress_percent == 45.0


def test_benchmark_creates_a_node_card_and_clears_it_on_finish(
    qapp, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    shot = _shot()
    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,), render_backend="vast"
    )
    viewmodel.offer = SimpleNamespace(price_per_hour=0.2, gpu_name="RTX 3080")
    estimate = SimpleNamespace(
        selection=SimpleNamespace(frames=(101, 148, 196)),
        staging=SimpleNamespace(bytes=1_000, files=10, entries=()),
        plan=SimpleNamespace(estimated_cost=0.05),
    )
    monkeypatch.setattr(viewmodel, "benchmark_estimate", lambda shot=None: estimate)
    monkeypatch.setattr(viewmodel, "scan", lambda *args, **kwargs: None)
    started = []
    monkeypatch.setattr(
        viewmodel.workers,
        "start",
        lambda key, worker, **kwargs: started.append(key) or True,
    )

    assert viewmodel.benchmark_selected(shot)

    assert started == ["render_benchmark"]
    assert viewmodel._benchmark_run_id
    cards = [card for card in viewmodel.node_cards if card.run_label == "benchmark"]
    assert cards and cards[0].frames_expected == 3
    assert cards[0].current_shot == "sh010"

    viewmodel._on_benchmark_finished("sh010", 40.0)

    assert viewmodel._benchmark_run_id == ""
    assert cards[0].final is True
    assert cards[0].status == "completed"


def test_benchmark_shots_runs_one_batch_card(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    shot = _shot()
    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,), render_backend="vast"
    )
    viewmodel.offer = SimpleNamespace(price_per_hour=0.2, gpu_name="RTX 3080")
    estimate = SimpleNamespace(
        shots=((shot, SimpleNamespace(frames=(101, 148, 196))),),
        frames=3,
        staging=SimpleNamespace(bytes=1_000, files=10, entries=()),
        plan=SimpleNamespace(estimated_cost=0.05),
    )
    monkeypatch.setattr(
        viewmodel, "benchmark_batch_estimate", lambda shots=None: estimate
    )
    monkeypatch.setattr(viewmodel, "scan", lambda *args, **kwargs: None)
    started = []
    monkeypatch.setattr(
        viewmodel.workers,
        "start",
        lambda key, worker, **kwargs: started.append(key) or True,
    )
    finished = []
    viewmodel.benchmarks_finished.connect(
        lambda results, message: finished.append((results, message))
    )

    assert viewmodel.benchmark_shots([shot])

    assert started == ["render_benchmark"]
    cards = [card for card in viewmodel.node_cards if card.run_label == "benchmark"]
    assert len(cards) == 1
    assert cards[0].frames_expected == 3

    viewmodel._on_benchmarks_finished(
        [("sh010", 40.0)], "Benchmarked 1/1 shot(s)."
    )

    assert viewmodel._benchmark_run_id == ""
    assert cards[0].final is True
    assert cards[0].status == "completed"
    assert finished and finished[0][1] == "Benchmarked 1/1 shot(s)."


def test_bake_geometry_defaults_follow_the_local_cache_state(qapp):
    from dataclasses import replace

    from src.domain.render.models import GeometryBakeInfo

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.settings = RenderSettings()
    fresh = replace(
        _shot(),
        geometry_bakes=(
            GeometryBakeInfo(local_cache=True, cache_stale=False),
        ),
    )
    stale = replace(
        _shot(),
        geometry_bakes=(
            GeometryBakeInfo(local_cache=True, cache_stale=True),
        ),
    )
    missing = replace(
        _shot(), geometry_bakes=(GeometryBakeInfo(local_cache=False),)
    )

    assert viewmodel.bake_geometry_nodes_effective([fresh]) is False
    assert viewmodel.bake_geometry_nodes_effective([stale]) is True
    assert viewmodel.bake_geometry_nodes_effective([missing]) is True

    viewmodel.settings = RenderSettings(bake_geometry_nodes=False)
    assert viewmodel.bake_geometry_nodes_effective([missing]) is False


def test_particle_cache_state_is_visible_per_shot(qapp):
    from dataclasses import replace

    from src.domain.render.models import ParticleCacheInfo

    viewmodel = RenderPanelViewModel(RenderService())
    missing = replace(
        _shot(),
        particle_caches=(ParticleCacheInfo(baked=False),),
    )
    present = replace(
        _shot(),
        particle_caches=(ParticleCacheInfo(baked=True),),
    )

    assert viewmodel._particle_state(missing) == "Particle cache missing"
    assert viewmodel._particle_state(present) == "Particle cache present"
    assert viewmodel._particle_state(_shot()) == ""


def test_offer_progress_captures_the_node_assignment(qapp):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel._ensure_node_card("", 0)

    viewmodel._on_burst_progress_status(
        SimpleNamespace(
            node=0,
            stage="offer",
            message="renting",
            assignment=(("pro/shots/sq010/sh010/sh010-layout.blend", (101, 102)),),
        )
    )

    card = viewmodel.node_cards[0]
    assert card.assignment == (
        ("pro/shots/sq010/sh010/sh010-layout.blend", (101, 102)),
    )


def test_relaunch_plan_reuses_the_failed_frames_on_one_node(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src.interfaces.qt.viewmodels.render_panel_viewmodel import (
        NodeLaunchConfig,
        RenderNodeCardModel,
    )

    shot = _shot()
    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(render_backend="vast")
    card = RenderNodeCardModel(
        node=5,
        status="failed",
        run_id="original",
        assignment=((shot.relative_path, (101, 102, 105)),),
        launch=NodeLaunchConfig(
            gpu_profile="rtx_3080",
            max_price_per_hour=0.18,
            bake_geometry_nodes=False,
        ),
        price_per_hour=0.15,
    )
    plan = SimpleNamespace(
        shots=(shot,),
        total_frames=3,
        required_nodes=1,
        estimated_cost=0.2,
        warnings=(),
    )
    monkeypatch.setattr(viewmodel.service, "plan", lambda *a, **k: plan)
    monkeypatch.setattr(
        viewmodel.service,
        "staging_estimate",
        lambda *a, **k: SimpleNamespace(bytes=1_000, files=10),
    )

    relaunch = viewmodel.relaunch_plan(card)

    assert relaunch is not None
    assert [item.frame_start for item in relaunch.shots] == [101, 105]
    assert [item.frame_end for item in relaunch.shots] == [102, 105]
    assert relaunch.plan.required_nodes == 1
    assert relaunch.launch.gpu_profile == "rtx_3080"


def test_relaunch_node_starts_one_node_with_the_original_index(
    qapp, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import src.interfaces.qt.viewmodels.render_panel_viewmodel as vm_module
    from src.interfaces.qt.viewmodels.render_panel_viewmodel import (
        NodeLaunchConfig,
        RenderNodeCardModel,
    )

    shot = _shot()
    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(render_backend="vast")
    card = RenderNodeCardModel(
        node=5,
        status="failed",
        run_id="original",
        assignment=((shot.relative_path, (101, 102)),),
        launch=NodeLaunchConfig(
            gpu_profile="rtx_3080",
            max_price_per_hour=0.18,
            bake_geometry_nodes=False,
        ),
        price_per_hour=0.15,
    )
    plan = SimpleNamespace(
        shots=(shot,),
        total_frames=2,
        required_nodes=1,
        estimated_cost=0.2,
        warnings=(),
    )
    monkeypatch.setattr(viewmodel.service, "plan", lambda *a, **k: plan)
    monkeypatch.setattr(
        viewmodel.service,
        "staging_estimate",
        lambda *a, **k: SimpleNamespace(bytes=1_000, files=10),
    )
    monkeypatch.setattr(
        viewmodel,
        "_register_run",
        lambda run, clear_finished=True: viewmodel._runs.__setitem__(
            run.run_id, run
        ),
    )
    started = []
    monkeypatch.setattr(
        viewmodel.workers,
        "start",
        lambda key, worker, **kwargs: started.append((key, worker)) or True,
    )

    class _Signal:
        def connect(self, *_args, **_kwargs):
            return None

    class _Worker:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            self.burst_progress = _Signal()
            self.report_ready = _Signal()
            self.error = _Signal()

    monkeypatch.setattr(vm_module, "RenderBurstWorker", _Worker)

    assert viewmodel.relaunch_node(card)

    run = next(iter(viewmodel._runs.values()))
    assert run.node_indices == (5,)
    assert run.label == "relaunch"
    assert run.cards[5].assignment == card.assignment
    worker = started[0][1]
    assert worker.kwargs["node_indices"] == [5]
    assert worker.kwargs["skip_existing"] is True


def test_min_ram_auto_for_node_bakes(qapp):
    from dataclasses import replace

    from src.domain.render.bakes import DEFAULT_GN_BAKE_MIN_CPU_RAM_GB
    from src.domain.render.models import GeometryBakeInfo

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.settings = RenderSettings()
    stale = replace(
        _shot(),
        geometry_bakes=(
            GeometryBakeInfo(local_cache=True, cache_stale=True),
        ),
    )

    assert (
        viewmodel.min_cpu_ram_gb_effective([stale])
        == DEFAULT_GN_BAKE_MIN_CPU_RAM_GB
    )

    viewmodel.settings = RenderSettings(min_cpu_ram_gb=32.0)
    assert viewmodel.min_cpu_ram_gb_effective([stale]) == 32.0


def test_activity_summary_uses_active_runs_when_the_pending_plan_is_empty(
    qapp, tmp_path
):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from src.interfaces.qt.viewmodels.render_panel_viewmodel import (
        RenderNodeCardModel,
        RenderRunState,
    )

    viewmodel = RenderPanelViewModel(RenderService())
    shot = _shot()
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,), render_backend="vast"
    )
    plan = viewmodel._plan_for_shots([shot])
    run = RenderRunState(
        run_id="run-1",
        backend="vast",
        plan=plan,
        gpu_profile="rtx_4070",
        locked_shots={shot.relative_path},
        cards={
            0: RenderNodeCardModel(
                node=0,
                status="rendering",
                price_per_hour=0.2,
                frames_done=1,
                frames_expected=35,
                eta_seconds=120,
            ),
            1: RenderNodeCardModel(
                node=1,
                status="rendering",
                price_per_hour=0.2,
                frames_done=1,
                frames_expected=35,
                eta_seconds=300,
            ),
        },
        started_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    viewmodel._runs = {run.run_id: run}
    viewmodel._locked_shots = {shot.relative_path}

    viewmodel.recalculate()
    summary = viewmodel.activity_summary()

    assert viewmodel.plan is not None and viewmodel.plan.total_frames == 0
    assert summary.active_runs == 1
    assert summary.nodes == 2
    assert summary.frames_done == 2
    assert summary.frames_expected == 70
    assert summary.gpu_hours > 1.9
    assert summary.cost > 0.3
    assert summary.eta_seconds == 300
    assert summary.shot_names == (shot.name,)
    assert summary.pending_plan is not None
    assert summary.pending_plan.total_frames == 0


def test_apply_offer_fix_updates_settings_and_retries(qapp, tmp_path, monkeypatch):
    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.settings = RenderSettings(min_cpu_ram_gb=32.0)
    refreshed = []
    monkeypatch.setattr(viewmodel, "_save_settings", lambda: None)
    monkeypatch.setattr(viewmodel, "recalculate", lambda: None)
    monkeypatch.setattr(
        viewmodel, "_refresh_vast_offer", lambda: refreshed.append(True) or True
    )

    assert viewmodel.apply_offer_fix("min_cpu_ram_gb", 31.0) is True

    assert viewmodel.settings.min_cpu_ram_gb == 31.0
    assert refreshed == [True]


def test_offer_blocked_keeps_structured_diagnostics(qapp, tmp_path):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    captured = []
    viewmodel.offer_diagnostics_ready.connect(captured.append)
    diagnostics = SimpleNamespace(message="No RTX 4070 offer meets all limits.")

    viewmodel._on_offer_blocked(diagnostics)

    assert viewmodel.offer is None
    assert viewmodel.offer_diagnostics is diagnostics
    assert captured == [diagnostics]


def test_effective_gpu_profile_uses_slowest_offer_in_ceiling_mode(qapp, tmp_path):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.settings = RenderSettings(
        render_backend="vast",
        gpu_profile="rtx_3080",
        fill_similar_gpus=True,
        similar_gpu_mode="ceiling",
        fill_allow_less_vram=True,
    )
    viewmodel.candidate_offers = [
        SimpleNamespace(gpu_profile="rtx_4070", gpu_name="RTX 4070"),
        SimpleNamespace(gpu_profile="rtx_3070", gpu_name="RTX 3070"),
    ]

    assert viewmodel.effective_gpu_profile() == "rtx_3070"

    viewmodel.settings = replace(viewmodel.settings, similar_gpu_mode="floor")
    assert viewmodel.effective_gpu_profile() == "rtx_3080"


def test_mixed_offer_cost_uses_each_node_price(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    shot = _shot()
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,),
        render_backend="vast",
        gpu_profile="rtx_3080",
        fill_similar_gpus=True,
        similar_gpu_mode="floor",
    )
    viewmodel.offer = SimpleNamespace(price_per_hour=0.1)
    viewmodel.candidate_offers = [
        SimpleNamespace(
            gpu_profile="rtx_3080",
            gpu_label="RTX 3080 10 GB",
            gpu_name="RTX 3080",
            price_per_hour=0.1,
            gpu_ram_gb=10.0,
        ),
        SimpleNamespace(
            gpu_profile="rtx_3090",
            gpu_label="RTX 3090 24 GB",
            gpu_name="RTX 3090",
            price_per_hour=0.2,
            gpu_ram_gb=24.0,
        ),
    ]
    fake_plan = RenderPlan(
        shots=(shot,),
        skipped=(),
        unmeasured=(),
        gpu_profile="rtx_3080",
        target_seconds=3600.0,
        utilization=0.85,
        setup_seconds=600.0,
        price_per_hour=0.1,
        total_gpu_seconds=1000.0,
        required_nodes=2,
        estimated_wall_seconds=3600.0,
        estimated_cost=0.1,
        confidence="measured",
        warnings=(),
    )
    monkeypatch.setattr(viewmodel.service, "plan", lambda *a, **k: fake_plan)
    monkeypatch.setattr(viewmodel, "_save_settings", lambda: None)

    viewmodel.recalculate()

    assert viewmodel.plan.estimated_cost == (0.1 + 0.2)
    assert any("same or faster" in item for item in viewmodel.plan.warnings)


def test_start_render_blocks_when_offers_are_short(qapp, tmp_path):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    shot = _shot()
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,), render_backend="vast"
    )
    viewmodel.offer = SimpleNamespace(price_per_hour=0.1)
    viewmodel.candidate_offers = [SimpleNamespace(id=1)]
    errors = []
    viewmodel.render_error.connect(errors.append)
    fake_plan = SimpleNamespace(
        shots=(shot,),
        total_frames=96,
        required_nodes=8,
        estimated_cost=1.0,
    )

    assert viewmodel._start_render_plan(fake_plan) is False
    assert "Only 1 of 8 node offers" in errors[0]


def test_fill_with_similar_profiles_enables_opt_in_and_retries(
    qapp, tmp_path, monkeypatch
):
    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.settings = RenderSettings(render_backend="vast")
    started = []
    monkeypatch.setattr(viewmodel, "_save_settings", lambda: None)
    monkeypatch.setattr(viewmodel, "recalculate", lambda: None)
    monkeypatch.setattr(
        viewmodel, "refresh_candidates", lambda: started.append("refresh") or True
    )

    assert (
        viewmodel.fill_with_similar_profiles("ceiling", allow_less_vram=True)
        is True
    )

    assert viewmodel.settings.fill_similar_gpus is True
    assert viewmodel.settings.similar_gpu_mode == "ceiling"
    assert viewmodel.settings.fill_allow_less_vram is True
    assert started == ["refresh"]


def test_staging_estimate_excludes_bake_caches_when_enabled(
    qapp, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.settings = RenderSettings(
        render_backend="vast", bake_geometry_nodes=True
    )
    shot = replace(
        _shot(),
        geometry_bakes=(
            SimpleNamespace(cache_dir_name="blendcache_sh010"),
        ),
    )
    captured = {}

    def fake_staging(root, *, exclude_names=(), shots=None):
        captured["exclude_names"] = tuple(exclude_names)
        captured["shots"] = list(shots or ())
        return SimpleNamespace(bytes=1, files=1, exists=True, entries=())

    monkeypatch.setattr(viewmodel.service, "staging_estimate", fake_staging)

    result = viewmodel.staging_estimate([shot])

    assert result is not None
    assert captured["exclude_names"] == ("blendcache_sh010",)


def test_select_project_does_not_rescan_automatically(qapp, tmp_path, monkeypatch):
    viewmodel = RenderPanelViewModel(RenderService())
    scans = []
    monkeypatch.setattr(viewmodel, "scan", lambda **kwargs: scans.append(kwargs) or True)
    monkeypatch.setattr(viewmodel.service, "cached_shots", lambda *a, **k: None)

    viewmodel.select_project("p0005", "id", tmp_path)

    assert scans == []


def test_cached_shots_emit_the_cache_notice(qapp, tmp_path, monkeypatch):
    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    viewmodel.settings = RenderSettings()
    notices = []
    viewmodel.shots_cache_loaded.connect(notices.append)
    monkeypatch.setattr(
        viewmodel.service, "cached_shots", lambda *a, **k: [_shot()]
    )
    monkeypatch.setattr(viewmodel, "recalculate", lambda: None)
    monkeypatch.setattr(viewmodel, "_emit_shot_reviews", lambda: None)
    monkeypatch.setattr(viewmodel, "_save_settings", lambda: None)

    viewmodel._load_cached_shots()

    assert notices == [True]


def test_shot_scan_keeps_the_current_vast_state(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    offer = SimpleNamespace(gpu_name="RTX 3080", price_per_hour=0.12)
    candidates = [offer]
    viewmodel.offer = offer
    viewmodel.balance = 12.0
    viewmodel.candidate_offers = candidates
    monkeypatch.setattr(viewmodel, "recalculate", lambda: None)
    monkeypatch.setattr(viewmodel, "_emit_shot_reviews", lambda: None)
    monkeypatch.setattr(viewmodel, "_save_settings", lambda: None)
    monkeypatch.setattr(viewmodel, "_write_status", lambda **kwargs: None)
    plan = RenderPlan(
        shots=(),
        skipped=(),
        unmeasured=(),
        gpu_profile="rtx_3080",
        target_seconds=3600.0,
        utilization=0.85,
        setup_seconds=600.0,
        price_per_hour=0.0,
        total_gpu_seconds=0.0,
        required_nodes=0,
        estimated_wall_seconds=0.0,
        estimated_cost=0.0,
        confidence="measured",
    )

    viewmodel._on_scan_shots_ready([], plan, None, 0.0, [])

    assert viewmodel.offer is offer
    assert viewmodel.balance == 12.0
    assert viewmodel.candidate_offers == candidates


def test_burst_frame_progress_emits_live_frame(qapp):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel._ensure_node_card("", 2)
    live = []
    viewmodel.live_frame_ready.connect(
        lambda shot, frame, path, node: live.append((shot, frame, path, node))
    )

    viewmodel._on_burst_progress_status(
        SimpleNamespace(
            node=2,
            stage="frame",
            message='{"frame": 120, "seconds": 60.0}',
            frames_done=1,
            frames_total=22,
            instance_id=77,
            gpu_name="RTX 3090",
            region="US",
            price_per_hour=0.2,
            offer_id=10,
            shot="sh040",
            frame=120,
            live_frame_path="/tmp/live/frame_0120.png",
        )
    )

    assert live == [
        ("sh040", 120, "/tmp/live/frame_0120.png", 2)
    ]


def test_clear_queued_relaunch_removes_only_that_run(qapp, tmp_path):
    from datetime import datetime, timezone

    from src.interfaces.qt.viewmodels.render_panel_viewmodel import (
        RenderNodeCardModel,
        RenderRunState,
    )

    viewmodel = RenderPanelViewModel(RenderService())
    viewmodel.project_root = tmp_path
    shot = _shot()
    plan = viewmodel._plan_for_shots([shot])
    card = RenderNodeCardModel(
        node=6,
        status="queued",
        run_id="relaunch-run",
        run_label="relaunch",
        assignment=((shot.relative_path, (101,)),),
    )
    run = RenderRunState(
        run_id="relaunch-run",
        backend="vast",
        plan=plan,
        gpu_profile="rtx_3080",
        cards={6: card},
        label="relaunch",
        relaunch_key=card.key,
        started_at=datetime.now(timezone.utc),
    )
    viewmodel._runs = {run.run_id: run}
    viewmodel._relaunch_active = {card.key}
    viewmodel.node_cards = [card]

    assert viewmodel.clear_queued_relaunch(card) is True
    assert "relaunch-run" not in viewmodel._runs
    assert card.key not in viewmodel._relaunch_active
    assert card.status == "failed"


def test_dependencies_audited_updates_the_shot_list(qapp, monkeypatch):
    from dataclasses import replace

    viewmodel = RenderPanelViewModel(RenderService())
    old = _shot()
    viewmodel.shots = [old]
    viewmodel.settings = RenderSettings(selected_shots=(old.relative_path,))
    monkeypatch.setattr(viewmodel, "recalculate", lambda: None)
    monkeypatch.setattr(viewmodel, "_emit_shot_reviews", lambda: None)
    updated = replace(
        old,
        dependencies_audited=True,
        dependencies=("02_archivos_de_produccion/pro/assets/studio.hdr",),
    )

    viewmodel._on_dependencies_audited([updated])

    assert viewmodel.shots[0].dependencies_audited is True
    assert viewmodel.shots[0].dependencies == (
        "02_archivos_de_produccion/pro/assets/studio.hdr",
    )


def test_dependency_blocking_can_be_toggled_off(qapp, monkeypatch):
    from dataclasses import replace as dataclass_replace

    from src.domain.render.models import DependencyIssue

    viewmodel = RenderPanelViewModel(RenderService())
    shot = replace(
        _shot(),
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
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(selected_shots=(shot.relative_path,))
    monkeypatch.setattr(viewmodel, "recalculate", lambda: None)

    assert len(viewmodel.blocking_dependency_issues()) == 1

    viewmodel.set_dependency_blocking(
        shot.dependency_issues[0], False
    )

    assert viewmodel.blocking_dependency_issues() == []


def test_preview_creates_a_node_card_and_tracks_progress(
    qapp, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    viewmodel = RenderPanelViewModel(RenderService())
    shot = _shot()
    viewmodel.project_root = tmp_path
    viewmodel.shots = [shot]
    viewmodel.settings = RenderSettings(
        selected_shots=(shot.relative_path,), preview_backend="local"
    )
    monkeypatch.setattr(
        viewmodel.workers, "start", lambda *args, **kwargs: True
    )

    assert viewmodel.preview_shots([shot]) is True

    card = viewmodel._preview_cards[0]
    assert card.run_label == "preview"
    assert card.frames_expected == 1
    assert card.frames_done == 0
    assert card.status == "queued"

    viewmodel._on_preview_progress_status("sh010", 1, 1, 2.5)
    assert card.current_shot == "sh010"
    assert card.status == "rendering"
    assert card.seconds_per_frame == 2.5

    viewmodel.preview_paths = {}
    monkeypatch.setattr(viewmodel, "_save_preview_index", lambda: None)
    monkeypatch.setattr(viewmodel, "_write_status", lambda **kwargs: None)
    monkeypatch.setattr(viewmodel, "preview_ready", SimpleNamespace(emit=lambda *a: None))
    viewmodel._on_preview_ready("sh010", str(tmp_path / "frame.png"))
    assert card.frames_done == 1
    assert card.progress_percent == 100.0

    viewmodel._finish_audit = lambda *a, **k: None
    viewmodel.preview_running = SimpleNamespace(emit=lambda *a: None)
    viewmodel.preview_finished = SimpleNamespace(emit=lambda *a: None)
    viewmodel._write_status = lambda **kwargs: None
    viewmodel._on_previews_finished(1, 1, [], None)
    assert card.status == "completed"
    assert card.final is True
