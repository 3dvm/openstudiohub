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

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Signal

from src.application.services.render_service import RenderService
from src.domain.render.models import RenderPlan, RenderSettings, RenderShot
from src.infrastructure.render.status import RenderStatusStore
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.workers.render_workers import (
    KitsuStatusesWorker,
    KitsuUploadWorker,
    LocalRenderWorker,
    RenderBenchmarkWorker,
    RenderBurstWorker,
    RenderPanelScanWorker,
    RenderPreviewWorker,
    RenderVideoWorker,
)
from src.interfaces.qt.workers.worker_manager import WorkerManager


class RenderPanelViewModel(BaseViewModel):
    shots_ready = Signal(list, object, object, float)
    scan_progress = Signal(str, int, int)
    scan_error = Signal(str)

    preview_ready = Signal(str, str)
    preview_progress = Signal(str, int, int, float)
    preview_error = Signal(str)
    preview_finished = Signal(int, int)

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

    kitsu_statuses_ready = Signal(list)
    kitsu_status_error = Signal(str)
    kitsu_upload_finished = Signal(bool, str)

    def __init__(
        self,
        service: RenderService,
        production_service=None,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.service = service
        self.production_service = production_service
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
        self._progress_by_shot: dict[str, int] = {}

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
        self.shots = []
        self.plan = None
        self.offer = None
        self.preview_paths = {}
        self.video_paths = {}
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
        self.settings = replace(
            self.settings, selected_shots=tuple(relative_paths)
        )
        self._save_settings()
        self.recalculate()

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

    def _on_shots_ready(self, shots: list, plan: RenderPlan, offer, balance: float) -> None:
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
                            shots=selected,
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
        self.report_status("Render plan ready.", "green")
        self.shots_ready.emit(self.shots, plan, offer, balance)

    def recalculate(self) -> None:
        if not self.shots or self.project_root is None:
            return
        selected = self.selected_shots
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
                    shots=selected,
                ),
                self.settings.render_backend,
                self.settings.local_speed_factor,
            )
        )
        self.shots_ready.emit(self.shots, self.plan, self.offer, self.balance)

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def preview_shots(self, shots: list[RenderShot] | None = None) -> bool:
        if self.project_root is None or self.read_only:
            return False
        if self.workers.is_running("render_preview"):
            return False
        targets = list(shots or self.selected_shots)
        if not targets:
            return False
        if self.settings.preview_backend == "vast" and self.offer is None:
            self.preview_error.emit(
                "Scan with the Vast backend before using Vast previews."
            )
            return False
        worker = RenderPreviewWorker(
            self.service, self.project_root, targets, self.settings, offer=self.offer
        )
        worker.preview_ready.connect(self._on_preview_ready)
        worker.preview_progress.connect(self.preview_progress)
        worker.burst_progress.connect(self.burst_progress)
        worker.error.connect(self.preview_error)
        worker.finished_previews.connect(self._on_previews_finished)
        self.set_busy(True)
        self._write_status(status="previewing", message="Rendering previews.")
        self.report_status(f"Rendering {len(targets)} preview(s) locally...", "yellow")
        return self.workers.start("render_preview", worker)

    def _on_preview_ready(self, shot_name: str, image_path: str) -> None:
        path = Path(image_path)
        self.preview_paths[shot_name] = path
        self._write_status(preview=str(path))
        self.preview_ready.emit(shot_name, str(path))

    def _on_previews_finished(self, rendered: int, total: int) -> None:
        self.set_busy(False)
        self._write_status(status="ready", message=f"Previews finished ({rendered}/{total}).")
        self.preview_finished.emit(rendered, total)

    def benchmark_selected(self, shot: RenderShot | None = None) -> bool:
        if (
            self.project_root is None
            or self.read_only
            or not self.shots
            or self.offer is None
        ):
            self.benchmark_error.emit(
                "Select a shot, use the Vast backend and scan the project before benchmarking."
            )
            return False
        shot = shot or self.selected_shot()
        if shot is None:
            self.benchmark_error.emit("Select a shot to benchmark.")
            return False
        if self.workers.is_running("render_benchmark"):
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
    def start_render(self) -> bool:
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
        if self.workers.is_running("render_burst") or self.workers.is_running("render_local"):
            return False
        if self.settings.render_backend == "local":
            worker = LocalRenderWorker(
                self.service,
                self.project_root,
                list(self.plan.shots),
                self.settings,
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

        worker = RenderBurstWorker(
            self.service,
            self.project_root,
            self.plan,
            max_price_per_hour=self.settings.max_price_per_hour,
            preferred_region=self.settings.preferred_region,
            min_inet_down_mbps=self.settings.min_inet_down_mbps,
            min_inet_up_mbps=self.settings.min_inet_up_mbps,
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
        self.render_finished.emit(reports)
        self._maybe_create_videos()

    def cancel_render(self) -> None:
        for key in ("render_burst", "render_local", "render_preview"):
            worker = self.workers.get(key)
            if worker is not None and hasattr(worker, "cancel"):
                worker.cancel()

    def _handle_burst_finished(self, report) -> None:
        self.set_busy(False)
        self._write_status(
            status="completed" if getattr(report, "ok", False) else "failed",
            message=getattr(report, "message", "Render finished."),
            frames_done=getattr(report, "frames_rendered", 0),
            cost=getattr(report, "cost", 0.0),
        )
        self.render_finished.emit(report)
        if getattr(report, "ok", False):
            self._maybe_create_videos()

    def _maybe_create_videos(self) -> None:
        if self.settings.video_enabled:
            self.create_videos()

    # ------------------------------------------------------------------
    # Video
    # ------------------------------------------------------------------
    def create_videos(self, shots: list[RenderShot] | None = None) -> bool:
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

    def _on_video_ready(self, shot_name: str, video_path: str) -> None:
        path = Path(video_path)
        self.video_paths[shot_name] = path
        self._write_status(video=str(path))
        self.video_ready.emit(shot_name, str(path))

    def _on_videos_finished(self, created: int, total: int) -> None:
        self.videos_finished.emit(created, total)

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
        self._write_status(
            status="rendering",
            message=getattr(event, "message", ""),
            frames_done=sum(self._progress_by_node.values()),
            frames_expected=(self.plan.total_frames if self.plan else None),
        )

    def _on_local_progress_status(self, shot_name: str, done: int, total: int, seconds: float) -> None:
        self._progress_by_shot[shot_name] = int(done)
        self._write_status(
            status="rendering",
            message=f"{shot_name}: {done}/{total} ({seconds:.1f}s)",
            frames_done=sum(self._progress_by_shot.values()),
        )

    def _on_error_status(self, message: str) -> None:
        self.set_busy(False)
        self._write_status(status="failed", message=message)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self.cancel_render()
        self.workers.shutdown()
