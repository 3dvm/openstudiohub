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

import json
import statistics
import uuid
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Signal

from src.application.services.launch_service import LaunchService
from src.application.services.render_service import RenderService, next_version
from src.application.services.task_file_sync_service import TaskFileSyncService
from src.domain.render.capacity import (
    GPU_PROFILES,
    slowest_gpu_profile,
)
from src.domain.render.bakes import (
    bake_geometry_nodes_effective as _bake_effective,
    min_cpu_ram_gb_effective as _min_ram_effective,
)
from src.domain.render.models import (
    DependencyIssue,
    RenderPlan,
    RenderSettings,
    RenderShot,
)
from src.infrastructure.render.run_audit import RenderRunAuditLogger
from src.infrastructure.render.staging import bake_cache_names
from src.infrastructure.render.status import RenderStatusStore
from src.interfaces.qt.ui_format import format_rate
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.viewmodels.vcs_credential_gate import (
    VcsPrompt,
    ensure_vcs_credentials,
    vcs_requires_credentials,
)
from src.interfaces.qt.workers.render_workers import (
    DependencyFixWorker,
    KitsuStatusesWorker,
    KitsuTasksWorker,
    PublishShotWorker,
    RenderDependencyAuditWorker,
    RenderAlternativeOffersWorker,
    KitsuUploadWorker,
    LocalRenderWorker,
    RenderBenchmarkBatchWorker,
    RenderBenchmarkWorker,
    RenderBurstWorker,
    RenderCandidatesWorker,
    OpenShotBlendWorker,
    RenderOfferWorker,
    RenderPanelScanWorker,
    RenderPreviewVideoWorker,
    RenderPreviewWorker,
    RenderVideoWorker,
)
from src.interfaces.qt.workers.worker_manager import WorkerManager


@dataclass(frozen=True)
class NodeLaunchConfig:
    """Offer constraints and bake mode used by one node."""

    gpu_profile: str = "rtx_4070"
    max_price_per_hour: float = 0.0
    preferred_region: str = "prefer_americas"
    min_inet_down_mbps: float = 0.0
    min_inet_up_mbps: float = 0.0
    task_type: str = "render"
    bake_geometry_nodes: bool = False
    min_cpu_ram_gb: float = 0.0
    fill_similar_gpus: bool = False
    similar_gpu_mode: str = "floor"
    fill_allow_less_vram: bool = False


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
    upload_bytes_done: int = 0
    upload_bytes_total: int = 0
    upload_files: int = 0
    cost: float = 0.0
    stage: str = ""
    current_shot: str = ""
    progress_percent: float = 0.0
    seconds_per_frame: float = 0.0
    eta_seconds: float = 0.0
    hub_logs: tuple[Path, ...] = field(default_factory=tuple)
    summary_logs: tuple[Path, ...] = field(default_factory=tuple)
    blender_logs: tuple[Path, ...] = field(default_factory=tuple)
    final: bool = False
    run_id: str = ""
    run_label: str = ""
    assignment: tuple[tuple[str, tuple[int, ...]], ...] = ()
    launch: NodeLaunchConfig | None = None
    live_frame_path: str = ""

    @property
    def key(self) -> str:
        return f"{self.run_id}:{self.node}"


@dataclass
class RenderRunState:
    """State owned by one active render job."""

    run_id: str
    backend: str
    plan: RenderPlan
    gpu_profile: str
    locked_shots: set[str] = field(default_factory=set)
    cards: dict[int, RenderNodeCardModel] = field(default_factory=dict)
    progress_by_node: dict[int, int] = field(default_factory=dict)
    frame_seconds: dict[str, list[float]] = field(default_factory=dict)
    retry: bool = False
    node_indices: tuple[int, ...] = ()
    label: str = ""
    relaunch_key: str = ""
    settings: RenderSettings = field(default_factory=RenderSettings)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class RenderActivitySummary:
    """Live view of the runs and the work still queued behind them."""

    active_runs: int = 0
    nodes: int = 0
    frames_done: int = 0
    frames_expected: int = 0
    gpu_hours: float = 0.0
    cost: float = 0.0
    eta_seconds: float = 0.0
    shot_names: tuple[str, ...] = ()
    pending_plan: RenderPlan | None = None

    @property
    def has_active(self) -> bool:
        return self.active_runs > 0


@dataclass(frozen=True)
class RelaunchPlan:
    """One failed node retried on a fresh offer with the same frames."""

    shots: tuple[RenderShot, ...]
    plan: RenderPlan
    staging: object
    launch: NodeLaunchConfig
    bake_geometry_nodes: bool


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
    image_format: str
    measured_seconds: float | None
    warnings: tuple[str, ...]
    relative_path: str
    task_type: str = ""
    particle_state: str = ""
    setup_html: str = ""
    dependency_count: int = 0
    dependency_blocking_count: int = 0


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
    "install": "installing",
    "setup": "installing",
    "stage": "staging",
    "verify": "verifying",
    "render": "rendering",
    "frame": "rendering",
    "sync": "syncing",
    "bake": "baking",
    "validate": "validating",
    "destroy": "destroyed",
}


class RenderPanelViewModel(BaseViewModel):
    shots_ready = Signal(list, object, object, float, list)
    shots_cache_loaded = Signal(bool)
    vast_balance_ready = Signal(float)
    dependency_fix_finished = Signal(bool, str)
    dependencies_audited = Signal(bool)
    offer_diagnostics_ready = Signal(object)
    offer_alternatives_ready = Signal(list)
    shot_reviews_ready = Signal(list)
    node_cards_ready = Signal(list)
    node_card_updated = Signal(str)
    render_runs_changed = Signal(int)
    measurement_conflicts = Signal(list)
    scan_progress = Signal(str, int, int)
    scan_error = Signal(str)

    preview_ready = Signal(str, str)
    preview_progress = Signal(str, int, int, float)
    preview_error = Signal(str)
    preview_finished = Signal(int, int, list, object)
    preview_running = Signal(bool)

    benchmark_progress = Signal(object)
    benchmark_finished = Signal(str, float)
    benchmarks_finished = Signal(list, str)
    benchmark_error = Signal(str)
    benchmark_running = Signal(bool)

    burst_progress = Signal(object)
    live_frame_ready = Signal(str, int, str, int)  # shot, frame, path, node
    local_render_progress = Signal(str, int, int, float)
    render_finished = Signal(object)
    render_error = Signal(str)

    video_ready = Signal(str, str)
    video_error = Signal(str)
    videos_finished = Signal(int, int)
    preview_video_ready = Signal(str, str)

    kitsu_statuses_ready = Signal(list)
    kitsu_status_error = Signal(str)
    kitsu_tasks_ready = Signal(list)
    publish_finished = Signal(bool, str, str)
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
        self.scan_error.connect(self._on_scan_error)
        self.preview_error.connect(self._on_preview_error)
        self.preview_progress.connect(self._on_preview_progress_status)
        self.render_error.connect(self._on_render_error)

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
        self.kitsu_tasks: list[dict] = []
        self.read_only = False
        self.status_store: RenderStatusStore | None = None
        self.audit = RenderRunAuditLogger()
        self._active_run_id = ""
        self.last_burst_report = None
        self.preview_video_paths: dict[str, Path] = {}
        self.node_cards: list[RenderNodeCardModel] = []
        self.candidate_offers: list = []
        self.offer_diagnostics = None
        self.alternate_offers: list = []
        self._runs: dict[str, RenderRunState] = {}
        self._plan_cards: list[RenderNodeCardModel] = []
        self._finished_cards: list[RenderNodeCardModel] = []
        self._preview_cards: list[RenderNodeCardModel] = []
        self._preview_run_id = ""
        self._preview_rendered = 0
        self._preview_total = 0
        self._benchmark_cards: list[RenderNodeCardModel] = []
        self._benchmark_run_id = ""
        self._relaunch_active: set[str] = set()
        self._local_run_id = ""
        self._progress_by_shot: dict[str, int] = {}
        self._progress_by_node: dict[int, int] = {}
        self._node_frame_seconds: dict[int, deque[float]] = {}
        self._locked_shots: set[str] = set()
        self._failed_shots: set[str] = set()
        self.last_preview_failed: list[str] = []
        self.last_preview_report = None
        self._shots_from_cache = False
        self._dependency_blocking: dict[tuple[str, str, str], bool] = {}

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
        self._node_frame_seconds = {}
        self.shots = []
        self.plan = None
        self.offer = None
        self.preview_paths = {}
        self.video_paths = {}
        self._load_preview_paths()
        self.node_cards = []
        self.candidate_offers = []
        self.offer_diagnostics = None
        self.alternate_offers = []
        self._runs = {}
        self._plan_cards = []
        self._finished_cards = []
        self._preview_cards = []
        self._preview_run_id = ""
        self._preview_rendered = 0
        self._preview_total = 0
        self._benchmark_cards = []
        self._benchmark_run_id = ""
        self._relaunch_active = set()
        self._local_run_id = ""
        self._locked_shots = set()
        self._failed_shots = set()
        self._node_frame_seconds = {}
        self._dependency_blocking = {}
        self.node_cards_ready.emit([])
        self.shot_reviews_ready.emit([])
        self.render_runs_changed.emit(0)
        try:
            self.settings = self.service.load_settings(self.project_root)
        except Exception:  # noqa: BLE001
            self.settings = RenderSettings()
        if not read_only:
            self._write_status(status="idle", message="Render panel loaded.")
            cached = self._load_cached_shots()
            if cached is None:
                self.report_status(
                    "No cached shots. Press Re-scan to scan the project.", "white"
                )
        else:
            self.report_status("Render panel loaded in read-only mode.", "white")

    def _load_cached_shots(self) -> list | None:
        """Show the last scan immediately, before the background refresh."""
        try:
            shots = self.service.cached_shots(
                self.project_root,
                quality_override=self.settings.final_quality,
                gpu_profile=self.settings.gpu_profile,
            )
        except Exception:  # noqa: BLE001 - the scan replaces a missing cache
            shots = None
        if not shots:
            return None
        self.shots = list(shots)
        self._shots_from_cache = True
        self.shots_cache_loaded.emit(True)
        available = {shot.relative_path for shot in self.shots}
        selected = tuple(
            path for path in self.settings.selected_shots if path in available
        )
        if not selected:
            selected = tuple(
                shot.relative_path for shot in self.shots if shot.is_ready
            )
        if selected != self.settings.selected_shots:
            self.settings = replace(self.settings, selected_shots=selected)
            self._save_settings()
        self.recalculate()
        self._emit_shot_reviews()
        self.report_status(
            f"Loaded {len(self.shots)} shot(s) from the local scan cache.", "white"
        )
        return self.shots

    @property
    def selected_shots(self) -> list[RenderShot]:
        return self.service.selected_shots(self.shots, self.settings)

    def bake_geometry_nodes_effective(
        self, shots: list[RenderShot] | None = None
    ) -> bool:
        targets = list(shots if shots is not None else self.selected_shots)
        return _bake_effective(self.settings, targets)

    def min_cpu_ram_gb_effective(
        self, shots: list[RenderShot] | None = None
    ) -> float:
        targets = list(shots if shots is not None else self.selected_shots)
        return _min_ram_effective(self.settings, targets)

    def update_settings(self, settings: RenderSettings) -> None:
        self.settings = settings
        self._save_settings()

    def update_preview_settings(self, settings: RenderSettings) -> None:
        """Apply only the preview fields without changing the current plan."""
        self.settings = replace(
            self.settings,
            preview_backend=settings.preview_backend,
            preview_quality=settings.preview_quality,
            preview_frame_mode=settings.preview_frame_mode,
            preview_frame=settings.preview_frame,
            preview_frames=settings.preview_frames,
        )
        self._save_settings()

    def set_render_backend(
        self, backend: str, settings: RenderSettings | None = None
    ) -> None:
        """Switch the final backend and refresh the plan immediately."""
        value = (backend or "vast").strip().lower()
        if value not in ("vast", "local"):
            value = "vast"
        if value == self.settings.render_backend and self.offer is not None:
            return
        updates: dict = {"render_backend": value}
        if settings is not None:
            updates.update(
                gpu_profile=settings.gpu_profile,
                target_hours=settings.target_hours,
                max_price_per_hour=settings.max_price_per_hour,
                max_nodes=settings.max_nodes,
                budget=settings.budget,
                preferred_region=settings.preferred_region,
                min_inet_down_mbps=settings.min_inet_down_mbps,
                min_inet_up_mbps=settings.min_inet_up_mbps,
                min_cpu_ram_gb=settings.min_cpu_ram_gb,
                fill_similar_gpus=settings.fill_similar_gpus,
                similar_gpu_mode=settings.similar_gpu_mode,
                fill_allow_less_vram=settings.fill_allow_less_vram,
            )
        self.settings = replace(self.settings, **updates)
        self._save_settings()
        self.recalculate()
        if value == "vast":
            self._refresh_vast_offer()

    def refresh_offer(self) -> bool:
        """Public wrapper used by the offer panel actions."""
        return self._refresh_vast_offer()

    def _refresh_vast_offer(self) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("render_offer"):
            return False
        count = max(1, int(self.plan.required_nodes or 1)) if self.plan else 1
        worker = RenderOfferWorker(
            self.service,
            count,
            self.settings,
            min_cpu_ram_gb=self.min_cpu_ram_gb_effective(
                list(self.plan.shots) if self.plan is not None else None
            ),
        )
        worker.offers_ready.connect(self._on_offers_ready)
        worker.offer_blocked.connect(self._on_offer_blocked)
        worker.error.connect(self._on_offer_error)
        self.report_status("Searching for a Vast.ai offer...", "yellow")
        return self.workers.start("render_offer", worker)

    def _on_offers_ready(self, offers: list, balance: float) -> None:
        self.candidate_offers = list(offers or ())
        self.offer = self.candidate_offers[0] if self.candidate_offers else None
        self.balance = float(balance or 0.0)
        self.offer_diagnostics = None
        self.alternate_offers = []
        self.vast_balance_ready.emit(self.balance)
        self.recalculate()
        if self.offer is None:
            self.report_status(
                "No Vast.ai offer matched the current price/network limits.", "red"
            )
            return
        self.report_status(
            f"Vast.ai offer: {self.offer.gpu_name} at "
            f"${self.offer.price_per_hour:.2f}/h.",
            "green",
        )

    def _on_offer_error(self, message: str) -> None:
        self.offer = None
        self.candidate_offers = []
        self.offer_diagnostics = None
        self.alternate_offers = []
        self.recalculate()
        self.report_status(message, "red")

    def _on_offer_blocked(self, diagnostics) -> None:
        self.offer = None
        self.candidate_offers = []
        self.offer_diagnostics = diagnostics
        self.alternate_offers = []
        message = getattr(diagnostics, "message", "") or (
            "No Vast.ai offer matched the current limits."
        )
        self.report_status(message, "red")
        self.offer_diagnostics_ready.emit(diagnostics)
        self.recalculate()

    def apply_offer_fix(self, field: str, value) -> bool:
        """Apply one explicit limit change and search again."""
        allowed = {
            "max_price_per_hour",
            "min_cpu_ram_gb",
            "min_inet_down_mbps",
            "min_inet_up_mbps",
            "preferred_region",
            "gpu_profile",
        }
        if field not in allowed or self.project_root is None or self.read_only:
            return False
        updates = {field: value}
        self.settings = replace(self.settings, **updates)
        self._save_settings()
        self.offer_diagnostics = None
        self.alternate_offers = []
        self.recalculate()
        self._refresh_vast_offer()
        self.report_status(f"Applied offer fix: {field} = {value}.", "green")
        return True

    def use_local_backend(self) -> None:
        self.offer_diagnostics = None
        self.alternate_offers = []
        self.set_render_backend("local")

    def search_alternate_profiles(self) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("render_alternates"):
            return False
        worker = RenderAlternativeOffersWorker(
            self.service,
            self.settings,
            min_cpu_ram_gb=self.min_cpu_ram_gb_effective(
                list(self.plan.shots) if self.plan is not None else None
            ),
        )
        worker.alternatives_ready.connect(self._on_alternatives_ready)
        worker.error.connect(self._on_offer_error)
        self.report_status("Searching the other GPU profiles...", "yellow")
        return self.workers.start("render_alternates", worker)

    def _on_alternatives_ready(self, alternatives: list) -> None:
        self.alternate_offers = list(alternatives or ())
        self.offer_alternatives_ready.emit(self.alternate_offers)
        if self.alternate_offers:
            self.report_status(
                f"{len(self.alternate_offers)} other GPU profile(s) have a "
                "valid offer.",
                "green",
            )
        else:
            self.report_status(
                "No other GPU profile matches the current limits.", "red"
            )

    def staging_estimate(self, shots: list[RenderShot] | None = None):
        """Return the upload the next Vast node would receive."""
        if self.project_root is None:
            return None
        targets = list(
            shots
            if shots is not None
            else (list(self.plan.shots) if self.plan is not None else ())
        )
        exclude_names = (
            bake_cache_names(targets)
            if self.bake_geometry_nodes_effective(targets)
            else ()
        )
        try:
            return self.service.staging_estimate(
                self.project_root,
                exclude_names=exclude_names,
                shots=targets,
            )
        except Exception:  # noqa: BLE001 - the dialog falls back to no estimate
            return None

    def audit_dependencies(self) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("dependency_audit"):
            return False
        targets = self.selected_shots
        if not targets:
            return False
        worker = RenderDependencyAuditWorker(
            self.service, self.project_root, targets
        )
        worker.audited.connect(self._on_dependencies_audited)
        worker.error.connect(self._on_dependency_audit_error)
        self.report_status("Auditing dependencies recursively...", "yellow")
        return self.workers.start("dependency_audit", worker, critical=False)

    def _on_dependencies_audited(self, audited: list) -> None:
        by_path = {shot.relative_path: shot for shot in audited or ()}
        self.shots = [
            by_path.get(shot.relative_path, shot) for shot in self.shots
        ]
        self._apply_dependency_preferences()
        self.recalculate()
        self._emit_shot_reviews()
        self.dependencies_audited.emit(True)
        issues = self.dependency_issues()
        self.report_status(
            f"Dependency audit complete: {len(issues)} issue(s).",
            "green" if not issues else "red",
        )

    def _on_dependency_audit_error(self, message: str) -> None:
        self.dependencies_audited.emit(False)
        self.report_status(f"Dependency audit failed: {message}", "red")

    def dependency_issues(
        self, shots: list[RenderShot] | None = None
    ) -> list[DependencyIssue]:
        targets = list(
            shots
            if shots is not None
            else (
                list(self.plan.shots)
                if self.plan is not None
                else list(self.selected_shots)
            )
        )
        seen: set[tuple[str, str, str]] = set()
        issues: list[DependencyIssue] = []
        for shot in targets:
            for issue in getattr(shot, "dependency_issues", ()) or ():
                key = (issue.path, issue.status, issue.owner)
                if key in seen:
                    continue
                seen.add(key)
                issues.append(issue)
        return issues

    def blocking_dependency_issues(
        self, shots: list[RenderShot] | None = None
    ) -> list[DependencyIssue]:
        return [
            issue for issue in self.dependency_issues(shots) if issue.blocking
        ]

    def set_dependency_blocking(
        self, issue: DependencyIssue, blocking: bool
    ) -> None:
        key = (issue.path, issue.status, issue.owner)
        self._dependency_blocking[key] = bool(blocking)
        self._apply_dependency_preferences()
        self.dependencies_audited.emit(True)

    def _apply_dependency_preferences(self) -> None:
        updated: list[RenderShot] = []
        for shot in self.shots:
            issues = tuple(
                replace(
                    issue,
                    blocking=self._dependency_blocking.get(
                        (issue.path, issue.status, issue.owner),
                        issue.blocking,
                    ),
                )
                for issue in getattr(shot, "dependency_issues", ()) or ()
            )
            updated.append(replace(shot, dependency_issues=issues))
        self.shots = updated
        by_path = {shot.relative_path: shot for shot in updated}
        if self.plan is not None:
            plan_shots = []
            for shot in self.plan.shots:
                source = by_path.get(shot.relative_path)
                if source is not None:
                    shot = replace(
                        shot, dependency_issues=source.dependency_issues
                    )
                plan_shots.append(shot)
            self.plan = replace(self.plan, shots=tuple(plan_shots))

    def fix_dependencies(self) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("dependency_fix"):
            return False
        issues = self.dependency_issues()
        owners = sorted(
            {
                issue.owner
                for issue in issues
                if issue.owner and issue.status in ("external", "outside_production")
            }
        )
        if not owners:
            self.report_status("No external dependency owners to fix.", "yellow")
            return False
        worker = DependencyFixWorker(
            self.service, self.project_root, owners
        )
        worker.fixed.connect(self._on_dependencies_fixed)
        self.report_status("Packing and unpacking external dependencies...", "yellow")
        return self.workers.start("dependency_fix", worker, critical=True)

    def _on_dependencies_fixed(self, ok: bool, message: str) -> None:
        self.report_status(message, "green" if ok else "red")
        self.dependency_fix_finished.emit(ok, message)
        if ok:
            self.scan(force=False)

    def preview_frame_for(self, shot: RenderShot) -> int:
        return self.service.preview_frame(shot, self.settings)

    def set_preview_frame(self, shot: RenderShot, frame: int) -> None:
        value = max(shot.frame_start, min(shot.frame_end, int(frame)))
        entries = dict(self.settings.preview_frames)
        entries[shot.relative_path] = value
        self.settings = replace(
            self.settings, preview_frames=tuple(sorted(entries.items()))
        )
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
    def scan(self, *, force: bool = False) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("render_scan"):
            return False
        worker = RenderPanelScanWorker(
            self.service,
            self.project_root,
            self.settings,
            production_service=self.production_service,
            project_id=self.project_id,
            force=force,
        )
        worker.scan_progress.connect(self.scan_progress)
        worker.shots_ready.connect(self._on_scan_shots_ready)
        worker.scan_warning.connect(self._on_scan_warning)
        worker.offer_blocked.connect(self._on_offer_blocked)
        worker.error.connect(self.scan_error)
        self.set_busy(True)
        self.report_status(
            "Re-scanning every .blend with Blender..."
            if force
            else "Refreshing shots and render setup...",
            "yellow",
        )
        return self.workers.start("render_scan", worker)

    def _on_scan_warning(self, message: str) -> None:
        self.report_status(message, "yellow")

    def _apply_dependency_preferences_from(self, shots: list) -> None:
        prepared = []
        for shot in shots:
            issues = tuple(
                replace(
                    issue,
                    blocking=self._dependency_blocking.get(
                        (issue.path, issue.status, issue.owner),
                        issue.blocking,
                    ),
                )
                for issue in getattr(shot, "dependency_issues", ()) or ()
            )
            prepared.append(replace(shot, dependency_issues=issues))
        self.shots = prepared

    def _on_scan_shots_ready(
        self, shots: list, plan: RenderPlan, offer, balance: float, candidates: list
    ) -> None:
        self._shots_from_cache = False
        self._apply_dependency_preferences_from(shots)
        self.shots_cache_loaded.emit(False)
        self._on_shots_ready(
            self.shots or shots,
            plan,
            self.offer,
            self.balance,
            self.candidate_offers,
        )

    def _on_shots_ready(
        self, shots: list, plan: RenderPlan, offer, balance: float, candidates: list
    ) -> None:
        self.set_busy(False)
        self.shots = list(shots)
        self.offer = offer
        self.balance = balance
        self.vast_balance_ready.emit(float(balance or 0.0))
        self.candidate_offers = list(candidates or ())
        if offer is not None or not (
            self.settings.render_backend == "vast"
            or self.settings.preview_backend == "vast"
        ):
            self.offer_diagnostics = None
            self.alternate_offers = []
        available = {shot.relative_path for shot in self.shots}
        selected = tuple(
            path for path in self.settings.selected_shots if path in available
        )
        if not selected:
            selected = tuple(
                shot.relative_path for shot in self.shots if shot.is_ready
            )
        if selected != self.settings.selected_shots:
            self.settings = replace(self.settings, selected_shots=selected)
            self._save_settings()
        self.recalculate()
        current = self.plan or plan
        if self._runs:
            self._write_runs_status("Render plan ready.")
        else:
            self._write_status(
                status="ready",
                message="Render plan ready.",
                frames_expected=current.total_frames if current else 0,
                frames_done=0,
                nodes=current.required_nodes if current else 0,
                cost=current.estimated_cost if current else 0.0,
            )
        self.report_status("Render plan ready.", "green")
        self.shots_ready.emit(
            self.shots, self.plan, self.offer, self.balance, self.candidate_offers
        )
        self._emit_shot_reviews()

    def is_shot_locked(self, shot: RenderShot) -> bool:
        return shot.relative_path in self._locked_shots

    def has_active_runs(self) -> bool:
        return bool(self._runs)

    def active_run_count(self) -> int:
        return len(self._runs)

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
        dependency_count = len(getattr(shot, "dependency_issues", ()) or ())
        dependency_blocking_count = sum(
            1
            for issue in getattr(shot, "dependency_issues", ()) or ()
            if issue.blocking
        )
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
            image_format=quality.file_format,
            measured_seconds=shot.measured_seconds,
            warnings=tuple(warnings),
            relative_path=shot.relative_path,
            task_type=shot.task_type,
            particle_state=self._particle_state(shot),
            setup_html=self._setup_html(shot),
            dependency_count=dependency_count,
            dependency_blocking_count=dependency_blocking_count,
        )

    def _setup_html(self, shot: RenderShot) -> str:
        setup = shot.setup
        if setup is None:
            return "Render setup: not available."
        layers = ", ".join(
            f"{layer.name}{'✓' if layer.connected_to_output else '⚠'}"
            for layer in setup.view_layers
        ) or "-"
        comp = "on" if setup.is_compositing_ready else "check"
        outputs = (
            ", ".join(item.base_path for item in setup.file_outputs)
            if setup.file_outputs
            else "composite only"
        )
        return (
            f"<b>Compositing:</b> {comp} ({setup.compositor_name or '-'}) · "
            f"<b>View layers:</b> {layers}<br>"
            f"<b>Output:</b> {setup.output_format or '-'} "
            f"{setup.color_mode or '-'} "
            f"{setup.color_depth + '-bit' if setup.color_depth else ''} · "
            f"<b>Color:</b> {setup.view_transform or '-'}<br>"
            f"<b>Camera:</b> {setup.camera or '-'} · "
            f"<b>FPS:</b> {setup.fps:.2f} · "
            f"<b>Range:</b> {shot.frame_start}–{shot.frame_end}<br>"
            f"<b>Files:</b> {outputs}"
        )

    @staticmethod
    def _particle_state(shot: RenderShot) -> str:
        if not shot.particle_caches:
            return ""
        if any(not cache.baked for cache in shot.particle_caches):
            return "Particle cache missing"
        return "Particle cache present"

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
        step = max(1, int(shot.frame_step or 1))
        return [
            frame
            for frame in range(shot.frame_start, shot.frame_end + 1, step)
            if self.service.frame_path(
                self.project_root, shot, frame, self.settings.task_type
            ).is_file()
        ]

    def render_single_shot(self, shot: RenderShot) -> bool:
        if self.is_shot_locked(shot):
            self.render_error.emit("That shot is already rendering.")
            return False
        plan = self._plan_for_shots([shot])
        if not plan.shots:
            self.render_error.emit("That shot has no pending frames.")
            return False
        return self._start_render_plan(plan)

    def retry_missing_shot(self, shot: RenderShot) -> bool:
        if self.is_shot_locked(shot):
            self.render_error.emit("That shot is already rendering.")
            return False
        plan = self._plan_for_shots([shot])
        if not plan.shots:
            self.render_error.emit("That shot has no missing frames.")
            return False
        return self._start_render_plan(plan, retry=True)

    def approve_all_rendered(self, shot: RenderShot) -> tuple[bool, str]:
        frames = self._rendered_frames(shot)
        if not frames:
            return False, "The shot has no rendered frames."
        result = self.approve_frames(shot, frames, True)
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

    @staticmethod
    def _run_label(plan: RenderPlan) -> str:
        names = [shot.name for shot in getattr(plan, "shots", ()) or ()]
        if not names:
            return ""
        if len(names) <= 2:
            return ", ".join(names)
        return f"{names[0]}, {names[1]} +{len(names) - 2}"

    def _build_node_cards(self, plan: RenderPlan) -> None:
        label = self._run_label(plan)
        if self.settings.render_backend == "local":
            cards = [
                RenderNodeCardModel(
                    node=0,
                    status="candidate",
                    message="Runs on this workstation.",
                    gpu_name="Local workstation",
                    final=True,
                    run_id="plan",
                    run_label=label,
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
                            run_id="plan",
                            run_label=label,
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
                        run_id="plan",
                        run_label=label,
                    )
                )
        self._plan_cards = cards
        self._sync_node_cards()

    def _sync_node_cards(self) -> None:
        cards: list[RenderNodeCardModel] = []
        for run in sorted(self._runs.values(), key=lambda item: item.started_at):
            cards.extend(
                card for _node, card in sorted(run.cards.items())
            )
        cards.extend(self._finished_cards)
        cards.extend(self._preview_cards)
        cards.extend(self._benchmark_cards)
        cards.extend(self._plan_cards)
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
            min_cpu_ram_gb=self.min_cpu_ram_gb_effective(list(self.plan.shots)),
        )
        worker.candidates_ready.connect(self._on_candidates_ready)
        worker.offer_blocked.connect(self._on_offer_blocked)
        worker.error.connect(self.scan_error)
        self.report_status("Refreshing Vast.ai candidate offers...", "yellow")
        return self.workers.start("render_candidates", worker)

    def _on_candidates_ready(self, candidates: list) -> None:
        self.candidate_offers = list(candidates or [])
        self.offer_diagnostics = None
        self.alternate_offers = []
        self.recalculate()
        self.report_status("Candidate offers refreshed.", "green")

    def fill_with_similar_profiles(
        self,
        mode: str = "floor",
        *,
        allow_less_vram: bool = False,
    ) -> bool:
        """Enable fill mode and refresh the candidate offers explicitly."""
        if self.project_root is None or self.read_only:
            return False
        direction = (mode or "floor").strip().lower()
        if direction not in ("floor", "ceiling"):
            direction = "floor"
        self.settings = replace(
            self.settings,
            fill_similar_gpus=True,
            similar_gpu_mode=direction,
            fill_allow_less_vram=bool(allow_less_vram),
        )
        self._save_settings()
        self.recalculate()
        started = self.refresh_candidates()
        if not started:
            self._refresh_vast_offer()
        return True

    def cap_plan_to_available(self) -> bool:
        """Cap the plan at the number of offers currently available."""
        available = len(self.candidate_offers or ())
        if available <= 0 or self.project_root is None or self.read_only:
            return False
        self.settings = replace(self.settings, max_nodes=available)
        self._save_settings()
        self.recalculate()
        self.report_status(
            f"Plan capped at {available} node(s); the deadline may require "
            "a longer target.",
            "yellow",
        )
        return True

    def _ensure_node_card(self, run_id: str, node: int) -> RenderNodeCardModel:
        run_id = str(run_id or "")
        if run_id and run_id == self._preview_run_id:
            while len(self._preview_cards) <= int(node):
                self._preview_cards.append(
                    RenderNodeCardModel(
                        node=len(self._preview_cards),
                        status="queued",
                        run_id=run_id,
                        run_label="preview",
                    )
                )
                self._sync_node_cards()
            return self._preview_cards[int(node)]
        if run_id and run_id == self._benchmark_run_id:
            while len(self._benchmark_cards) <= int(node):
                self._benchmark_cards.append(
                    RenderNodeCardModel(
                        node=len(self._benchmark_cards),
                        status="queued",
                        run_id=run_id,
                        run_label="benchmark",
                    )
                )
                self._sync_node_cards()
            return self._benchmark_cards[int(node)]
        run = self._runs.get(run_id)
        if run is not None:
            card = run.cards.get(int(node))
            if card is None:
                card = RenderNodeCardModel(
                    node=int(node),
                    status="queued",
                    run_id=run.run_id,
                    run_label=run.label or self._run_label(run.plan),
                    launch=self._launch_config(run.settings),
                )
                run.cards[int(node)] = card
                self._sync_node_cards()
            return card
        while len(self._plan_cards) <= int(node):
            self._plan_cards.append(
                RenderNodeCardModel(
                    node=len(self._plan_cards),
                    status="queued",
                    run_id="plan",
                )
            )
            self._sync_node_cards()
        return self._plan_cards[int(node)]

    @staticmethod
    def _launch_config(settings: RenderSettings) -> NodeLaunchConfig:
        return NodeLaunchConfig(
            gpu_profile=settings.gpu_profile,
            max_price_per_hour=settings.max_price_per_hour,
            preferred_region=settings.preferred_region,
            min_inet_down_mbps=settings.min_inet_down_mbps,
            min_inet_up_mbps=settings.min_inet_up_mbps,
            task_type=settings.task_type,
            bake_geometry_nodes=bool(settings.bake_geometry_nodes),
            min_cpu_ram_gb=float(settings.min_cpu_ram_gb or 0.0),
            fill_similar_gpus=bool(settings.fill_similar_gpus),
            similar_gpu_mode=str(settings.similar_gpu_mode or "floor"),
            fill_allow_less_vram=bool(settings.fill_allow_less_vram),
        )

    def _create_run_cards(self, run: RenderRunState) -> None:
        label = run.label or self._run_label(run.plan)
        launch = self._launch_config(run.settings)
        cards: dict[int, RenderNodeCardModel] = {}
        if run.backend == "local":
            cards[0] = RenderNodeCardModel(
                node=0,
                status="queued",
                message="Waiting for the workstation.",
                run_id=run.run_id,
                run_label=label,
                gpu_name="Local workstation",
                launch=launch,
            )
            run.cards = cards
            return
        node_indices = (
            list(run.node_indices)
            if run.node_indices
            else list(range(max(1, int(run.plan.required_nodes or 1))))
        )
        for position, node in enumerate(node_indices):
            offer = (
                self.candidate_offers[position]
                if position < len(self.candidate_offers)
                else None
            )
            cards[int(node)] = RenderNodeCardModel(
                node=int(node),
                status="queued",
                message="Waiting for a node.",
                run_id=run.run_id,
                run_label=label,
                gpu_name=str(getattr(offer, "gpu_name", "") or ""),
                region=str(getattr(offer, "geolocation", "") or ""),
                price_per_hour=float(getattr(offer, "price_per_hour", 0.0) or 0.0),
                offer_id=int(getattr(offer, "id", 0) or 0),
                launch=launch,
            )
        run.cards = cards

    def _available_selected_shots(self) -> list[RenderShot]:
        return [
            shot for shot in self.selected_shots if not self.is_shot_locked(shot)
        ]

    @staticmethod
    def _offer_profile_key(offer) -> str:
        key = str(getattr(offer, "gpu_profile", "") or "")
        if key in GPU_PROFILES:
            return key
        name = str(getattr(offer, "gpu_name", "") or "").strip().lower()
        for profile_key, profile in GPU_PROFILES.items():
            if name and name == profile.vast_gpu_name.strip().lower():
                return profile_key
        return ""

    def effective_gpu_profile(self) -> str:
        """Return the speed reference used by the current offer mix."""
        base = self.settings.gpu_profile
        if (
            self.settings.render_backend != "vast"
            or not self.settings.fill_similar_gpus
            or self.settings.similar_gpu_mode != "ceiling"
            or not self.candidate_offers
        ):
            return base
        profiles = [
            self._offer_profile_key(offer) for offer in self.candidate_offers
        ]
        slowest = slowest_gpu_profile(profiles)
        return slowest or base

    def _with_offer_mix(self, plan: RenderPlan) -> RenderPlan:
        """Apply per-node prices and warnings to a mixed offer selection."""
        if self.settings.render_backend != "vast":
            return plan
        offers = list(self.candidate_offers or ())
        required = int(plan.required_nodes or 0)
        selected = offers[:required] if required > 0 else offers
        base = GPU_PROFILES.get(self.settings.gpu_profile)
        warnings = list(plan.warnings)
        if base is not None and selected:
            fallback = [
                offer
                for offer in selected
                if self._offer_profile_key(offer) not in ("", base.key)
            ]
            if fallback:
                counts: dict[str, int] = {}
                for offer in fallback:
                    label = str(
                        getattr(offer, "gpu_label", "")
                        or getattr(offer, "gpu_name", "")
                        or "similar GPU"
                    )
                    counts[label] = counts.get(label, 0) + 1
                detail = ", ".join(
                    f"{count}× {label}" for label, count in counts.items()
                )
                if self.settings.similar_gpu_mode == "ceiling":
                    warnings.append(
                        f"{len(fallback)} node(s) filled with same or slower "
                        f"GPUs: {detail}. The plan uses the slowest selected GPU."
                    )
                else:
                    warnings.append(
                        f"{len(fallback)} node(s) filled with same or faster "
                        f"GPUs: {detail}. Actual wall time may improve."
                    )
            less_vram = [
                offer
                for offer in selected
                if float(getattr(offer, "gpu_ram_gb", 0.0) or 0.0) < base.vram_gb
            ]
            if less_vram:
                warnings.append(
                    f"{len(less_vram)} selected node(s) have less VRAM than "
                    f"{base.label}; out-of-memory risk is higher."
                )
        if required > 0 and len(offers) < required:
            message = (
                f"Only {len(offers)} of {required} node offer(s) are available. "
                "Fill with similar GPUs or cap the plan."
            )
            if not any(
                "node offer(s) are available" in item
                or "candidate offer(s) for" in item
                for item in warnings
            ):
                warnings.append(message)
            return replace(plan, warnings=tuple(warnings))
        if required > 0 and offers:
            wall = float(plan.estimated_wall_seconds or 0.0)
            cost = sum(
                float(getattr(offer, "price_per_hour", 0.0) or 0.0)
                * wall
                / 3600.0
                for offer in offers[:required]
            )
            warnings = [
                warning
                for warning in warnings
                if not warning.startswith("Estimated cost (")
            ]
            if self.settings.budget > 0 and cost > self.settings.budget:
                warnings.append(
                    f"Estimated cost ({cost:.2f}) exceeds the budget "
                    f"({self.settings.budget:.2f})."
                )
            plan = replace(plan, estimated_cost=cost)
        return replace(plan, warnings=tuple(warnings))

    def _plan_for_shots(self, shots: list[RenderShot]) -> RenderPlan:
        pending = self.service.pending_shots(
            self.project_root, shots, task_type=self.settings.task_type
        )
        price = self.offer.price_per_hour if self.offer is not None else 0.0
        effective = self.effective_gpu_profile()
        plan = self._with_offer_warning(
            self.service.adjust_plan_for_backend(
                self.service.plan(
                    self.project_root,
                    target_hours=self.settings.target_hours,
                    gpu_profile=effective,
                    measured_gpu_profile=(
                        self.settings.gpu_profile
                        if effective != self.settings.gpu_profile
                        else ""
                    ),
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
        plan = self._with_offer_mix(plan)
        warnings = list(plan.warnings)
        bake_effective = self.bake_geometry_nodes_effective(pending)
        gn_shots = [shot for shot in pending if shot.geometry_bakes]
        if gn_shots:
            if bake_effective:
                warnings.append(
                    "Geometry-node caches will be baked on each node before "
                    "rendering; the first frame waits for the bake."
                )
                min_ram = self.min_cpu_ram_gb_effective(pending)
                if min_ram > 0:
                    source = (
                        "configured"
                        if self.settings.min_cpu_ram_gb > 0
                        else "automatic"
                    )
                    warnings.append(
                        f"Vast.ai hosts need at least {min_ram:.0f} GB of "
                        f"system RAM for node-side bakes ({source})."
                    )
            else:
                warnings.append(
                    "Geometry-node caches will be uploaded to every node. "
                    "Enable the node bake to reduce the upload."
                )
        missing_particles = [
            shot.name
            for shot in pending
            if any(not cache.baked for cache in shot.particle_caches)
        ]
        if missing_particles:
            warnings.append(
                "Particle caches missing (not baked by the node): "
                + ", ".join(sorted(set(missing_particles)))
            )
        return replace(plan, warnings=tuple(warnings))

    def recalculate(self) -> None:
        if not self.shots or self.project_root is None:
            return
        self.plan = self._plan_for_shots(self._available_selected_shots())
        self._build_node_cards(self.plan)
        self.shots_ready.emit(
            self.shots, self.plan, self.offer, self.balance, self.candidate_offers
        )

    def activity_summary(self) -> RenderActivitySummary:
        """Aggregate live runs and the pending plan for the Nodes panel."""
        now = datetime.now(timezone.utc)
        nodes = 0
        frames_done = 0
        frames_expected = 0
        gpu_hours = 0.0
        cost = 0.0
        eta_seconds = 0.0
        shot_names: list[str] = []
        for run in sorted(self._runs.values(), key=lambda item: item.started_at):
            elapsed = max(0.0, (now - run.started_at).total_seconds())
            run_nodes = len(run.cards) or int(run.plan.required_nodes or 0)
            nodes += run_nodes
            run_done = sum(run.progress_by_node.values())
            if not run_done:
                run_done = sum(card.frames_done for card in run.cards.values())
            frames_done += run_done
            frames_expected += sum(
                card.frames_expected
                for card in run.cards.values()
                if card.frames_expected
            ) or int(run.plan.total_frames or 0)
            shot_names.extend(shot.name for shot in run.plan.shots)
            if run.cards:
                for card in run.cards.values():
                    price = float(card.price_per_hour or run.plan.price_per_hour or 0.0)
                    gpu_hours += elapsed / 3600.0
                    cost += price * elapsed / 3600.0
                    if not card.final and card.eta_seconds > 0:
                        eta_seconds = max(eta_seconds, float(card.eta_seconds))
            else:
                gpu_hours += elapsed * run_nodes / 3600.0
                cost += (
                    float(run.plan.price_per_hour or 0.0)
                    * elapsed
                    * run_nodes
                    / 3600.0
                )
            if not eta_seconds:
                eta_seconds = max(
                    0.0,
                    float(run.plan.estimated_wall_seconds or 0.0) - elapsed,
                )
        return RenderActivitySummary(
            active_runs=len(self._runs),
            nodes=nodes,
            frames_done=frames_done,
            frames_expected=frames_expected,
            gpu_hours=gpu_hours,
            cost=cost,
            eta_seconds=eta_seconds,
            shot_names=tuple(dict.fromkeys(shot_names)),
            pending_plan=self.plan,
        )

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def preview_shots(self, shots: list[RenderShot] | None = None) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("render_preview"):
            return False
        if self.workers.is_running("render_benchmark"):
            self.preview_error.emit("A benchmark is already running.")
            return False
        targets = [
            shot
            for shot in (shots or self.selected_shots)
            if not self.is_shot_locked(shot)
        ]
        if not targets:
            self.preview_error.emit("The selected shots are already rendering.")
            return False
        if self.settings.preview_backend == "vast" and self.offer is None:
            self.preview_error.emit(
                "Scan with the Vast backend before using Vast previews."
            )
            return False
        import uuid

        self._active_run_id = uuid.uuid4().hex[:12]
        self._preview_run_id = self._active_run_id
        self._preview_rendered = 0
        self._preview_total = len(targets)
        backend = (
            "vast" if self.settings.preview_backend == "vast" else "local"
        )
        preview_offer = self.offer if backend == "vast" else None
        self._preview_cards = [
            RenderNodeCardModel(
                node=0,
                status="queued",
                message="Preparing preview...",
                run_id=self._preview_run_id,
                run_label="preview",
                gpu_name=(
                    str(getattr(preview_offer, "gpu_name", "") or "")
                    if backend == "vast"
                    else "Local workstation"
                ),
                region=str(getattr(preview_offer, "geolocation", "") or ""),
                price_per_hour=float(
                    getattr(preview_offer, "price_per_hour", 0.0) or 0.0
                ),
                offer_id=int(getattr(preview_offer, "id", 0) or 0),
                frames_expected=len(targets),
                launch=self._launch_config(self.settings),
            )
        ]
        self._sync_node_cards()
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
            bake_geometry_nodes=self.bake_geometry_nodes_effective(targets),
            min_cpu_ram_gb=self.min_cpu_ram_gb_effective(targets),
        )
        worker.preview_ready.connect(self._on_preview_ready)
        worker.preview_progress.connect(self.preview_progress)
        worker.burst_progress.connect(self.burst_progress)
        worker.finished_previews.connect(self._on_previews_finished)
        self.preview_running.emit(True)
        if not self._runs:
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
        self._preview_rendered += 1
        self._update_preview_card(
            status="rendering",
            message=f"Preview ready: {shot_name}",
            current_shot=shot_name,
        )
        self._save_preview_index()
        self._write_status(
            preview=str(path),
            previews={
                name: str(item) for name, item in self.preview_paths.items()
            },
        )
        self.preview_ready.emit(shot_name, str(path))

    def _on_preview_progress_status(
        self, shot_name: str, done: int, total: int, seconds: float
    ) -> None:
        self._update_preview_card(
            status="rendering",
            message=f"{shot_name}: preview frame {done}/{total}",
            current_shot=shot_name,
            seconds_per_frame=float(seconds or 0.0),
            eta_seconds=float(seconds or 0.0),
        )
        self._write_status(
            status="previewing",
            message=f"{shot_name}: preview frame {done}/{total}",
            frames_done=self._preview_rendered,
            frames_expected=self._preview_total,
        )

    def _update_preview_card(self, **updates) -> None:
        if not self._preview_cards:
            return
        card = self._preview_cards[0]
        for key, value in updates.items():
            setattr(card, key, value)
        card.frames_expected = max(1, self._preview_total)
        card.frames_done = min(self._preview_rendered, card.frames_expected)
        card.progress_percent = (
            card.frames_done * 100.0 / card.frames_expected
            if card.frames_expected
            else 0.0
        )
        self.node_card_updated.emit(card.key)

    def _on_previews_finished(
        self, rendered: int, total: int, failed: list, report
    ) -> None:
        self.preview_running.emit(False)
        self._finish_audit(
            self._active_run_id,
            ok=not failed,
            message=f"Previews finished ({rendered}/{total}).",
        )
        for card in self._preview_cards:
            card.final = True
            card.eta_seconds = 0.0
            card.status = "completed" if not failed else "failed"
            card.frames_expected = max(1, total)
            card.frames_done = rendered
            card.progress_percent = (
                rendered * 100.0 / card.frames_expected
                if card.frames_expected
                else 0.0
            )
            card.message = f"Previews finished ({rendered}/{total})"
        self._preview_run_id = ""
        self._sync_node_cards()
        self.last_preview_failed = list(failed or [])
        self.last_preview_report = report
        if self._runs:
            self._write_runs_status(f"Previews finished ({rendered}/{total}).")
        else:
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

    def measurement_for(self, shot: RenderShot, backend: str = "remote") -> dict | None:
        if self.project_root is None:
            return None
        profile = "local" if backend == "local" else self.settings.gpu_profile
        try:
            return self.service.measurement(self.project_root, shot, profile)
        except Exception:  # noqa: BLE001
            return None

    def benchmark_estimate(self, shot: RenderShot | None = None):
        """Upload/GPU/frame estimate shown before renting a benchmark node."""
        if self.project_root is None or shot is None:
            return None
        price = float(getattr(self.offer, "price_per_hour", 0.0) or 0.0)
        try:
            return self.service.benchmark_estimate(
                self.project_root,
                shot,
                gpu_profile=self.settings.gpu_profile,
                price_per_hour=price,
                budget=self.settings.budget,
                bake_geometry_nodes=self.bake_geometry_nodes_effective([shot]),
            )
        except Exception:  # noqa: BLE001 - the dialog falls back to the plain prompt
            return None

    def benchmark_selected(
        self, shot: RenderShot | None = None, *, overwrite: bool = False
    ) -> bool:
        if self.project_root is None or self.read_only or not self.shots:
            self.benchmark_error.emit(
                "Scan the project and select a shot before benchmarking."
            )
            return False
        shot = shot or self.selected_shot()
        if shot is None:
            self.benchmark_error.emit("Select a shot to benchmark.")
            return False
        if self.is_shot_locked(shot):
            self.benchmark_error.emit("That shot is already rendering.")
            return False
        if (
            self.workers.is_running("render_benchmark")
            or self.workers.is_running("render_preview")
        ):
            self.benchmark_error.emit("A benchmark or preview is already running.")
            return False
        if not overwrite and self.measurement_for(shot) is not None:
            self.benchmark_error.emit(
                "A benchmark already exists for this shot; confirm the overwrite."
            )
            return False
        estimate = self.benchmark_estimate(shot)
        if estimate is not None and not estimate.selection.frames:
            self.benchmark_error.emit(
                "The shot has no frames in its scene range to benchmark."
            )
            return False
        run_id = uuid.uuid4().hex[:12]
        self._benchmark_run_id = run_id
        self._benchmark_cards = [
            RenderNodeCardModel(
                node=0,
                status="queued",
                message=f"Preparing the benchmark of {shot.relative_path}",
                run_id=run_id,
                run_label="benchmark",
                current_shot=shot.name,
                frames_expected=(
                    len(estimate.selection.frames) if estimate is not None else 0
                ),
            )
        ]
        self._sync_node_cards()
        self.audit.log(
            "run_start",
            run_id=run_id,
            backend="benchmark-vast",
            project=self.project_name,
            shot=shot.name,
            blend=shot.relative_path,
            frames=(
                list(estimate.selection.frames) if estimate is not None else []
            ),
            upload_bytes=estimate.staging.bytes if estimate is not None else 0,
            upload_files=estimate.staging.files if estimate is not None else 0,
            nodes=1,
        )
        worker = RenderBenchmarkWorker(
            self.service,
            self.project_root,
            shot,
            self.settings,
            self.offer,
            audit=self.audit,
            run_id=run_id,
            bake_geometry_nodes=self.bake_geometry_nodes_effective([shot]),
            min_cpu_ram_gb=self.min_cpu_ram_gb_effective([shot]),
        )
        worker.benchmark_progress.connect(self.benchmark_progress)
        worker.benchmark_progress.connect(self._on_burst_progress_status)
        worker.benchmark_finished.connect(self._on_benchmark_finished)
        worker.error.connect(self._on_benchmark_error)
        self.benchmark_running.emit(True)
        frames = (
            ", ".join(str(frame) for frame in estimate.selection.frames)
            if estimate is not None
            else "?"
        )
        self.report_status(
            f"Benchmarking {shot.name} (frames {frames}) on a Vast.ai node...",
            "yellow",
        )
        return self.workers.start("render_benchmark", worker, critical=True)

    def benchmark_batch_estimate(self, shots: list[RenderShot] | None = None):
        """Estimate a multi-shot benchmark that rents a single node."""
        targets = list(shots if shots is not None else self.selected_shots)
        if self.project_root is None or not targets:
            return None
        price = float(getattr(self.offer, "price_per_hour", 0.0) or 0.0)
        try:
            return self.service.benchmark_batch_estimate(
                self.project_root,
                targets,
                gpu_profile=self.settings.gpu_profile,
                price_per_hour=price,
                budget=self.settings.budget,
                bake_geometry_nodes=self.bake_geometry_nodes_effective(targets),
            )
        except Exception:  # noqa: BLE001 - the dialog falls back to a plain prompt
            return None

    def benchmark_shots(
        self,
        shots: list[RenderShot] | None = None,
        *,
        overwrite: bool = False,
    ) -> bool:
        if self.project_root is None or self.read_only or not self.shots:
            self.benchmark_error.emit(
                "Scan the project and select shots before benchmarking."
            )
            return False
        targets = [
            shot
            for shot in (shots if shots is not None else self.selected_shots)
            if not self.is_shot_locked(shot)
        ]
        if not targets:
            self.benchmark_error.emit(
                "The selected shots are locked or already rendering."
            )
            return False
        if (
            self.workers.is_running("render_benchmark")
            or self.workers.is_running("render_preview")
        ):
            self.benchmark_error.emit("A benchmark or preview is already running.")
            return False
        if not overwrite and any(
            self.measurement_for(shot) is not None for shot in targets
        ):
            self.benchmark_error.emit(
                "A benchmark already exists for a selected shot; confirm the "
                "overwrite."
            )
            return False
        estimate = self.benchmark_batch_estimate(targets)
        if estimate is None or not estimate.shots:
            self.benchmark_error.emit(
                "The selected shots have no frames in their scene ranges."
            )
            return False
        run_id = uuid.uuid4().hex[:12]
        self._benchmark_run_id = run_id
        self._benchmark_cards = [
            RenderNodeCardModel(
                node=0,
                status="queued",
                message=f"Preparing {len(estimate.shots)} benchmark(s)",
                run_id=run_id,
                run_label="benchmark",
                frames_expected=estimate.frames,
            )
        ]
        self._sync_node_cards()
        self.audit.log(
            "run_start",
            run_id=run_id,
            backend="benchmark-vast",
            project=self.project_name,
            shots=[shot.name for shot, _selection in estimate.shots],
            blends=[shot.relative_path for shot, _selection in estimate.shots],
            frames=estimate.frames,
            upload_bytes=estimate.staging.bytes,
            upload_files=estimate.staging.files,
            nodes=1,
        )
        worker = RenderBenchmarkBatchWorker(
            self.service,
            self.project_root,
            [shot for shot, _selection in estimate.shots],
            self.settings,
            self.offer,
            audit=self.audit,
            run_id=run_id,
            bake_geometry_nodes=self.bake_geometry_nodes_effective(
                [item for item, _selection in estimate.shots]
            ),
            min_cpu_ram_gb=self.min_cpu_ram_gb_effective(
                [item for item, _selection in estimate.shots]
            ),
        )
        worker.benchmarks_progress.connect(self.benchmark_progress)
        worker.benchmarks_progress.connect(self._on_burst_progress_status)
        worker.benchmarks_finished.connect(self._on_benchmarks_finished)
        worker.error.connect(self._on_benchmark_error)
        self.benchmark_running.emit(True)
        self.report_status(
            f"Benchmarking {len(estimate.shots)} shot(s) on one Vast.ai node...",
            "yellow",
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
        run_id = self._benchmark_run_id
        message = f"Benchmark for {shot_name}: {format_rate(median)}/frame."
        self._finish_benchmark_cards("completed", message)
        self.audit.log(
            "run_finished", run_id=run_id, ok=True, message=message
        )
        self._benchmark_run_id = ""
        self.benchmark_running.emit(False)
        self.report_status(message, "green")
        self.benchmark_finished.emit(shot_name, median)
        self.scan()

    def _on_benchmark_error(self, message: str) -> None:
        run_id = self._benchmark_run_id
        self._finish_benchmark_cards("failed", message)
        self.audit.log(
            "run_finished", run_id=run_id, ok=False, message=message
        )
        self._benchmark_run_id = ""
        self.benchmark_running.emit(False)
        self.benchmark_error.emit(message)

    def _finish_benchmark_cards(self, status: str, message: str) -> None:
        for card in self._benchmark_cards:
            card.status = status
            card.message = message
            card.final = True
            card.eta_seconds = 0.0
        self._sync_node_cards()

    def _on_benchmarks_finished(
        self, results: list, message: str
    ) -> None:
        run_id = self._benchmark_run_id
        self._finish_benchmark_cards("completed", message)
        self.audit.log(
            "run_finished",
            run_id=run_id,
            ok=True,
            message=message,
            results=[
                {"shot": name, "seconds": seconds}
                for name, seconds in (results or ())
            ],
        )
        self._benchmark_run_id = ""
        self.benchmark_running.emit(False)
        self.report_status(message, "green")
        self.benchmarks_finished.emit(list(results or ()), message)
        self.scan()

    # ------------------------------------------------------------------
    # Relaunch a failed node
    # ------------------------------------------------------------------
    def node_card(self, key: str) -> RenderNodeCardModel | None:
        return next(
            (card for card in self.node_cards if card.key == str(key)),
            None,
        )

    def _relaunch_shots(self, card: RenderNodeCardModel) -> list[RenderShot]:
        by_path = {shot.relative_path: shot for shot in self.shots}
        shots: list[RenderShot] = []
        for relative_path, frames in card.assignment:
            shot = by_path.get(relative_path)
            if shot is None:
                continue
            ordered = sorted({int(frame) for frame in frames})
            if not ordered:
                continue
            start = previous = ordered[0]
            for frame in ordered[1:]:
                if frame == previous + 1:
                    previous = frame
                    continue
                shots.append(
                    replace(
                        shot,
                        frame_start=start,
                        frame_end=previous,
                        frame_step=1,
                    )
                )
                start = previous = frame
            shots.append(
                replace(
                    shot,
                    frame_start=start,
                    frame_end=previous,
                    frame_step=1,
                )
            )
        return shots

    def relaunch_plan(self, card: RenderNodeCardModel | None) -> RelaunchPlan | None:
        if self.project_root is None or card is None:
            return None
        if card.status != "failed" or not card.assignment:
            return None
        shots = self._relaunch_shots(card)
        if not shots:
            return None
        launch = card.launch or self._launch_config(self.settings)
        bake_geometry_nodes = self.bake_geometry_nodes_effective(shots)
        launch = replace(
            launch,
            min_cpu_ram_gb=self.min_cpu_ram_gb_effective(shots),
        )
        price = float(card.price_per_hour or 0.0)
        plan = self.service.plan(
            self.project_root,
            target_hours=self.settings.target_hours,
            gpu_profile=launch.gpu_profile,
            quality_override=self.settings.final_quality,
            price_per_hour=price,
            max_nodes=1,
            budget=self.settings.budget,
            shots=shots,
        )
        staging = self.service.staging_estimate(
            self.project_root,
            exclude_names=(
                bake_cache_names(shots) if bake_geometry_nodes else ()
            ),
            shots=shots,
        )
        return RelaunchPlan(
            shots=tuple(shots),
            plan=plan,
            staging=staging,
            launch=launch,
            bake_geometry_nodes=bake_geometry_nodes,
        )

    def clear_queued_relaunch(
        self, card: RenderNodeCardModel | None, *, quiet: bool = False
    ) -> bool:
        """Remove a relaunch run that never reached its worker."""
        if card is None:
            return False
        run = next(
            (
                item
                for item in self._runs.values()
                if item.relaunch_key == card.key
            ),
            None,
        )
        if run is None:
            self._relaunch_active.discard(card.key)
            return False
        worker_key = f"render_burst:{run.run_id}"
        if self.workers.is_running(worker_key):
            if not quiet:
                self.render_error.emit(
                    "The relaunch worker is still running; cancel it first."
                )
            return False
        message = "Queued relaunch cleared."
        self._runs.pop(run.run_id, None)
        self._finish_audit(run.run_id, ok=False, message=message)
        for item in run.cards.values():
            item.status = "failed"
            item.message = message
            item.final = True
            item.eta_seconds = 0.0
        self._release_run(run, ok=False, rendered=0)
        self.report_status(message, "yellow")
        if not quiet:
            self.render_error.emit(
                f"Node {card.node + 1}: {message} You can relaunch it again."
            )
        return True

    def relaunch_node(
        self,
        card: RenderNodeCardModel | None,
        relaunch: RelaunchPlan | None = None,
    ) -> bool:
        if self.project_root is None or self.read_only or card is None:
            return False
        if card.key in self._relaunch_active:
            stale = next(
                (
                    item
                    for item in self._runs.values()
                    if item.relaunch_key == card.key
                ),
                None,
            )
            if stale is not None and not self.workers.is_running(
                f"render_burst:{stale.run_id}"
            ):
                self.clear_queued_relaunch(card, quiet=True)
            else:
                self.render_error.emit("This node is already being relaunched.")
                return False
        if card.status != "failed" or not card.assignment:
            self.render_error.emit("This node has no failed assignment to relaunch.")
            return False
        relaunch = relaunch or self.relaunch_plan(card)
        if relaunch is None or not relaunch.plan.shots:
            self.render_error.emit("The failed node has no frames to relaunch.")
            return False
        launch = relaunch.launch
        snapshot = replace(
            self.settings,
            gpu_profile=launch.gpu_profile,
            max_price_per_hour=launch.max_price_per_hour,
            preferred_region=launch.preferred_region,
            min_inet_down_mbps=launch.min_inet_down_mbps,
            min_inet_up_mbps=launch.min_inet_up_mbps,
            task_type=launch.task_type,
            bake_geometry_nodes=relaunch.bake_geometry_nodes,
        )
        run_id = uuid.uuid4().hex[:12]
        run = RenderRunState(
            run_id=run_id,
            backend="vast",
            plan=relaunch.plan,
            gpu_profile=launch.gpu_profile,
            locked_shots=set(),
            retry=True,
            node_indices=(int(card.node),),
            label="relaunch",
            relaunch_key=card.key,
            settings=snapshot,
        )
        self._create_run_cards(run)
        retry_card = run.cards.get(int(card.node))
        if retry_card is not None:
            retry_card.assignment = card.assignment
            retry_card.frames_expected = int(relaunch.plan.total_frames)
            retry_card.message = (
                f"Searching a new offer and preparing the upload for "
                f"Node {card.node + 1}…"
            )
        self.audit.log(
            "run_start",
            run_id=run_id,
            backend="vast-relaunch",
            project=self.project_name,
            node=int(card.node),
            frames=int(relaunch.plan.total_frames),
            upload_bytes=int(getattr(relaunch.staging, "bytes", 0) or 0),
            upload_files=int(getattr(relaunch.staging, "files", 0) or 0),
            bake_geometry_nodes=relaunch.bake_geometry_nodes,
        )
        self._relaunch_active.add(card.key)
        try:
            self._register_run(run, clear_finished=False)
            worker = RenderBurstWorker(
                self.service,
                self.project_root,
                relaunch.plan,
                max_price_per_hour=launch.max_price_per_hour,
                preferred_region=launch.preferred_region,
                min_inet_down_mbps=launch.min_inet_down_mbps,
                min_inet_up_mbps=launch.min_inet_up_mbps,
                audit=self.audit,
                run_id=run_id,
                skip_existing=True,
                bake_geometry_nodes=relaunch.bake_geometry_nodes,
                min_cpu_ram_gb=relaunch.launch.min_cpu_ram_gb,
                node_indices=[int(card.node)],
                fill_similar_gpus=relaunch.launch.fill_similar_gpus,
                similar_gpu_mode=relaunch.launch.similar_gpu_mode,
                fill_allow_less_vram=relaunch.launch.fill_allow_less_vram,
                gpu_profile=relaunch.launch.gpu_profile,
            )
            worker.burst_progress.connect(self.burst_progress)
            worker.report_ready.connect(self._handle_burst_finished)
            worker.error.connect(
                lambda message, rid=run_id: self._on_run_error(rid, message)
            )
            self.report_status(
                f"Relaunching Node {card.node + 1} with a new offer "
                f"({relaunch.plan.total_frames} frame(s))...",
                "yellow",
            )
            started = self.workers.start(
                f"render_burst:{run_id}", worker, critical=True
            )
            if not started:
                raise RuntimeError("Could not start the relaunch worker.")
            return True
        except Exception as error:  # noqa: BLE001
            self._relaunch_active.discard(card.key)
            self._on_run_error(
                run_id,
                f"Relaunch could not start: {error}",
            )
            return False

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def start_render(self, retry: bool = False) -> bool:
        return self._start_render_plan(self.plan, retry=retry)

    def _start_render_plan(self, plan: RenderPlan | None, retry: bool = False) -> bool:
        if self.project_root is None or self.read_only or plan is None:
            return False
        targets = [
            shot for shot in plan.shots if not self.is_shot_locked(shot)
        ]
        if not targets:
            self.render_error.emit("No shots selected for render.")
            return False
        if (
            self.settings.render_backend == "vast"
            and self.workers.is_running("render_offer")
        ):
            self.render_error.emit(
                "Still searching for a Vast.ai offer. Try again in a moment."
            )
            return False
        if self.settings.render_backend == "vast" and self.offer is None:
            self.render_error.emit(
                "No Vast.ai offer within the price cap; raise the max price or use local."
            )
            return False
        if (
            self.settings.render_backend == "vast"
            and self.candidate_offers
            and len(self.candidate_offers) < int(plan.required_nodes or 0)
        ):
            self.render_error.emit(
                f"Only {len(self.candidate_offers)} of "
                f"{plan.required_nodes} node offers are available. "
                "Fill with similar GPUs, refresh the offers, or cap the plan."
            )
            return False
        if self.workers.is_running("render_preview"):
            self.render_error.emit("A preview is already running.")
            return False
        if len(targets) != len(plan.shots):
            plan = self._plan_for_shots(targets)
            if not plan.shots:
                self.render_error.emit("No pending frames for the unlocked shots.")
                return False
        backend = self.settings.render_backend
        if backend == "local" and any(
            run.backend == "local" for run in self._runs.values()
        ):
            self.render_error.emit("A local render is already running.")
            return False
        if backend == "vast" and self.balance > 0:
            reserved = sum(
                run.plan.estimated_cost
                for run in self._runs.values()
                if run.backend == "vast"
            ) + float(plan.estimated_cost or 0.0)
            if reserved > self.balance:
                self.render_error.emit(
                    "The active runs plus this plan exceed the Vast.ai balance "
                    f"(${reserved:.2f} > ${self.balance:.2f})."
                )
                return False
        run_id = uuid.uuid4().hex[:12]
        run = RenderRunState(
            run_id=run_id,
            backend=backend,
            plan=plan,
            gpu_profile=self.settings.gpu_profile,
            locked_shots={shot.relative_path for shot in plan.shots},
            retry=retry,
            settings=replace(
                self.settings,
                bake_geometry_nodes=self.bake_geometry_nodes_effective(
                    list(plan.shots)
                ),
                min_cpu_ram_gb=self.min_cpu_ram_gb_effective(list(plan.shots)),
            ),
        )
        self._start_audit(run_id, backend, plan)
        self._failed_shots.difference_update(run.locked_shots)
        if backend == "local":
            self._local_run_id = run_id
            self._create_run_cards(run)
            self._register_run(run)
            worker = LocalRenderWorker(
                self.service,
                self.project_root,
                list(plan.shots),
                self.settings,
                skip_existing=retry,
                audit=self.audit,
                run_id=run_id,
            )
            worker.render_progress.connect(self.local_render_progress)
            worker.finished_render.connect(
                lambda reports, rid=run_id: self._on_local_finished(rid, reports)
            )
            worker.error.connect(
                lambda message, rid=run_id: self._on_run_error(rid, message)
            )
            self._progress_by_shot = {}
            self.report_status(
                f"Rendering {plan.total_frames} frame(s) locally...", "yellow"
            )
            return self.workers.start("render_local", worker, critical=True)

        self._create_run_cards(run)
        self._register_run(run)
        worker = RenderBurstWorker(
            self.service,
            self.project_root,
            plan,
            max_price_per_hour=self.settings.max_price_per_hour,
            preferred_region=self.settings.preferred_region,
            min_inet_down_mbps=self.settings.min_inet_down_mbps,
            min_inet_up_mbps=self.settings.min_inet_up_mbps,
            audit=self.audit,
            run_id=run_id,
            skip_existing=retry,
            bake_geometry_nodes=self.bake_geometry_nodes_effective(list(plan.shots)),
            min_cpu_ram_gb=self.min_cpu_ram_gb_effective(list(plan.shots)),
            fill_similar_gpus=self.settings.fill_similar_gpus,
            similar_gpu_mode=self.settings.similar_gpu_mode,
            fill_allow_less_vram=self.settings.fill_allow_less_vram,
            gpu_profile=self.settings.gpu_profile,
        )
        worker.burst_progress.connect(self.burst_progress)
        worker.report_ready.connect(self._handle_burst_finished)
        worker.error.connect(
            lambda message, rid=run_id: self._on_run_error(rid, message)
        )
        self.report_status(
            f"Starting {plan.required_nodes} Vast.ai node(s)...", "yellow"
        )
        return self.workers.start(f"render_burst:{run_id}", worker, critical=True)

    def _register_run(
        self, run: RenderRunState, *, clear_finished: bool = True
    ) -> None:
        self._runs[run.run_id] = run
        if clear_finished:
            self._finished_cards = []
        self._locked_shots.update(run.locked_shots)
        self._sync_node_cards()
        self._emit_shot_reviews()
        self.render_runs_changed.emit(len(self._runs))
        self._write_runs_status()
        self.recalculate()

    def _on_local_finished(self, run_id: str, reports: list) -> None:
        run = self._runs.pop(run_id, None)
        self._local_run_id = ""
        rendered = sum(item.frames_rendered for item in reports)
        ok = bool(reports) and all(item.ok for item in reports)
        message = f"Local render: {rendered} frame(s)."
        self._finish_audit(run_id, ok=ok, message="Local render finished.")
        if run is not None:
            self._update_local_run_cards(run, reports)
            self._store_run_measurements(run)
            self._release_run(run, ok=ok, rendered=rendered)
        if self._runs:
            self._write_runs_status(message)
        else:
            self._write_status(
                status="completed" if ok else "failed",
                message=message,
                frames_done=rendered,
                frames_expected=None,
                nodes=0,
                runs=[],
            )
        self.render_finished.emit(reports)

    def _preview_index_path(self) -> Path | None:
        if self.project_root is None:
            return None
        return self.service.render_root(self.project_root) / ".previews" / "index.json"

    def _load_preview_paths(self) -> None:
        paths: dict[str, Path] = {}
        if self.status_store is not None:
            data = self.status_store.read()
            previews = data.get("previews")
            if isinstance(previews, dict):
                for name, value in previews.items():
                    candidate = Path(str(value))
                    if candidate.is_file():
                        paths[str(name)] = candidate
        index_path = self._preview_index_path()
        if index_path is not None and index_path.is_file():
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if isinstance(data, dict):
                for name, value in data.items():
                    candidate = Path(str(value))
                    if candidate.is_file():
                        paths[str(name)] = candidate
        self.preview_paths = paths

    def _save_preview_index(self) -> None:
        index_path = self._preview_index_path()
        if index_path is None:
            return
        try:
            index_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = index_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {name: str(path) for name, path in self.preview_paths.items()},
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary.replace(index_path)
        except OSError:
            pass

    def latest_preview_path(self, shot: RenderShot) -> Path | None:
        known = self.preview_paths.get(shot.name)
        if known is not None and known.is_file():
            return known
        if self.project_root is None:
            return None
        root = self.service.render_root(self.project_root)
        sequence = shot.sequence or "shots"
        patterns = (
            f".previews/*/shots/{sequence}/{shot.name}.render/frame_*.png",
            f"shots/{sequence}/{shot.name}.render/.previews/*/frame_*.png",
            f"shots/{sequence}/{shot.name}.render/.previews/frame_*.png",
        )
        candidates: list[Path] = []
        for pattern in patterns:
            try:
                candidates.extend(
                    path for path in root.glob(pattern) if path.is_file()
                )
            except OSError:
                continue
        if not candidates:
            return None
        newest = max(candidates, key=lambda path: path.stat().st_mtime)
        self.preview_paths[shot.name] = newest
        self._save_preview_index()
        return newest

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
        for key in self.workers.keys():
            if not (
                key.startswith("render_burst:")
                or key in ("render_local", "render_preview")
            ):
                continue
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
        run_id = str(getattr(report, "run_id", "") or "")
        run = self._runs.pop(run_id, None)
        ok = bool(getattr(report, "ok", False))
        message = getattr(report, "message", "Render finished.")
        self.last_burst_report = report
        self._finish_audit(run_id, ok=ok, message=message)
        if run is not None:
            self._update_burst_run_cards(run, report)
            self._store_run_measurements(run)
            self._release_run(
                run, ok=ok, rendered=int(getattr(report, "frames_rendered", 0))
            )
        if self._runs:
            self._write_runs_status(message)
        else:
            self._write_status(
                status="completed" if ok else "failed",
                message=message,
                frames_done=getattr(report, "frames_rendered", 0),
                cost=getattr(report, "cost", 0.0),
                nodes=0,
                runs=[],
            )
        self.render_finished.emit(report)

    def _on_run_error(self, run_id: str, message: str) -> None:
        run = self._runs.pop(str(run_id or ""), None)
        if self._local_run_id == str(run_id or ""):
            self._local_run_id = ""
        self._finish_audit(run_id, ok=False, message=message)
        if run is not None:
            for card in run.cards.values():
                if not card.final:
                    card.status = "failed"
                    card.message = message
                    card.final = True
                    card.eta_seconds = 0.0
            self._release_run(run, ok=False, rendered=0)
        if self._runs:
            self._write_runs_status(message)
        else:
            self._write_status(
                status="failed", message=message, nodes=0, runs=[]
            )
        self.render_error.emit(message)

    def _release_run(self, run: RenderRunState, *, ok: bool, rendered: int) -> None:
        if run.relaunch_key:
            self._relaunch_active.discard(run.relaunch_key)
        locked = set(run.locked_shots)
        if not ok and rendered <= 0:
            self._failed_shots.update(locked)
        else:
            self._failed_shots.difference_update(locked)
        self._locked_shots.difference_update(locked)
        self._finished_cards.extend(
            card for _node, card in sorted(run.cards.items())
        )
        self._sync_node_cards()
        self._emit_shot_reviews()
        self.render_runs_changed.emit(len(self._runs))
        self.recalculate()

    def _update_burst_run_cards(self, run: RenderRunState, report) -> None:
        used_nodes = {
            int(result.node) for result in (getattr(report, "nodes", ()) or ())
        }
        for node in list(run.cards):
            if node not in used_nodes:
                del run.cards[node]
        for result in getattr(report, "nodes", ()) or ():
            card = run.cards.get(int(result.node))
            if card is None:
                card = RenderNodeCardModel(
                    node=int(result.node),
                    run_id=run.run_id,
                    run_label=run.label or self._run_label(run.plan),
                    launch=self._launch_config(run.settings),
                )
                run.cards[int(result.node)] = card
            card.status = "completed" if result.ok else "failed"
            card.message = result.message
            card.stage = result.stage
            card.instance_id = int(result.instance_id or 0)
            card.frames_done = int(result.frames_done or 0)
            card.frames_expected = int(result.frames_expected or 0)
            card.cost = float(result.cost or 0.0)
            card.progress_percent = (
                card.frames_done * 100.0 / card.frames_expected
                if card.frames_expected
                else 0.0
            )
            card.eta_seconds = 0.0
            card.gpu_name = result.gpu_name or card.gpu_name
            card.region = result.region or card.region
            card.price_per_hour = result.price_per_hour or card.price_per_hour
            card.hub_logs = (self.audit.node_log_path(run.run_id, result.node),)
            card.summary_logs = (
                self.audit.run_dir(run.run_id) / f"node-{result.node}.json",
            )
            card.blender_logs = tuple(Path(path) for path in result.blender_logs or ())
            card.final = True
            self.node_card_updated.emit(card.key)

    def _update_local_run_cards(self, run: RenderRunState, reports: list) -> None:
        card = run.cards.get(0)
        if card is None:
            card = RenderNodeCardModel(
                node=0, run_id=run.run_id, run_label=self._run_label(run.plan)
            )
            run.cards[0] = card
        shots = list(run.plan.shots)
        hub_logs: list[Path] = []
        summary_logs: list[Path] = []
        blender_logs: list[Path] = []
        for index, report in enumerate(reports or []):
            shot = shots[index] if index < len(shots) else None
            if shot is None:
                continue
            node_id = f"local-{shot.name}"
            hub_logs.append(self.audit.node_log_path(run.run_id, node_id))
            summary_logs.append(
                self.audit.run_dir(run.run_id) / f"node-{node_id}.json"
            )
            blender_logs.append(
                self.audit.blender_log_path(run.run_id, node_id)
            )
        card.status = (
            "completed" if not reports or all(item.ok for item in reports) else "failed"
        )
        card.gpu_name = card.gpu_name or "Local workstation"
        card.frames_done = sum(item.frames_rendered for item in reports or [])
        card.frames_expected = sum(item.frames_expected for item in reports or [])
        card.progress_percent = (
            card.frames_done * 100.0 / card.frames_expected
            if card.frames_expected
            else 0.0
        )
        card.eta_seconds = 0.0
        card.message = "Local render finished."
        card.hub_logs = tuple(hub_logs)
        card.summary_logs = tuple(summary_logs)
        card.blender_logs = tuple(blender_logs)
        card.final = True
        self.node_card_updated.emit(card.key)

    def _store_run_measurements(self, run: RenderRunState) -> None:
        if self.project_root is None:
            return
        backend = "local" if run.backend == "local" else "remote"
        profile = "local" if backend == "local" else run.gpu_profile
        gpu_label = (
            run.cards[0].gpu_name
            if run.cards and run.cards[0].gpu_name
            else ("Local workstation" if backend == "local" else "")
        )
        conflicts: list[dict] = []
        for shot in run.plan.shots:
            samples = run.frame_seconds.get(shot.name) or []
            if not samples:
                continue
            seconds = float(statistics.median(samples))
            if seconds <= 0:
                continue
            existing = self.measurement_for(shot, backend)
            item = {
                "shot": shot,
                "backend": backend,
                "gpu_profile": profile,
                "seconds": seconds,
                "existing": existing,
                "gpu_label": gpu_label,
            }
            if existing is None:
                self._apply_measurement(item)
            else:
                conflicts.append(item)
        if conflicts:
            self.measurement_conflicts.emit(conflicts)

    def resolve_measurement_conflict(self, item: dict, replace_it: bool) -> None:
        if replace_it:
            self._apply_measurement(item)
            self.recalculate()

    def _apply_measurement(self, item: dict) -> None:
        if self.project_root is None:
            return
        shot = item["shot"]
        seconds = float(item.get("seconds") or 0.0)
        if seconds <= 0:
            return
        backend = str(item.get("backend") or "remote")
        profile = "local" if backend == "local" else str(
            item.get("gpu_profile") or self.settings.gpu_profile
        )
        try:
            self.service.record_measurement(
                self.project_root,
                shot,
                profile,
                seconds,
                gpu_label=str(item.get("gpu_label") or ""),
            )
        except Exception:  # noqa: BLE001
            return
        for index, candidate in enumerate(self.shots):
            if candidate.relative_path != shot.relative_path:
                continue
            if backend == "local":
                self.shots[index] = replace(
                    candidate, local_measured_seconds=seconds
                )
            else:
                self.shots[index] = replace(
                    candidate,
                    measured_seconds=seconds,
                    measurement_stale=False,
                    measurement_scaled=False,
                    measurement_source_gpu="",
                )
            break

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

    def _start_audit(self, run_id: str, backend: str, plan: RenderPlan | None = None) -> None:
        self._active_run_id = run_id
        audit_plan = plan or self.plan
        self.audit.log(
            "run_start",
            run_id=run_id,
            backend=backend,
            project=self.project_name,
            frames=audit_plan.total_frames if audit_plan else 0,
            nodes=audit_plan.required_nodes if audit_plan else 0,
            cost=audit_plan.estimated_cost if audit_plan else 0.0,
        )

    def _finish_audit(self, run_id: str, *, ok: bool, message: str) -> None:
        if not run_id:
            return
        self.audit.log(
            "run_finished",
            run_id=run_id,
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
        step = max(1, int(shot.frame_step or 1))
        done = 0
        for frame in range(shot.frame_start, shot.frame_end + 1, step):
            if self.service.frame_path(
                self.project_root, shot, frame, self.settings.task_type
            ).is_file():
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

    def render_comments(self, shot: RenderShot) -> dict:
        if self.project_root is None:
            return {"shot": [], "frames": {}}
        return self.service.render_comments(
            self.project_root, shot, self.settings.task_type
        )

    def _comment_author(self) -> str:
        user = getattr(self.auth_service, "current_user", None)
        return str(
            getattr(user, "full_name", "")
            or getattr(user, "email", "")
            or getattr(user, "first_name", "")
            or ""
        )

    def add_render_comment(
        self, shot: RenderShot, text: str, frame: int | None = None
    ) -> dict:
        if self.project_root is None:
            return {"shot": [], "frames": {}}
        return self.service.add_render_comment(
            self.project_root,
            shot,
            text,
            frame=frame,
            author=self._comment_author(),
            task_type=self.settings.task_type,
        )

    def delete_render_comment(self, shot: RenderShot, comment_id: str) -> dict:
        if self.project_root is None:
            return {"shot": [], "frames": {}}
        return self.service.delete_render_comment(
            self.project_root, shot, comment_id, task_type=self.settings.task_type
        )

    def resolve_render_comment(
        self, shot: RenderShot, comment_id: str, resolved: bool
    ) -> dict:
        if self.project_root is None:
            return {"shot": [], "frames": {}}
        return self.service.resolve_render_comment(
            self.project_root,
            shot,
            comment_id,
            resolved,
            task_type=self.settings.task_type,
        )

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
        if result[0]:
            self._emit_shot_reviews()
        self.report_status(result[1], "green" if result[0] else "red")
        return result

    # ------------------------------------------------------------------
    # Kitsu
    # ------------------------------------------------------------------
    def load_kitsu_tasks(self) -> bool:
        if self.production_service is None or not self.project_id:
            return False
        if self.workers.is_running("kitsu_tasks"):
            return False
        worker = KitsuTasksWorker(self.production_service, self.project_id)
        worker.tasks_ready.connect(self._on_kitsu_tasks)
        worker.error.connect(self.kitsu_status_error)
        return self.workers.start("kitsu_tasks", worker)

    def _on_kitsu_tasks(self, tasks: list) -> None:
        self.kitsu_tasks = list(tasks or ())
        self.kitsu_tasks_ready.emit(self.kitsu_tasks)

    def rendered_frame_numbers(self, shot: RenderShot) -> list[int]:
        return self._rendered_frames(shot)

    def suggested_publish_version(self, shot: RenderShot) -> str:
        if self.project_root is None:
            return "v001"
        folder = self.service.kitsu_review_dir(
            self.project_root,
            shot,
            self.settings.video_task_type or self.settings.task_type,
        )
        return next_version(
            folder,
            f"{shot.name}-{self.settings.video_task_type or self.settings.task_type}",
        )

    def publish_shot(
        self,
        shot: RenderShot,
        *,
        task_id: str,
        status: dict,
        comment: str,
        version: str,
        set_thumbnail: bool = False,
    ) -> bool:
        if (
            self.project_root is None
            or self.production_service is None
            or self.read_only
        ):
            return False
        if self.workers.is_running("publish_shot"):
            return False
        frames = self.rendered_frame_numbers(shot)
        if not frames:
            self.report_status("No rendered frames to publish.", "red")
            return False
        worker = PublishShotWorker(
            self.service,
            self.production_service,
            self.project_id,
            self.project_root,
            shot,
            self.settings,
            task_id=task_id,
            task_status=status,
            comment=comment,
            version=version,
            first_frame=min(frames),
            last_frame=max(frames),
            set_thumbnail=set_thumbnail,
        )
        worker.finished_publish.connect(self._on_publish_finished)
        self.report_status("Publishing shot to Kitsu...", "yellow")
        return self.workers.start("publish_shot", worker, critical=True)

    def _on_publish_finished(self, ok: bool, message: str, video: str) -> None:
        self.report_status(message, "green" if ok else "red")
        self.publish_finished.emit(ok, message, video)

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

    def _write_runs_status(self, message: str = "") -> None:
        if self.status_store is None or not self._runs:
            return
        data = self.status_store.read()
        data["project"] = self.project_name
        runs: list[dict] = []
        done = expected = nodes = 0
        cost = 0.0
        for run in sorted(self._runs.values(), key=lambda item: item.started_at):
            run_done = sum(run.progress_by_node.values())
            if not run_done:
                run_done = sum(card.frames_done for card in run.cards.values())
            run_expected = sum(
                card.frames_expected
                for card in run.cards.values()
                if card.frames_expected
            ) or int(run.plan.total_frames or 0)
            run_nodes = len(run.cards) or int(run.plan.required_nodes)
            run_cost = sum(card.cost for card in run.cards.values())
            done += run_done
            expected += run_expected
            nodes += run_nodes
            cost += run_cost
            runs.append(
                {
                    "run_id": run.run_id,
                    "backend": run.backend,
                    "frames_done": run_done,
                    "frames_expected": run_expected,
                    "nodes": run_nodes,
                    "shots": [shot.name for shot in run.plan.shots],
                    "started_at": run.started_at.isoformat(),
                }
            )
        backends = {run.backend for run in self._runs.values()}
        live = self.activity_summary()
        data.update(
            {
                "status": "rendering",
                "backend": next(iter(backends)) if len(backends) == 1 else "mixed",
                "message": message or f"{len(runs)} render run(s) active.",
                "frames_done": live.frames_done or done,
                "frames_expected": live.frames_expected or expected,
                "nodes": live.nodes or nodes,
                "cost": live.cost or cost,
                "runs": runs,
                "started_at": min(
                    run.started_at for run in self._runs.values()
                ).isoformat(),
            }
        )
        data["shots"] = [
            {"name": shot.name, "frames": shot.frames, "ready": shot.is_ready}
            for shot in self.shots
        ]
        self.status_store.write(data)

    def _on_burst_progress_status(self, event) -> None:
        node = int(getattr(event, "node", 0))
        run_id = str(getattr(event, "run_id", "") or "")
        run = self._runs.get(run_id)
        if run is None and getattr(event, "frames_total", 0):
            self._progress_by_node[node] = int(getattr(event, "frames_done", 0))
        card = self._ensure_node_card(run_id, node)
        stage = str(getattr(event, "stage", "") or "")
        terminal = stage in ("finished", "failed")
        if card.final and not terminal:
            return
        log_run_id = run_id or self._active_run_id
        if terminal:
            ok = bool(getattr(event, "ok", stage == "finished"))
            card.status = "completed" if ok else "failed"
            card.final = True
            card.eta_seconds = 0.0
            card.hub_logs = (self.audit.node_log_path(log_run_id, node),)
            card.summary_logs = (
                self.audit.run_dir(log_run_id) / f"node-{node}.json",
            )
            card.blender_logs = tuple(
                Path(path) for path in getattr(event, "blender_logs", ()) or ()
            )
        else:
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
        if getattr(event, "shot", ""):
            card.current_shot = str(event.shot)
        assignment = tuple(getattr(event, "assignment", ()) or ())
        if assignment:
            card.assignment = assignment
        if card.launch is None and run is not None:
            card.launch = self._launch_config(run.settings)
        bytes_total = int(getattr(event, "bytes_total", 0) or 0)
        if bytes_total > 0:
            card.upload_bytes_total = bytes_total
            card.upload_bytes_done = int(getattr(event, "bytes_done", 0) or 0)
        files_total = int(getattr(event, "files_total", 0) or 0)
        if files_total > 0:
            card.upload_files = files_total
        card.frames_done = int(getattr(event, "frames_done", 0) or card.frames_done or 0)
        card.frames_expected = int(
            getattr(event, "frames_total", 0) or card.frames_expected or 0
        )
        if stage == "stage" and card.upload_bytes_total > 0:
            card.progress_percent = min(
                100.0,
                card.upload_bytes_done * 100.0 / card.upload_bytes_total,
            )
        elif card.frames_expected > 0:
            card.progress_percent = min(
                100.0, card.frames_done * 100.0 / card.frames_expected
            )
        if stage == "frame":
            seconds = 0.0
            try:
                payload = json.loads(str(getattr(event, "message", "") or "{}"))
                seconds = float(payload.get("seconds") or 0.0)
            except (TypeError, ValueError):
                seconds = 0.0
            live_path = str(getattr(event, "live_frame_path", "") or "")
            if live_path:
                card.live_frame_path = live_path
                self.live_frame_ready.emit(
                    str(getattr(event, "shot", "") or ""),
                    int(getattr(event, "frame", 0) or 0),
                    live_path,
                    node,
                )
            if seconds > 0:
                samples = self._node_frame_seconds.setdefault(
                    card.key, deque(maxlen=8)
                )
                samples.append(seconds)
                card.seconds_per_frame = sum(samples) / len(samples)
                if run is not None and getattr(event, "shot", ""):
                    run.frame_seconds.setdefault(str(event.shot), []).append(seconds)
        if run is not None:
            run.progress_by_node[node] = card.frames_done
        remaining = max(0, card.frames_expected - card.frames_done)
        if card.seconds_per_frame > 0 and stage in ("frame", "render"):
            card.eta_seconds = card.seconds_per_frame * remaining
        elif stage in ("sync", "validate", "destroy") or card.status in ("completed", "failed", "destroyed"):
            card.eta_seconds = 0.0
        self.node_card_updated.emit(card.key)
        if run is not None:
            self._write_runs_status(str(getattr(event, "message", "") or ""))
            return
        if run_id and run_id == self._preview_run_id:
            if not self._runs:
                self._write_status(
                    status="previewing",
                    message=getattr(event, "message", ""),
                )
            return
        if run_id and run_id == self._benchmark_run_id:
            return
        expected_total = sum(
            card.frames_expected for card in self.node_cards if card.frames_expected
        )
        self._write_status(
            status="rendering",
            message=getattr(event, "message", ""),
            frames_done=sum(self._progress_by_node.values()),
            frames_expected=(
                expected_total
                or (self.plan.total_frames if self.plan else None)
            ),
        )

    def _on_local_progress_status(self, shot_name: str, done: int, total: int, seconds: float) -> None:
        run = self._runs.get(self._local_run_id)
        self._progress_by_shot[shot_name] = int(done)
        card = self._ensure_node_card(self._local_run_id, 0)
        card.status = "rendering"
        card.current_shot = shot_name
        card.message = f"{shot_name}: {done}/{total} ({format_rate(seconds)})"
        card.frames_done = sum(self._progress_by_shot.values())
        card.frames_expected = (
            run.plan.total_frames
            if run is not None
            else (self.plan.total_frames if self.plan else card.frames_expected)
        )
        if card.frames_expected:
            card.progress_percent = min(
                100.0, card.frames_done * 100.0 / card.frames_expected
            )
        if seconds > 0:
            samples = self._node_frame_seconds.setdefault(
                card.key, deque(maxlen=8)
            )
            samples.append(float(seconds))
            card.seconds_per_frame = sum(samples) / len(samples)
            card.eta_seconds = card.seconds_per_frame * max(
                0, card.frames_expected - card.frames_done
            )
            if run is not None:
                run.frame_seconds.setdefault(shot_name, []).append(float(seconds))
        if run is not None:
            run.progress_by_node[0] = card.frames_done
        self.node_card_updated.emit(card.key)
        if run is not None:
            self._write_runs_status(
                f"{shot_name}: {done}/{total} ({format_rate(seconds)})"
            )
            return
        self._write_status(
            status="rendering",
            message=f"{shot_name}: {done}/{total} ({format_rate(seconds)})",
            frames_done=sum(self._progress_by_shot.values()),
        )

    def _on_scan_error(self, message: str) -> None:
        self.set_busy(False)
        self.report_status(message, "red")
        if not self._runs:
            self._write_status(status="failed", message=message)

    def _on_preview_error(self, message: str) -> None:
        self.preview_running.emit(False)
        self.report_status(message, "red")
        if not self._runs:
            self._write_status(status="failed", message=message)

    def _on_render_error(self, message: str) -> None:
        self.report_status(message, "red")
        if not self._runs:
            self._write_status(status="failed", message=message)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self.cancel_render()
        self.workers.shutdown()
