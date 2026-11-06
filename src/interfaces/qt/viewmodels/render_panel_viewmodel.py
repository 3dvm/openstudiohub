# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/render_panel_viewmodel.py
# Architectural role: MVVM ViewModel / dedicated render panel
# =========================================================================================

"""ViewModel for the dedicated render panel.

It owns the project/shot selection, the shared render settings, the plan, the
preview, the local or Vast render and the review video. The View only renders
widgets and forwards user actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Signal

from src.application.services.launch_service import LaunchService
from src.application.services.render_service import RenderService
from src.application.services.task_file_sync_service import TaskFileSyncService
from src.domain.render.models import RenderPlan, RenderSettings, RenderShot
from src.infrastructure.render.run_audit import RenderRunAuditLogger
from src.infrastructure.render.status import RenderStatusStore
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.viewmodels.vcs_credential_gate import (
    VcsPrompt,
    ensure_vcs_credentials,
    vcs_requires_credentials,
)
from src.interfaces.qt.workers.render_workers import (
    KitsuStatusesWorker,
    KitsuUploadWorker,
    LocalRenderWorker,
    RenderBenchmarkWorker,
    RenderBurstWorker,
    RenderCandidatesWorker,
    OpenShotBlendWorker,
    RenderPanelScanWorker,
    RenderPreviewVideoWorker,
    RenderPreviewWorker,
    RenderVideoWorker,
)
from src.interfaces.qt.workers.worker_manager import WorkerManager


@dataclass
class RenderNodeCardModel:
    node: int
    status: str = "candidate"
    message: str = ""
    instance_id: int = 0
    gpu_name: str = ""
    region: str = ""
    price_per_hour: float = 0.0
    reliability: float = 0.0
    down_mbps: float = 0.0
    up_mbps: float = 0.0
    offer_id: int = 0
    frames_done: int = 0
    frames_expected: int = 0
    cost: float = 0.0
    stage: str = ""
    hub_logs: tuple[Path, ...] = field(default_factory=tuple)
    summary_logs: tuple[Path, ...] = field(default_factory=tuple)
    blender_logs: tuple[Path, ...] = field(default_factory=tuple)
    final: bool = False


@dataclass
class ShotReviewModel:
    name: str
    sequence: str
    status: str
    status_label: str
    status_tooltip: str
    selected: bool
    locked: bool
    ready: bool
    frames: int
    rendered: int
    approved: int
    missing: int
    frame_range: str
    engine: str
    resolution: str
    samples: int
    measured_seconds: float | None
    warnings: tuple[str, ...]
    relative_path: str


SHOT_STATUS_TOOLTIPS = {
    "not_ready": (
        "The shot has no camera, no geometry or an invalid frame range. "
        "It cannot be rendered."
    ),
    "check_setup": (
        "The shot is renderable, but the compositor or view layers are incomplete. "
        "Review the setup before rendering."
    ),
    "rendering": "This shot is part of the active run and is being rendered right now.",
    "queued": "This shot is selected for the active run and waiting for a node.",
    "failed": "The last render attempt for this shot failed before writing frames.",
    "finished": "Every expected frame is rendered and approved.",
    "in_review": (
        "Every expected frame is rendered, but some frames are still waiting "
        "for approval."
    ),
    "with_renders": (
        "Some frames are rendered. Rendered and approved counts show the progress."
    ),
    "ready": "The shot is ready to render and has no rendered frames yet.",
}

_SHOT_STATUS_LABELS = {
    "not_ready": "Not ready",
    "check_setup": "Check setup",
    "rendering": "Rendering",
    "queued": "Queued",
    "failed": "Failed",
    "finished": "Finished",
    "in_review": "In review",
    "with_renders": "With renders",
    "ready": "Ready",
}


_STAGE_TO_STATUS = {
    "offer": "creating",
    "create": "creating",
    "boot": "booting",
    "ssh": "ssh",
    "setup": "installing",
    "stage": "staging",
    "render": "rendering",
    "frame": "rendering",
    "sync": "syncing",
    "bake": "baking",
    "validate": "validating",
    "destroy": "destroyed",
}


class RenderPanelViewModel(BaseViewModel):
    shots_ready = Signal(list, object, object, float, list)
    shot_reviews_ready = Signal(list)
    node_cards_ready = Signal(list)
    node_card_updated = Signal(int)
    scan_progress = Signal(str, int, int)
    scan_error = Signal(str)

    preview_ready = Signal(str, str)
    preview_progress = Signal(str, int, int, float)
    preview_error = Signal(str)
    preview_finished = Signal(int, int, list, object)

    benchmark_progress = Signal(object)
    benchmark_finished = Signal(str, float)
    benchmark_error = Signal(str)

    burst_progress = Signal(object)
    local_render_progress = Signal(str, int, int, float)
    render_finished = Signal(object)
    render_error = Signal(str)

    video_ready = Signal(str, str)
    video_error = Signal(str)
    videos_finished = Signal(int, int)
    preview_video_ready = Signal(str, str)

    kitsu_statuses_ready = Signal(list)
    kitsu_status_error = Signal(str)
    kitsu_upload_finished = Signal(bool, str)
    shot_launch_finished = Signal(str, bool, str)  # (relative path, ok, message)

    def __init__(
        self,
        service: RenderService,
        production_service=None,
        status_sink: StatusSink | None = None,
        parent=None,
        *,
        config_factory=None,
        auth_service=None,
        credential_vault=None,
        vcs_prompt: VcsPrompt | None = None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.service = service
        self.production_service = production_service
        self.config_factory = config_factory
        self.auth_service = auth_service
        self.credential_vault = credential_vault
        self.vcs_prompt = vcs_prompt
        self.task_file_sync_service = (
            TaskFileSyncService(config_factory) if config_factory is not None else None
        )
        self.launch_service = (
            LaunchService(config_factory) if config_factory is not None else None
        )
        self.workers = WorkerManager(self)
        self.burst_progress.connect(self._on_burst_progress_status)
        self.local_render_progress.connect(self._on_local_progress_status)
        self.scan_error.connect(self._on_error_status)
        self.preview_error.connect(self._on_error_status)
        self.render_error.connect(self._on_error_status)

        self.project_name = ""
        self.project_id = ""
        self.project_root: Path | None = None
        self.settings = RenderSettings()
        self.shots: list[RenderShot] = []
        self.plan: RenderPlan | None = None
        self.offer = None
        self.balance = 0.0
        self.preview_paths: dict[str, Path] = {}
        self.video_paths: dict[str, Path] = {}
        self.kitsu_statuses: list[dict] = []
        self.read_only = False
        self.status_store: RenderStatusStore | None = None
        self.audit = RenderRunAuditLogger()
        self._active_run_id = ""
        self.last_burst_report = None
        self.preview_video_paths: dict[str, Path] = {}
        self.node_cards: list[RenderNodeCardModel] = []
        self.candidate_offers: list = []
        self._progress_by_shot: dict[str, int] = {}
        self._progress_by_node: dict[int, int] = {}
        self._locked_shots: set[str] = set()
        self._failed_shots: set[str] = set()
        self.last_preview_failed: list[str] = []
        self.last_preview_report = None

    # ------------------------------------------------------------------
    # Project / settings
    # ------------------------------------------------------------------
    def select_project(
        self,
        project_name: str,
        project_id: str,
        project_root: Path,
        *,
        read_only: bool = False,
    ) -> None:
        self.project_name = project_name
        self.project_id = project_id
        self.project_root = Path(project_root)
        self.read_only = read_only
        self.status_store = RenderStatusStore.for_project(self.project_root)
        self._progress_by_shot = {}
        self._progress_by_node = {}
        self.shots = []
        self.plan = None
        self.offer = None
        self.preview_paths = {}
        self.video_paths = {}
        self.node_cards = []
        self.candidate_offers = []
        self._locked_shots = set()
        self._failed_shots = set()
        self.node_cards_ready.emit([])
        self.shot_reviews_ready.emit([])
        try:
            self.settings = self.service.load_settings(self.project_root)
        except Exception:  # noqa: BLE001
            self.settings = RenderSettings()
        if not read_only:
            self._write_status(status="idle", message="Render panel loaded.")
            self.scan()
        else:
            self.report_status("Render panel loaded in read-only mode.", "white")

    @property
    def selected_shots(self) -> list[RenderShot]:
        return self.service.selected_shots(self.shots, self.settings)

    def update_settings(self, settings: RenderSettings) -> None:
        self.settings = settings
        self._save_settings()

    def set_selected_shots(self, relative_paths: list[str]) -> None:
        requested = set(relative_paths or ())
        requested.update(self._locked_shots)
        self.settings = replace(
            self.settings, selected_shots=tuple(sorted(requested))
        )
        self._save_settings()
        self.recalculate()
        self._emit_shot_reviews()

    def _save_settings(self) -> None:
        if self.project_root is None:
            return
        try:
            self.service.save_settings(self.project_root, self.settings)
        except Exception as error:  # noqa: BLE001
            self.report_status(f"Could not save render settings: {error}", "red")

    # ------------------------------------------------------------------
    # Scan / plan
    # ------------------------------------------------------------------
    def scan(self) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("render_scan"):
            return False
        worker = RenderPanelScanWorker(
            self.service, self.project_root, self.settings
        )
        worker.scan_progress.connect(self.scan_progress)
        worker.shots_ready.connect(self._on_shots_ready)
        worker.error.connect(self.scan_error)
        self.set_busy(True)
        self.report_status("Scanning shots and render setup...", "yellow")
        return self.workers.start("render_scan", worker)

    def _on_shots_ready(
        self, shots: list, plan: RenderPlan, offer, balance: float, candidates: list
    ) -> None:
        self.set_busy(False)
        self.shots = list(shots)
        self.plan = plan
        self.offer = offer
        self.balance = balance
        if not self.settings.selected_shots:
            ready = [shot.relative_path for shot in self.shots if shot.is_ready]
            self.settings = replace(self.settings, selected_shots=tuple(ready))
            self._save_settings()
            if ready:
                selected = self.service.selected_shots(self.shots, self.settings)
                pending = self.service.pending_shots(
                    self.project_root, selected, task_type=self.settings.task_type
                )
                price = offer.price_per_hour if offer is not None else 0.0
                self.plan = self._with_offer_warning(
                    self.service.adjust_plan_for_backend(
                        self.service.plan(
                            self.project_root,
                            target_hours=self.settings.target_hours,
                            gpu_profile=self.settings.gpu_profile,
                            quality_override=self.settings.final_quality,
                            price_per_hour=price,
                            max_nodes=self.settings.max_nodes,
                            budget=self.settings.budget,
                            shots=pending,
                        ),
                        self.settings.render_backend,
                        self.settings.local_speed_factor,
                    )
                )
                plan = self.plan
        self._write_status(
            status="ready",
            message="Render plan ready.",
            frames_expected=plan.total_frames,
            frames_done=0,
            nodes=plan.required_nodes,
            cost=plan.estimated_cost,
        )
        self.candidate_offers = list(candidates or [])
        self._build_node_cards(plan)
        self.report_status("Render plan ready.", "green")
        self.shots_ready.emit(self.shots, plan, offer, balance, self.candidate_offers)
        self._emit_shot_reviews()

    def is_shot_locked(self, shot: RenderShot) -> bool:
        return shot.relative_path in self._locked_shots

    def shot_reviews(self) -> list[ShotReviewModel]:
        return [self._shot_review(shot) for shot in self.shots]

    def _emit_shot_reviews(self) -> None:
        self.shot_reviews_ready.emit(self.shot_reviews())

    def _shot_review(self, shot: RenderShot) -> ShotReviewModel:
        rendered, expected = self.shot_progress(shot)
        approved = 0
        if self.project_root is not None:
            try:
                approved = len(
                    self.service.frame_state_store(
                        self.project_root, shot, self.settings.task_type
                    ).approved_frames()
                )
            except Exception:  # noqa: BLE001
                approved = 0
        missing = max(0, expected - rendered)
        quality = shot.quality
        status = self._shot_status(shot, rendered, approved, expected)
        warnings = list(shot.warnings)
        setup = shot.setup
        if setup is not None:
            warnings.extend(setup.warnings or ())
        resolution = (
            f"{quality.effective_width}×{quality.effective_height} "
            f"({quality.resolution_percentage}%)"
        )
        return ShotReviewModel(
            name=shot.name,
            sequence=shot.sequence or "shots",
            status=status,
            status_label=_SHOT_STATUS_LABELS.get(status, status.title()),
            status_tooltip=SHOT_STATUS_TOOLTIPS.get(status, ""),
            selected=shot.relative_path in (self.settings.selected_shots or ()),
            locked=self.is_shot_locked(shot),
            ready=shot.is_ready,
            frames=expected,
            rendered=rendered,
            approved=approved,
            missing=missing,
            frame_range=f"{shot.frame_start}–{shot.frame_end} "
            f"(step {max(1, shot.frame_step)})",
            engine=quality.engine,
            resolution=resolution,
            samples=int(quality.samples),
            measured_seconds=shot.measured_seconds,
            warnings=tuple(warnings),
            relative_path=shot.relative_path,
        )

    def _shot_status(
        self, shot: RenderShot, rendered: int, approved: int, expected: int
    ) -> str:
        if not shot.is_ready:
            return "not_ready"
        setup = shot.setup
        if setup is not None and not setup.is_compositing_ready:
            return "check_setup"
        if self.is_shot_locked(shot):
            return "rendering"
        if shot.relative_path in self._failed_shots:
            return "failed"
        if expected > 0 and approved >= expected:
            return "finished"
        if expected > 0 and rendered >= expected:
            return "in_review"
        if rendered > 0:
            return "with_renders"
        return "ready"

    def _shot_by_path(self, relative_path: str) -> RenderShot | None:
        for shot in self.shots:
            if shot.relative_path == relative_path:
                return shot
        return None

    def _rendered_frames(self, shot: RenderShot) -> list[int]:
        if self.project_root is None:
            return []
        folder = self.service.shot_output_dir(
            self.project_root, shot, self.settings.task_type
        )
        step = max(1, int(shot.frame_step or 1))
        return [
            frame
            for frame in range(shot.frame_start, shot.frame_end + 1, step)
            if (folder / f"frame_{frame:04d}.png").is_file()
        ]

    def render_single_shot(self, shot: RenderShot) -> bool:
        if self.is_shot_locked(shot) or self.workers.is_running("render_burst") or self.workers.is_running("render_local"):
            self.render_error.emit("That shot is already rendering or a render is running.")
            return False
        self.settings = replace(
            self.settings, selected_shots=(shot.relative_path,)
        )
        self._save_settings()
        self.recalculate()
        self._emit_shot_reviews()
        return self.start_render()

    def retry_missing_shot(self, shot: RenderShot) -> bool:
        if self.is_shot_locked(shot) or self.workers.is_running("render_burst") or self.workers.is_running("render_local"):
            self.render_error.emit("That shot is already rendering or a render is running.")
            return False
        self.settings = replace(
            self.settings, selected_shots=(shot.relative_path,)
        )
        self._save_settings()
        self.recalculate()
        self._emit_shot_reviews()
        return self.start_render(retry=True)

    def approve_all_rendered(self, shot: RenderShot) -> tuple[bool, str]:
        frames = self._rendered_frames(shot)
        if not frames:
            return False, "The shot has no rendered frames."
        result = self.approve_frames(shot, frames, True)
        self._emit_shot_reviews()
        return result

    def unapprove_all(self, shot: RenderShot) -> tuple[bool, str]:
        if self.project_root is None:
            return False, "The panel has no project."
        approved = sorted(
            self.service.frame_state_store(
                self.project_root, shot, self.settings.task_type
            ).approved_frames()
        )
        if not approved:
            return False, "The shot has no approved frames."
        result = self.approve_frames(shot, approved, False)
        self._emit_shot_reviews()
        return result

    def delete_unapproved(self, shot: RenderShot) -> tuple[bool, str]:
        if self.project_root is None:
            return False, "The panel has no project."
        approved = self.service.frame_state_store(
            self.project_root, shot, self.settings.task_type
        ).approved_frames()
        frames = [frame for frame in self._rendered_frames(shot) if frame not in approved]
        if not frames:
            return False, "There are no unapproved rendered frames."
        ok, message, _deleted = self.delete_frames(shot, frames)
        self._emit_shot_reviews()
        return ok, message

    def _build_node_cards(self, plan: RenderPlan) -> None:
        if self.settings.render_backend == "local":
            cards = [
                RenderNodeCardModel(
                    node=0,
                    status="candidate",
                    message="Runs on this workstation.",
                    gpu_name="Local workstation",
                    final=True,
                )
            ]
        else:
            cards = []
            for index in range(max(0, int(plan.required_nodes))):
                offer = (
                    self.candidate_offers[index]
                    if index < len(self.candidate_offers)
                    else None
                )
                if offer is None:
                    cards.append(
                        RenderNodeCardModel(
                            node=index,
                            status="candidate",
                            message="No candidate offer.",
                        )
                    )
                    continue
                cards.append(
                    RenderNodeCardModel(
                        node=index,
                        status="candidate",
                        message="Candidate offer.",
                        gpu_name=str(getattr(offer, "gpu_name", "") or ""),
                        region=str(getattr(offer, "geolocation", "") or ""),
                        price_per_hour=float(getattr(offer, "price_per_hour", 0.0) or 0.0),
                        reliability=float(getattr(offer, "reliability", 0.0) or 0.0),
                        down_mbps=float(getattr(offer, "inet_down_mbps", 0.0) or 0.0),
                        up_mbps=float(getattr(offer, "inet_up_mbps", 0.0) or 0.0),
                        offer_id=int(getattr(offer, "id", 0) or 0),
                    )
                )
        self.node_cards = cards
        self.node_cards_ready.emit(list(cards))

    def refresh_candidates(self) -> bool:
        if (
            self.project_root is None
            or self.read_only
            or self.plan is None
            or self.settings.render_backend != "vast"
        ):
            return False
        if self.workers.is_running("render_candidates"):
            return False
        worker = RenderCandidatesWorker(
            self.service,
            self.plan.required_nodes,
            self.settings,
        )
        worker.candidates_ready.connect(self._on_candidates_ready)
        worker.error.connect(self.scan_error)
        self.report_status("Refreshing Vast.ai candidate offers...", "yellow")
        return self.workers.start("render_candidates", worker)

    def _on_candidates_ready(self, candidates: list) -> None:
        self.candidate_offers = list(candidates or [])
        if self.plan is not None:
            self._build_node_cards(self.plan)
        self.report_status("Candidate offers refreshed.", "green")

    def _ensure_node_card(self, index: int) -> RenderNodeCardModel:
        while len(self.node_cards) <= index:
            self.node_cards.append(
                RenderNodeCardModel(node=len(self.node_cards), status="queued")
            )
        return self.node_cards[index]

    def _mark_cards_queued(self) -> None:
        for card in self.node_cards:
            card.status = "queued"
            card.final = False
            card.message = "Waiting for a node."
            card.instance_id = 0
            card.frames_done = 0
            card.frames_expected = 0
            card.cost = 0.0
            card.hub_logs = ()
            card.summary_logs = ()
            card.blender_logs = ()
        self.node_cards_ready.emit(list(self.node_cards))

    def recalculate(self) -> None:
        if not self.shots or self.project_root is None:
            return
        selected = self.selected_shots
        pending = self.service.pending_shots(
            self.project_root, selected, task_type=self.settings.task_type
        )
        price = self.offer.price_per_hour if self.offer is not None else 0.0
        self.plan = self._with_offer_warning(
            self.service.adjust_plan_for_backend(
                self.service.plan(
                    self.project_root,
                    target_hours=self.settings.target_hours,
                    gpu_profile=self.settings.gpu_profile,
                    quality_override=self.settings.final_quality,
                    price_per_hour=price,
                    max_nodes=self.settings.max_nodes,
                    budget=self.settings.budget,
                    shots=pending,
                ),
                self.settings.render_backend,
                self.settings.local_speed_factor,
            )
        )
        self._build_node_cards(self.plan)
        self.shots_ready.emit(
            self.shots, self.plan, self.offer, self.balance, self.candidate_offers
        )

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def preview_shots(self, shots: list[RenderShot] | None = None) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("render_preview"):
            return False
        if (
            self.workers.is_running("render_burst")
            or self.workers.is_running("render_local")
            or self.workers.is_running("render_benchmark")
        ):
            self.preview_error.emit("A render process is already running.")
            return False
        targets = list(shots or self.selected_shots)
        if not targets:
            return False
        if self.settings.preview_backend == "vast" and self.offer is None:
            self.preview_error.emit(
                "Scan with the Vast backend before using Vast previews."
            )
            return False
        import uuid

        self._active_run_id = uuid.uuid4().hex[:12]
        backend = (
            "vast" if self.settings.preview_backend == "vast" else "local"
        )
        self.audit.log(
            "run_start",
            run_id=self._active_run_id,
            backend=f"preview-{backend}",
            project=self.project_name,
            frames=len(targets),
            nodes=1 if backend == "vast" else 0,
        )
        worker = RenderPreviewWorker(
            self.service,
            self.project_root,
            targets,
            self.settings,
            offer=self.offer,
            audit=self.audit,
            run_id=self._active_run_id,
        )
        worker.preview_ready.connect(self._on_preview_ready)
        worker.preview_progress.connect(self.preview_progress)
        worker.burst_progress.connect(self.burst_progress)
        worker.finished_previews.connect(self._on_previews_finished)
        self.set_busy(True)
        self._write_status(
            status="previewing",
            backend=backend,
            message="Rendering previews.",
            frames_expected=len(targets),
            frames_done=0,
            nodes=1 if backend == "vast" else 0,
            cost=0.0,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        location = "on Vast.ai" if backend == "vast" else "locally"
        self.report_status(
            f"Rendering {len(targets)} preview(s) {location}...", "yellow"
        )
        return self.workers.start("render_preview", worker)

    def _on_preview_ready(self, shot_name: str, image_path: str) -> None:
        path = Path(image_path)
        self.preview_paths[shot_name] = path
        self._write_status(preview=str(path))
        self.preview_ready.emit(shot_name, str(path))

    def _on_previews_finished(
        self, rendered: int, total: int, failed: list, report
    ) -> None:
        self.set_busy(False)
        self._finish_audit(
            ok=not failed,
            message=f"Previews finished ({rendered}/{total}).",
        )
        self.last_preview_failed = list(failed or [])
        self.last_preview_report = report
        self._write_status(
            status="ready" if not failed else "failed",
            message=f"Previews finished ({rendered}/{total}).",
            frames_done=rendered,
            frames_expected=total,
            cost=getattr(report, "cost", 0.0) if report is not None else 0.0,
        )
        self.preview_finished.emit(rendered, total, list(failed or []), report)

    def retry_failed_previews(self) -> bool:
        failed = set(self.last_preview_failed)
        targets = [shot for shot in self.shots if shot.name in failed]
        if not targets:
            return False
        return self.preview_shots(targets)

    def benchmark_selected(self, shot: RenderShot | None = None) -> bool:
        if self.project_root is None or self.read_only or not self.shots:
            self.benchmark_error.emit(
                "Scan the project and select a shot before benchmarking."
            )
            return False
        shot = shot or self.selected_shot()
        if shot is None:
            self.benchmark_error.emit("Select a shot to benchmark.")
            return False
        if (
            self.workers.is_running("render_benchmark")
            or self.workers.is_running("render_preview")
            or self.workers.is_running("render_burst")
            or self.workers.is_running("render_local")
        ):
            self.benchmark_error.emit("Another render process is already running.")
            return False
        worker = RenderBenchmarkWorker(
            self.service, self.project_root, shot, self.settings, self.offer
        )
        worker.benchmark_progress.connect(self.benchmark_progress)
        worker.benchmark_finished.connect(self._on_benchmark_finished)
        worker.error.connect(self.benchmark_error)
        self.set_busy(True)
        self.report_status(
            f"Benchmarking {shot.name} on a Vast.ai node...", "yellow"
        )
        return self.workers.start("render_benchmark", worker, critical=True)

    def selected_shot(self) -> RenderShot | None:
        if not self.shots:
            return None
        for shot in self.shots:
            if shot.relative_path in (self.settings.selected_shots or ()):
                return shot
        return self.shots[0]

    def _on_benchmark_finished(self, shot_name: str, median: float) -> None:
        self.set_busy(False)
        self.report_status(
            f"Benchmark for {shot_name}: {median:.1f} s/frame.", "green"
        )
        self.benchmark_finished.emit(shot_name, median)
        self.scan()

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def start_render(self, retry: bool = False) -> bool:
        if self.project_root is None or self.read_only or self.plan is None:
            return False
        if not self.plan.shots:
            self.render_error.emit("No shots selected for render.")
            return False
        if self.settings.render_backend == "vast" and self.offer is None:
            self.render_error.emit(
                "No Vast.ai offer within the price cap; raise the max price or use local."
            )
            return False
        if (
            self.workers.is_running("render_burst")
            or self.workers.is_running("render_local")
            or self.workers.is_running("render_preview")
            or self.workers.is_running("render_benchmark")
        ):
            self.render_error.emit("Another render process is already running.")
            return False
        self._mark_cards_queued()
        selected = self.service.selected_shots(self.shots, self.settings)
        self._locked_shots = {shot.relative_path for shot in selected}
        self._failed_shots.clear()
        self._emit_shot_reviews()
        if self.settings.render_backend == "local":
            self._start_audit("local")
            worker = LocalRenderWorker(
                self.service,
                self.project_root,
                list(self.plan.shots),
                self.settings,
                skip_existing=retry,
                audit=self.audit,
                run_id=self._active_run_id,
            )
            worker.render_progress.connect(self.local_render_progress)
            worker.finished_render.connect(self._on_local_finished)
            worker.error.connect(self.render_error)
            self.set_busy(True)
            self._progress_by_shot = {}
            self._progress_by_node = {}
            self._write_status(
                status="rendering",
                backend="local",
                message="Rendering locally.",
                frames_expected=self.plan.total_frames,
                frames_done=0,
                nodes=1,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            self.report_status(
                f"Rendering {self.plan.total_frames} frame(s) locally...", "yellow"
            )
            return self.workers.start("render_local", worker, critical=True)

        self._start_audit("vast")
        worker = RenderBurstWorker(
            self.service,
            self.project_root,
            self.plan,
            max_price_per_hour=self.settings.max_price_per_hour,
            preferred_region=self.settings.preferred_region,
            min_inet_down_mbps=self.settings.min_inet_down_mbps,
            min_inet_up_mbps=self.settings.min_inet_up_mbps,
            audit=self.audit,
            run_id=self._active_run_id,
            skip_existing=retry,
        )
        worker.burst_progress.connect(self.burst_progress)
        worker.report_ready.connect(self._handle_burst_finished)
        worker.error.connect(self.render_error)
        self.set_busy(True)
        self._progress_by_node = {}
        self._write_status(
            status="rendering",
            backend="vast",
            message="Starting Vast.ai nodes.",
            frames_expected=self.plan.total_frames,
            frames_done=0,
            nodes=self.plan.required_nodes,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.report_status(
            f"Starting {self.plan.required_nodes} Vast.ai node(s)...", "yellow"
        )
        return self.workers.start("render_burst", worker, critical=True)

    def _on_local_finished(self, reports: list) -> None:
        self.set_busy(False)
        rendered = sum(item.frames_rendered for item in reports)
        self._write_status(
            status="completed" if all(item.ok for item in reports) else "failed",
            message=f"Local render: {rendered} frame(s).",
            frames_done=rendered,
        )
        ok = bool(reports) and all(item.ok for item in reports)
        self._finish_audit(ok=ok, message="Local render finished.")
        self._update_local_cards(reports)
        self._finish_shot_run(ok, sum(item.frames_rendered for item in reports))
        self.render_finished.emit(reports)

    def _resolve_server(self, project_root: Path):
        getter = getattr(self.config_factory, "get_server_for_project", None)
        if callable(getter):
            try:
                server = getter(project_root)
                if server is not None:
                    return server
            except Exception:  # noqa: BLE001
                pass
        getter = getattr(self.config_factory, "get_default_server", None)
        return getter() if callable(getter) else None

    def _ensure_vcs_credentials(self, project_root=None):
        if self.credential_vault is None or self.config_factory is None:
            return ("", "")
        server = self._resolve_server(project_root)
        return ensure_vcs_credentials(
            required=vcs_requires_credentials(self.config_factory, server=server),
            server_id=server.id if server is not None else "",
            server_label=server.name if server is not None else "default",
            needs_passphrase=bool(server is not None and server.is_remote),
            credential_vault=self.credential_vault,
            prompt=self.vcs_prompt,
            report_status=self.report_status,
        )

    def open_shot_blend(self, shot: RenderShot) -> bool:
        """Open the shot blend with the task sandbox and SVN lock protocol."""
        if (
            self.project_root is None
            or self.config_factory is None
            or self.launch_service is None
            or self.task_file_sync_service is None
            or self.credential_vault is None
            or self.auth_service is None
        ):
            self.report_status("Opening the task environment is not available.", "red")
            return False
        if self.workers.is_running("shot_launch"):
            self.report_status("A Blender session is already being opened.", "red")
            return False
        creds = self._ensure_vcs_credentials(self.project_root)
        if creds is None:
            return False
        svn_user, svn_pwd = creds
        kitsu_user, kitsu_pwd = self.credential_vault.get_kitsu_credentials()
        if not kitsu_pwd:
            self.report_status(
                "Kitsu credentials are missing. Log out and log in again.", "red"
            )
            return False
        try:
            role = self.auth_service.current_role()
            user_role = getattr(role, "value", str(role or "artist"))
        except Exception:  # noqa: BLE001
            user_role = "artist"
        worker = OpenShotBlendWorker(
            config_factory=self.config_factory,
            launch_service=self.launch_service,
            sync_service=self.task_file_sync_service,
            production_service=self.production_service,
            project_root=self.project_root,
            project_id=self.project_id,
            project_name=self.project_name,
            shot=shot,
            svn_user=svn_user,
            svn_pwd=svn_pwd,
            kitsu_user=kitsu_user or "",
            kitsu_pwd=kitsu_pwd,
            user_role=user_role,
        )
        worker.status.connect(self.report_status)
        worker.finished_launch.connect(self._on_shot_launch_finished)
        self.report_status(f"Opening {shot.name} in Blender...", "yellow")
        return self.workers.start("shot_launch", worker, critical=True)

    def _on_shot_launch_finished(
        self, relative_path: str, ok: bool, message: str
    ) -> None:
        self.report_status(message, "green" if ok else "red")
        self.shot_launch_finished.emit(relative_path, ok, message)

    def cancel_render(self) -> None:
        for key in ("render_burst", "render_local", "render_preview"):
            worker = self.workers.get(key)
            if worker is not None and hasattr(worker, "cancel"):
                worker.cancel()

    def stop_all_processes(self) -> None:
        """Cancel every cancellable render-related worker."""
        self.cancel_render()
        for key in (
            "render_scan",
            "render_candidates",
            "render_benchmark",
            "render_video",
            "render_preview_video",
            "kitsu_upload",
        ):
            worker = self.workers.get(key)
            if worker is not None and hasattr(worker, "cancel"):
                worker.cancel()
        self.report_status("Stopping all render processes...", "yellow")

    def _handle_burst_finished(self, report) -> None:
        self.set_busy(False)
        self._write_status(
            status="completed" if getattr(report, "ok", False) else "failed",
            message=getattr(report, "message", "Render finished."),
            frames_done=getattr(report, "frames_rendered", 0),
            cost=getattr(report, "cost", 0.0),
        )
        self.last_burst_report = report
        self._finish_audit(
            ok=bool(getattr(report, "ok", False)),
            message=getattr(report, "message", ""),
        )
        self._update_burst_cards(report)
        self._finish_shot_run(
            bool(getattr(report, "ok", False)),
            int(getattr(report, "frames_rendered", 0)),
        )
        self.render_finished.emit(report)

    def _finish_shot_run(self, ok: bool, rendered: int) -> None:
        locked = set(self._locked_shots)
        if not ok and rendered <= 0:
            self._failed_shots.update(locked)
        else:
            self._failed_shots.difference_update(locked)
        self._locked_shots.clear()
        self._emit_shot_reviews()

    def _update_burst_cards(self, report) -> None:
        run_id = getattr(report, "run_id", self._active_run_id)
        for result in getattr(report, "nodes", ()) or ():
            card = self._ensure_node_card(int(result.node))
            card.status = "completed" if result.ok else "failed"
            card.message = result.message
            card.stage = result.stage
            card.instance_id = int(result.instance_id or 0)
            card.frames_done = int(result.frames_done or 0)
            card.frames_expected = int(result.frames_expected or 0)
            card.cost = float(result.cost or 0.0)
            card.gpu_name = result.gpu_name or card.gpu_name
            card.region = result.region or card.region
            card.price_per_hour = result.price_per_hour or card.price_per_hour
            card.hub_logs = (self.audit.node_log_path(run_id, result.node),)
            card.summary_logs = (
                self.audit.run_dir(run_id) / f"node-{result.node}.json",
            )
            card.blender_logs = tuple(Path(path) for path in result.blender_logs or ())
            card.final = True
            self.node_card_updated.emit(card.node)

    def _update_local_cards(self, reports: list) -> None:
        card = self._ensure_node_card(0)
        shots = list(self.plan.shots) if self.plan is not None else []
        hub_logs: list[Path] = []
        summary_logs: list[Path] = []
        blender_logs: list[Path] = []
        for index, report in enumerate(reports or []):
            shot = shots[index] if index < len(shots) else None
            if shot is None:
                continue
            node_id = f"local-{shot.name}"
            hub_logs.append(self.audit.node_log_path(self._active_run_id, node_id))
            summary_logs.append(
                self.audit.run_dir(self._active_run_id) / f"node-{node_id}.json"
            )
            blender_logs.append(
                self.audit.blender_log_path(self._active_run_id, node_id)
            )
        card.status = "completed" if not reports or all(item.ok for item in reports) else "failed"
        card.gpu_name = card.gpu_name or "Local workstation"
        card.frames_done = sum(item.frames_rendered for item in reports or [])
        card.frames_expected = sum(item.frames_expected for item in reports or [])
        card.message = "Local render finished."
        card.hub_logs = tuple(hub_logs)
        card.summary_logs = tuple(summary_logs)
        card.blender_logs = tuple(blender_logs)
        card.final = True
        self.node_card_updated.emit(0)

    def run_log_dir(self) -> Path:
        """Folder that contains the detailed node logs for the last run."""
        return self.audit.root

    def latest_log_path(self, report=None) -> Path:
        """Best log file to open for a completed run."""
        run_id = getattr(report, "run_id", "") or self._active_run_id
        for node in getattr(report, "nodes", ()) or ():
            for path in getattr(node, "remote_logs", ()) or ():
                candidate = Path(path)
                if candidate.is_file():
                    return candidate
            for path in getattr(node, "blender_logs", ()) or ():
                candidate = Path(path)
                if candidate.is_file():
                    return candidate
            candidate = self.audit.node_log_path(run_id, node.node)
            if candidate.is_file():
                return candidate
        candidate = self.audit.node_log_path(run_id, 0)
        if candidate.is_file():
            return candidate
        return self.audit.run_dir(run_id)

    def _start_audit(self, backend: str) -> None:
        import uuid

        self._active_run_id = uuid.uuid4().hex[:12]
        self.audit.log(
            "run_start",
            run_id=self._active_run_id,
            backend=backend,
            project=self.project_name,
            frames=self.plan.total_frames if self.plan else 0,
            nodes=self.plan.required_nodes if self.plan else 0,
            cost=self.plan.estimated_cost if self.plan else 0.0,
        )

    def _finish_audit(self, *, ok: bool, message: str) -> None:
        if not self._active_run_id:
            return
        self.audit.log(
            "run_finished",
            run_id=self._active_run_id,
            ok=bool(ok),
            message=str(message or ""),
        )

    # ------------------------------------------------------------------
    # Video
    # ------------------------------------------------------------------
    def create_review_videos(self, shots: list[RenderShot] | None = None) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("render_video"):
            return False
        targets = list(shots or (self.plan.shots if self.plan else self.selected_shots))
        if not targets:
            return False
        worker = RenderVideoWorker(
            self.service, self.project_root, targets, self.settings
        )
        worker.video_ready.connect(self._on_video_ready)
        worker.error.connect(self.video_error)
        worker.finished_videos.connect(self._on_videos_finished)
        self.report_status("Creating review video(s) with ffmpeg...", "yellow")
        return self.workers.start("render_video", worker, critical=True)

    def create_preview_videos(self, shots: list[RenderShot] | None = None) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("render_preview_video"):
            return False
        targets = list(shots or self.selected_shots)
        if not targets:
            return False
        worker = RenderPreviewVideoWorker(
            self.service, self.project_root, targets, self.settings
        )
        worker.video_ready.connect(self._on_preview_video_ready)
        worker.error.connect(self.video_error)
        worker.finished_videos.connect(self._on_videos_finished)
        self.report_status("Creating preview video(s) with ffmpeg...", "yellow")
        return self.workers.start("render_preview_video", worker, critical=True)

    def _on_video_ready(self, shot_name: str, video_path: str) -> None:
        path = Path(video_path)
        self.video_paths[shot_name] = path
        self._write_status(video=str(path))
        self.video_ready.emit(shot_name, str(path))

    def _on_preview_video_ready(self, shot_name: str, video_path: str) -> None:
        path = Path(video_path)
        self.preview_video_paths[shot_name] = path
        self.preview_video_ready.emit(shot_name, str(path))

    def _on_videos_finished(self, created: int, total: int) -> None:
        self.videos_finished.emit(created, total)

    # ------------------------------------------------------------------
    # Frame review (sequence player)
    # ------------------------------------------------------------------
    def shot_progress(self, shot: RenderShot) -> tuple[int, int]:
        if self.project_root is None:
            return 0, int(shot.frames)
        folder = self.service.shot_output_dir(
            self.project_root, shot, self.settings.task_type
        )
        step = max(1, int(shot.frame_step or 1))
        done = 0
        for frame in range(shot.frame_start, shot.frame_end + 1, step):
            if (folder / f"frame_{frame:04d}.png").is_file():
                done += 1
        return done, int(shot.frames)

    def sequence_entries(self, shot: RenderShot) -> list[tuple[int, Path | None]]:
        if self.project_root is None:
            return []
        return self.service.sequence_entries(
            self.project_root, shot, self.settings.task_type
        )

    def approved_frames(self, shot: RenderShot) -> set[int]:
        if self.project_root is None:
            return set()
        return self.service.frame_state_store(
            self.project_root, shot, self.settings.task_type
        ).approved_frames()

    def delete_frame(self, shot: RenderShot, frame: int) -> tuple[bool, str]:
        ok, message, _deleted = self.delete_frames(shot, [frame])
        return ok, message

    def delete_frames(self, shot: RenderShot, frames: list[int]):
        if self.project_root is None or self.read_only:
            return False, "The render panel is read-only.", ()
        result = self.service.delete_frames(
            self.project_root, shot, frames, self.settings.task_type
        )
        self.report_status(result[1], "green" if result[0] else "red")
        return result

    def approve_frame(
        self, shot: RenderShot, frame: int, approved: bool
    ) -> tuple[bool, str]:
        return self.approve_frames(shot, [frame], approved)

    def approve_frames(
        self, shot: RenderShot, frames: list[int], approved: bool
    ) -> tuple[bool, str]:
        if self.project_root is None or self.read_only:
            return False, "The render panel is read-only."
        result = self.service.approve_frames(
            self.project_root,
            shot,
            frames,
            approved,
            task_type=self.settings.task_type,
        )
        self.report_status(result[1], "green" if result[0] else "red")
        return result

    # ------------------------------------------------------------------
    # Kitsu
    # ------------------------------------------------------------------
    def load_kitsu_statuses(self) -> bool:
        if self.production_service is None or not self.project_id:
            return False
        if self.workers.is_running("kitsu_statuses"):
            return False
        worker = KitsuStatusesWorker(self.production_service, self.project_id)
        worker.statuses_ready.connect(self._on_kitsu_statuses)
        worker.error.connect(self.kitsu_status_error)
        return self.workers.start("kitsu_statuses", worker)

    def _on_kitsu_statuses(self, statuses: list) -> None:
        self.kitsu_statuses = list(statuses)
        self.kitsu_statuses_ready.emit(self.kitsu_statuses)

    def upload_to_kitsu(self, shot_name: str, status: dict, comment: str = "") -> bool:
        if self.production_service is None or not self.project_id:
            return False
        video = self.video_paths.get(shot_name)
        if video is None or not video.is_file():
            self.kitsu_upload_finished.emit(
                False, f"No review video available for {shot_name}."
            )
            return False
        if self.workers.is_running("kitsu_upload"):
            return False
        worker = KitsuUploadWorker(
            self.production_service,
            self.project_id,
            shot_name,
            self.settings.video_task_type or "render",
            status,
            comment,
            str(video),
        )
        worker.upload_finished.connect(self.kitsu_upload_finished)
        return self.workers.start("kitsu_upload", worker, critical=True)

    def _with_offer_warning(self, plan: RenderPlan) -> RenderPlan:
        if self.settings.render_backend != "vast" or self.offer is not None:
            return plan
        message = (
            "No Vast.ai offer within the price/network limits; raise the max price "
            "or switch to the local backend."
        )
        if message in plan.warnings:
            return plan
        return replace(plan, warnings=tuple(plan.warnings) + (message,))

    def _write_status(self, **updates) -> None:
        if self.status_store is None:
            return
        data = self.status_store.read()
        data["project"] = self.project_name
        data.update({key: value for key, value in updates.items() if value is not None})
        data["shots"] = [
            {
                "name": shot.name,
                "frames": shot.frames,
                "ready": shot.is_ready,
            }
            for shot in self.shots
        ]
        self.status_store.write(data)

    def _on_burst_progress_status(self, event) -> None:
        node = int(getattr(event, "node", 0))
        if getattr(event, "frames_total", 0):
            self._progress_by_node[node] = int(getattr(event, "frames_done", 0))
        card = self._ensure_node_card(node)
        stage = str(getattr(event, "stage", "") or "")
        card.status = _STAGE_TO_STATUS.get(stage, card.status or "rendering")
        card.stage = stage
        card.message = str(getattr(event, "message", "") or "")
        card.instance_id = int(getattr(event, "instance_id", 0) or card.instance_id or 0)
        if getattr(event, "gpu_name", ""):
            card.gpu_name = str(event.gpu_name)
        if getattr(event, "region", ""):
            card.region = str(event.region)
        if getattr(event, "price_per_hour", 0):
            card.price_per_hour = float(event.price_per_hour)
        if getattr(event, "offer_id", 0):
            card.offer_id = int(event.offer_id)
        card.frames_done = int(getattr(event, "frames_done", 0) or card.frames_done or 0)
        card.frames_expected = int(
            getattr(event, "frames_total", 0) or card.frames_expected or 0
        )
        self.node_card_updated.emit(node)
        self._write_status(
            status="rendering",
            message=getattr(event, "message", ""),
            frames_done=sum(self._progress_by_node.values()),
            frames_expected=(self.plan.total_frames if self.plan else None),
        )

    def _on_local_progress_status(self, shot_name: str, done: int, total: int, seconds: float) -> None:
        self._progress_by_shot[shot_name] = int(done)
        card = self._ensure_node_card(0)
        card.status = "rendering"
        card.message = f"{shot_name}: {done}/{total} ({seconds:.1f}s)"
        card.frames_done = sum(self._progress_by_shot.values())
        card.frames_expected = self.plan.total_frames if self.plan else card.frames_expected
        self.node_card_updated.emit(0)
        self._write_status(
            status="rendering",
            message=f"{shot_name}: {done}/{total} ({seconds:.1f}s)",
            frames_done=sum(self._progress_by_shot.values()),
        )

    def _on_error_status(self, message: str) -> None:
        self.set_busy(False)
        self._finish_audit(ok=False, message=message)
        if self._locked_shots:
            self._failed_shots.update(self._locked_shots)
            self._locked_shots.clear()
            self._emit_shot_reviews()
        self._write_status(status="failed", message=message)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self.cancel_render()
        self.workers.shutdown()
