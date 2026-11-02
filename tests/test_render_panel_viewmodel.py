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
