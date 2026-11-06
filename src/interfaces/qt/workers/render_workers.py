# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/render_workers.py
# Architectural role: MVVM workers / render planning and Vast burst
# =========================================================================================

"""Background workers for the render plan dialog.

The Vast burst can run for tens of minutes, so both the project scan and the
burst itself execute in ``ManagedWorker`` threads. Progress is forwarded through
Qt signals, never by touching widgets from the worker.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal

from src.application.services.render_service import RenderService
from src.domain.render.models import RenderPlan, RenderSettings, RenderShot
from src.infrastructure.qt_worker import ManagedWorker
from src.infrastructure.render.frame_state import RenderFrameStateStore
from src.infrastructure.render.local import LocalRenderReport
from src.infrastructure.render.vast import VastOfferError


class RenderBurstWorker(ManagedWorker):
    """Run the short-lived Vast burst for an approved plan."""

    burst_progress = Signal(object)
    report_ready = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        service: RenderService,
        project_root: Path,
        plan: RenderPlan,
        max_price_per_hour: float = 0.0,
        preferred_region: str = "prefer_us",
        min_inet_down_mbps: float = 0.0,
        min_inet_up_mbps: float = 0.0,
        audit=None,
        run_id: str = "",
        skip_existing: bool = False,
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.plan = plan
        self.max_price_per_hour = float(max_price_per_hour)
        self.preferred_region = str(preferred_region or "prefer_us")
        self.min_inet_down_mbps = float(min_inet_down_mbps or 0.0)
        self.min_inet_up_mbps = float(min_inet_up_mbps or 0.0)
        self.audit = audit
        self.run_id = str(run_id or "")
        self.skip_existing = bool(skip_existing)
        self.runner = None

    def run(self) -> None:
        try:
            self.runner = self.service.build_burst_runner(
                self.project_root,
                self.plan,
                max_price_per_hour=self.max_price_per_hour,
                preferred_region=self.preferred_region,
                min_inet_down_mbps=self.min_inet_down_mbps,
                min_inet_up_mbps=self.min_inet_up_mbps,
                audit=self.audit,
                run_id=self.run_id,
                skip_existing=self.skip_existing,
            )
            report = self.runner.run(
                self.plan.shots,
                self.plan,
                progress=self.burst_progress.emit,
            )
            self.report_ready.emit(report)
        except Exception as error:  # noqa: BLE001
            self.error.emit(str(error))

    def cancel(self) -> None:
        if self.runner is not None:
            self.runner.cancel()


class RenderPanelScanWorker(ManagedWorker):
    """Scan the project and return every shot plus the selected plan."""

    shots_ready = Signal(list, object, object, float, list)  # shots, plan, offer, balance, candidates
    scan_progress = Signal(str, int, int)
    error = Signal(str)

    def __init__(
        self,
        service: RenderService,
        project_root: Path,
        settings: RenderSettings,
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.settings = settings

    def run(self) -> None:
        try:
            shots = self.service.scan_shots(
                self.project_root,
                quality_override=self.settings.final_quality,
                gpu_profile=self.settings.gpu_profile,
                progress=self.scan_progress.emit,
            )
            selected = self.service.selected_shots(shots, self.settings)
            pending = self.service.pending_shots(
                self.project_root, selected, task_type=self.settings.task_type
            )
            offer = None
            balance = 0.0
            price = 0.0
            offer_warning = ""
            needs_vast_offer = (
                self.settings.render_backend == "vast"
                or self.settings.preview_backend == "vast"
            )
            if needs_vast_offer:
                try:
                    offer = self.service.cheapest_offer(
                        self.settings.gpu_profile,
                        max_price_per_hour=self.settings.max_price_per_hour,
                        preferred_region=self.settings.preferred_region,
                        min_inet_down_mbps=self.settings.min_inet_down_mbps,
                        min_inet_up_mbps=self.settings.min_inet_up_mbps,
                    )
                    if self.settings.render_backend == "vast":
                        price = offer.price_per_hour
                except VastOfferError as error:
                    offer_warning = str(error)
                try:
                    balance = self.service.vast_balance()
                except Exception:  # noqa: BLE001
                    balance = 0.0
            plan = self.service.plan(
                self.project_root,
                target_hours=self.settings.target_hours,
                gpu_profile=self.settings.gpu_profile,
                quality_override=self.settings.final_quality,
                price_per_hour=price,
                max_nodes=self.settings.max_nodes,
                budget=self.settings.budget,
                shots=pending,
            )
            plan = self.service.adjust_plan_for_backend(
                plan, self.settings.render_backend, self.settings.local_speed_factor
            )
            candidates = []
            if self.settings.render_backend == "vast" and plan.required_nodes > 0:
                try:
                    candidates = self.service.candidate_offers(
                        self.settings.gpu_profile,
                        count=plan.required_nodes,
                        max_price_per_hour=self.settings.max_price_per_hour,
                        preferred_region=self.settings.preferred_region,
                        min_inet_down_mbps=self.settings.min_inet_down_mbps,
                        min_inet_up_mbps=self.settings.min_inet_up_mbps,
                    )
                except VastOfferError as error:
                    offer_warning = offer_warning or str(error)
                if candidates and len(candidates) < plan.required_nodes:
                    from dataclasses import replace as _replace

                    plan = _replace(
                        plan,
                        warnings=tuple(plan.warnings)
                        + (
                            f"Only {len(candidates)} candidate offer(s) for "
                            f"{plan.required_nodes} node(s); Vast.ai availability may change.",
                        ),
                    )
            if offer_warning:
                from dataclasses import replace as _replace

                plan = _replace(plan, warnings=tuple(plan.warnings) + (offer_warning,))
            self.shots_ready.emit(shots, plan, offer, balance, candidates)
        except Exception as error:  # noqa: BLE001
            self.error.emit(str(error))


class RenderCandidatesWorker(ManagedWorker):
    candidates_ready = Signal(list)
    error = Signal(str)

    def __init__(self, service: RenderService, count: int, settings: RenderSettings) -> None:
        super().__init__()
        self.service = service
        self.count = max(1, int(count or 1))
        self.settings = settings

    def run(self) -> None:
        try:
            offers = self.service.candidate_offers(
                self.settings.gpu_profile,
                count=self.count,
                max_price_per_hour=self.settings.max_price_per_hour,
                preferred_region=self.settings.preferred_region,
                min_inet_down_mbps=self.settings.min_inet_down_mbps,
                min_inet_up_mbps=self.settings.min_inet_up_mbps,
            )
            self.candidates_ready.emit(offers)
        except Exception as error:  # noqa: BLE001
            self.error.emit(str(error))


class RenderPreviewWorker(ManagedWorker):
    preview_ready = Signal(str, str)  # shot name, image path
    preview_progress = Signal(str, int, int, float)
    burst_progress = Signal(object)
    error = Signal(str)
    finished_previews = Signal(int, int)

    def __init__(
        self,
        service: RenderService,
        project_root: Path,
        shots: list[RenderShot],
        settings: RenderSettings,
        offer=None,
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.shots = list(shots)
        self.settings = settings
        self.offer = offer
        self._cancelled = False

    def run(self) -> None:
        rendered = 0
        if self.settings.preview_backend == "vast":
            try:
                results, report = self.service.preview_vast(
                    self.project_root,
                    self.shots,
                    self.settings,
                    offer=self.offer,
                    progress=self.burst_progress.emit,
                )
                for shot, image in results:
                    rendered += 1
                    self.preview_ready.emit(shot.name, str(image))
                if not getattr(report, "ok", False):
                    self.error.emit(
                        getattr(report, "message", "Vast preview failed.")
                    )
            except Exception as error:  # noqa: BLE001
                self.error.emit(str(error))
            self.finished_previews.emit(rendered, len(self.shots))
            return
        for shot in self.shots:
            if self._cancelled:
                break
            try:
                report, image = self.service.preview_local(
                    self.project_root,
                    shot,
                    self.settings,
                    progress=lambda done, total, seconds, name=shot.name: self.preview_progress.emit(
                        name, done, total, seconds
                    ),
                )
                if report.ok and image.is_file():
                    rendered += 1
                    self.preview_ready.emit(shot.name, str(image))
            except Exception as error:  # noqa: BLE001
                self.error.emit(f"{shot.name}: {error}")
        self.finished_previews.emit(rendered, len(self.shots))

    def cancel(self) -> None:
        self._cancelled = True


class LocalRenderWorker(ManagedWorker):
    render_progress = Signal(str, int, int, float)
    finished_render = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        service: RenderService,
        project_root: Path,
        shots: list[RenderShot],
        settings: RenderSettings,
        skip_existing: bool = False,
        audit=None,
        run_id: str = "",
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.shots = list(shots)
        self.settings = settings
        self.skip_existing = bool(skip_existing)
        self.audit = audit
        self.run_id = str(run_id or "")
        self.runner = None

    def run(self) -> None:
        reports: list[LocalRenderReport] = []
        try:
            self.runner = self.service.local_runner(self.project_root)
            for shot in self.shots:
                node_id = f"local-{shot.name}"
                output_dir = self.service.shot_output_dir(
                    self.project_root, shot, self.settings.task_type
                )
                state = RenderFrameStateStore(output_dir)
                approved = state.approved_frames()
                frames = [
                    frame
                    for frame in range(
                        shot.frame_start,
                        shot.frame_end + 1,
                        max(1, shot.frame_step),
                    )
                    if not (self.skip_existing and (output_dir / f"frame_{frame:04d}.png").is_file())
                    and frame not in approved
                ]
                if not frames:
                    continue
                log_path = None
                if self.audit is not None:
                    log_path = self.audit.blender_log_path(
                        self.run_id, node_id
                    )
                    self.audit.node_event(
                        "node_started",
                        run_id=self.run_id,
                        node=node_id,
                        stage="render",
                        message=f"local render of {shot.name}",
                        frames_expected=len(frames),
                        blender_log=str(log_path),
                    )
                report = self.runner.render(
                    shot.blend_path,
                    shot.quality,
                    frames,
                    output_dir,
                    use_compositing=bool(
                        shot.setup and shot.setup.compositing_enabled
                    ),
                    progress=lambda done, total, seconds, name=shot.name: self.render_progress.emit(
                        name, done, total, seconds
                    ),
                    log_path=log_path,
                )
                reports.append(report)
                if self.audit is not None:
                    self.audit.node_event(
                        "node_finished",
                        run_id=self.run_id,
                        node=node_id,
                        stage="render",
                        ok=report.ok,
                        message=report.message,
                        frames_done=report.frames_rendered,
                        frames_expected=report.frames_expected,
                        blender_log=str(log_path or ""),
                    )
                    self.audit.node_summary(
                        self.run_id,
                        node_id,
                        {
                            "node": node_id,
                            "ok": report.ok,
                            "message": report.message,
                            "frames_done": report.frames_rendered,
                            "frames_expected": report.frames_expected,
                            "missing": list(report.missing),
                            "blender_logs": [str(log_path)] if log_path else [],
                        },
                    )
            self.finished_render.emit(reports)
        except Exception as error:  # noqa: BLE001
            self.error.emit(str(error))

    def cancel(self) -> None:
        if self.runner is not None:
            self.runner.cancel()


class RenderVideoWorker(ManagedWorker):
    video_ready = Signal(str, str)  # shot name, video path
    error = Signal(str)
    finished_videos = Signal(int, int)

    def __init__(
        self,
        service: RenderService,
        project_root: Path,
        shots: list[RenderShot],
        settings: RenderSettings,
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.shots = list(shots)
        self.settings = settings
        self._cancelled = False

    def run(self) -> None:
        created = 0
        for shot in self.shots:
            if self._cancelled:
                break
            try:
                path = self.service.create_review_video(
                    self.project_root, shot, self.settings
                )
                created += 1
                self.video_ready.emit(shot.name, str(path))
            except Exception as error:  # noqa: BLE001
                self.error.emit(f"{shot.name}: {error}")
        self.finished_videos.emit(created, len(self.shots))

    def cancel(self) -> None:
        self._cancelled = True


class RenderPreviewVideoWorker(ManagedWorker):
    video_ready = Signal(str, str)  # shot name, video path
    error = Signal(str)
    finished_videos = Signal(int, int)

    def __init__(
        self,
        service: RenderService,
        project_root: Path,
        shots: list[RenderShot],
        settings: RenderSettings,
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.shots = list(shots)
        self.settings = settings
        self._cancelled = False

    def run(self) -> None:
        created = 0
        for shot in self.shots:
            if self._cancelled:
                break
            try:
                path = self.service.create_preview_video(
                    self.project_root, shot, self.settings
                )
                created += 1
                self.video_ready.emit(shot.name, str(path))
            except Exception as error:  # noqa: BLE001
                self.error.emit(f"{shot.name}: {error}")
        self.finished_videos.emit(created, len(self.shots))

    def cancel(self) -> None:
        self._cancelled = True


class KitsuStatusesWorker(ManagedWorker):
    statuses_ready = Signal(list)
    error = Signal(str)

    def __init__(self, production_service, project_id: str) -> None:
        super().__init__()
        self.production_service = production_service
        self.project_id = project_id

    def run(self) -> None:
        try:
            self.statuses_ready.emit(
                self.production_service.get_project_task_statuses(self.project_id)
            )
        except Exception as error:  # noqa: BLE001
            self.error.emit(str(error))


class KitsuUploadWorker(ManagedWorker):
    upload_finished = Signal(bool, str)

    def __init__(
        self,
        production_service,
        project_id: str,
        shot_name: str,
        task_type: str,
        status: dict,
        comment: str,
        video_path: str,
    ) -> None:
        super().__init__()
        self.production_service = production_service
        self.project_id = project_id
        self.shot_name = shot_name
        self.task_type = task_type
        self.status = status
        self.comment = comment
        self.video_path = video_path

    def run(self) -> None:
        try:
            board = self.production_service.get_project_task_board(self.project_id)
            task_row = None
            for row in board:
                entity = str(row.get("entity_name") or row.get("entity") or "")
                task_kind = str(row.get("task_type_name") or row.get("task_type") or "")
                if entity == self.shot_name and task_kind.lower() == self.task_type.lower():
                    task_row = row
                    break
            if task_row is None:
                self.upload_finished.emit(
                    False,
                    f"No Kitsu task '{self.task_type}' found for {self.shot_name}.",
                )
                return
            task = self.production_service.kitsu.get_task(str(task_row.get("id")))
            self.production_service.kitsu.publish_preview(
                task,
                self.status,
                comment=self.comment,
                preview_file_path=self.video_path,
                set_thumbnail=True,
            )
            self.upload_finished.emit(
                True,
                f"Uploaded {self.shot_name} to Kitsu and updated the task status.",
            )
        except Exception as error:  # noqa: BLE001
            self.upload_finished.emit(False, str(error))


class RenderBenchmarkWorker(ManagedWorker):
    """Measure representative frames on one Vast node and update the profile."""

    benchmark_progress = Signal(object)
    benchmark_finished = Signal(str, float)
    error = Signal(str)

    def __init__(
        self,
        service: RenderService,
        project_root: Path,
        shot: RenderShot,
        settings: RenderSettings,
        offer,
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.shot = shot
        self.settings = settings
        self.offer = offer
        self.runner = None

    def run(self) -> None:
        try:
            if self.offer is None:
                self.offer = self.service.cheapest_offer(
                    self.settings.gpu_profile,
                    max_price_per_hour=self.settings.max_price_per_hour,
                    preferred_region=self.settings.preferred_region,
                    min_inet_down_mbps=self.settings.min_inet_down_mbps,
                    min_inet_up_mbps=self.settings.min_inet_up_mbps,
                )
            frames = sorted(
                {
                    int(self.shot.frame_start),
                    int((self.shot.frame_start + self.shot.frame_end) // 2),
                    int(self.shot.frame_end),
                }
            )
            bench_shots = [
                replace(
                    self.shot,
                    frame_start=frame,
                    frame_end=frame,
                    frame_step=1,
                    measured_seconds=None,
                    measurement_stale=False,
                )
                for frame in frames
            ]
            plan = self.service.plan(
                self.project_root,
                target_hours=1.0,
                gpu_profile=self.settings.gpu_profile,
                quality_override=self.shot.quality,
                price_per_hour=(
                    self.offer.price_per_hour if self.offer is not None else 0.0
                ),
                max_nodes=1,
                budget=self.settings.budget,
                shots=bench_shots,
            )
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_root = (
                self.project_root / "03_render" / ".benchmarks" / timestamp
            )
            runner = self.service.build_burst_runner(
                self.project_root,
                plan,
                max_price_per_hour=self.settings.max_price_per_hour,
                output_root=output_root,
                preferred_region=self.settings.preferred_region,
                min_inet_down_mbps=self.settings.min_inet_down_mbps,
                min_inet_up_mbps=self.settings.min_inet_up_mbps,
            )
            self.runner = runner
            timings: list[float] = []

            def on_progress(event) -> None:
                self.benchmark_progress.emit(event)
                if getattr(event, "stage", "") != "frame":
                    return
                try:
                    payload = json.loads(str(getattr(event, "message", "") or "{}"))
                except ValueError:
                    return
                seconds = float(payload.get("seconds") or 0.0)
                if seconds > 0:
                    timings.append(seconds)

            report = runner.run(plan.shots, plan, progress=on_progress)
            if not report.ok or not timings:
                self.error.emit(
                    f"Benchmark failed: {getattr(report, 'message', 'no timing data')}"
                )
                return
            median = float(statistics.median(timings))
            self.service.record_measurement(
                self.project_root,
                self.shot,
                self.settings.gpu_profile,
                median,
                gpu_label=self.offer.gpu_name if self.offer is not None else "",
            )
            self.benchmark_finished.emit(self.shot.name, median)
        except Exception as error:  # noqa: BLE001
            self.error.emit(str(error))
