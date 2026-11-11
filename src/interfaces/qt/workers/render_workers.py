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
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal

from src.application.services.launch_service import LaunchService
from src.application.services.render_service import RenderService
from src.application.services.task_file_resolver import TaskFileResolver
from src.domain.render.frames import representative_frames as _representative_frames  # noqa: F401
from src.domain.render.image_formats import image_format
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
    scan_warning = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        service: RenderService,
        project_root: Path,
        settings: RenderSettings,
        *,
        production_service=None,
        project_id: str = "",
        force: bool = False,
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.settings = settings
        self.production_service = production_service
        self.project_id = str(project_id or "")
        self.force = bool(force)

    def _task_files(self) -> tuple[dict[str, dict], bool]:
        """Resolve every Kitsu shot task to its ``.blend`` file."""
        if self.production_service is None or not self.project_id:
            self.scan_warning.emit(
                "Kitsu is not connected; there are no shot tasks to render."
            )
            return {}, False
        try:
            board = self.production_service.get_project_task_board(self.project_id)
        except Exception as error:  # noqa: BLE001 - the panel stays empty
            self.scan_warning.emit(f"Kitsu is unavailable: {error}")
            return {}, False
        if not board:
            self.scan_warning.emit("No Kitsu shot tasks were found for this project.")
            return {}, True
        production_folder = self.service.production_folder_name(self.project_root)
        resolver = TaskFileResolver()
        by_path: dict[str, list[str]] = {}
        ids: dict[str, str] = {}
        for row in board:
            entity_type = str(
                row.get("entity_type_name") or row.get("entity_type") or ""
            ).strip().lower()
            if entity_type and entity_type != "shot":
                continue
            try:
                resolved = resolver.resolve(
                    self.project_root, row, production_folder
                )
            except Exception:  # noqa: BLE001 - one bad row must not stop the scan
                resolved = None
            if resolved is None:
                continue
            task_type = str(
                row.get("task_type_name") or row.get("task_type") or ""
            ).strip()
            task_id = str(row.get("id") or "").strip()
            types = by_path.setdefault(resolved.relative_path, [])
            if task_type and task_type not in types:
                types.append(task_type)
            if task_id:
                ids.setdefault(resolved.relative_path, task_id)
        if not by_path:
            self.scan_warning.emit("No Kitsu shot tasks were found for this project.")
            return {}, True
        return {
            path: {
                "task_type": " + ".join(types),
                "task_id": ids.get(path, ""),
            }
            for path, types in by_path.items()
        }, True

    def run(self) -> None:
        try:
            task_files, tasks_ok = self._task_files()
            shots = self.service.scan_shots(
                self.project_root,
                quality_override=self.settings.final_quality,
                gpu_profile=self.settings.gpu_profile,
                progress=self.scan_progress.emit,
                task_files=task_files,
                force=self.force,
                save_cache=tasks_ok,
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


class RenderOfferWorker(ManagedWorker):
    """Fetch Vast.ai offers and the balance for a backend switch."""

    offers_ready = Signal(list, float)
    error = Signal(str)

    def __init__(
        self, service: RenderService, count: int, settings: RenderSettings
    ) -> None:
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
            try:
                balance = self.service.vast_balance()
            except Exception:  # noqa: BLE001
                balance = 0.0
            self.offers_ready.emit(offers, balance)
        except Exception as error:  # noqa: BLE001
            self.error.emit(str(error))


class RenderPreviewWorker(ManagedWorker):
    preview_ready = Signal(str, str)  # shot name, image path
    preview_progress = Signal(str, int, int, float)
    burst_progress = Signal(object)
    error = Signal(str)
    finished_previews = Signal(int, int, list, object)

    def __init__(
        self,
        service: RenderService,
        project_root: Path,
        shots: list[RenderShot],
        settings: RenderSettings,
        offer=None,
        audit=None,
        run_id: str = "",
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.shots = list(shots)
        self.settings = settings
        self.offer = offer
        self.audit = audit
        self.run_id = str(run_id or "")
        self._cancelled = False

    def run(self) -> None:
        rendered = 0
        failed: list[str] = []
        report = None
        if self.settings.preview_backend == "vast":
            try:
                results, report = self.service.preview_vast(
                    self.project_root,
                    self.shots,
                    self.settings,
                    offer=self.offer,
                    progress=self.burst_progress.emit,
                    audit=self.audit,
                    run_id=self.run_id,
                )
                successful = set()
                for shot, image in results:
                    rendered += 1
                    successful.add(shot.name)
                    self.preview_ready.emit(shot.name, str(image))
                failed = [shot.name for shot in self.shots if shot.name not in successful]
                if failed:
                    self.error.emit(
                        getattr(report, "message", "Some Vast previews failed.")
                    )
            except Exception as error:  # noqa: BLE001
                failed = [shot.name for shot in self.shots]
                self.error.emit(str(error))
            self.finished_previews.emit(rendered, len(self.shots), failed, report)
            return
        for shot in self.shots:
            if self._cancelled:
                break
            node_id = f"preview-local-{shot.name}"
            log_path = None
            if self.audit is not None:
                log_path = self.audit.blender_log_path(self.run_id, node_id)
                self.audit.node_event(
                    "node_started",
                    run_id=self.run_id,
                    node=node_id,
                    stage="preview",
                    message=f"local preview of {shot.name}",
                    blender_log=str(log_path),
                )
            try:
                report, image = self.service.preview_local(
                    self.project_root,
                    shot,
                    self.settings,
                    progress=lambda done, total, seconds, name=shot.name: self.preview_progress.emit(
                        name, done, total, seconds
                    ),
                    log_path=log_path,
                )
                if self.audit is not None:
                    self.audit.node_event(
                        "node_finished",
                        run_id=self.run_id,
                        node=node_id,
                        stage="preview",
                        ok=report.ok,
                        message=report.message,
                        blender_log=str(log_path or ""),
                    )
                    self.audit.node_summary(
                        self.run_id,
                        node_id,
                        {
                            "node": node_id,
                            "ok": report.ok,
                            "message": report.message,
                            "blender_logs": [str(log_path)] if log_path else [],
                        },
                    )
                if report.ok and image.is_file():
                    rendered += 1
                    self.preview_ready.emit(shot.name, str(image))
                else:
                    failed.append(shot.name)
                    self.error.emit(f"{shot.name}: {report.message}")
            except Exception as error:  # noqa: BLE001
                failed.append(shot.name)
                self.error.emit(f"{shot.name}: {error}")
        self.finished_previews.emit(rendered, len(self.shots), failed, report)

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
                    if not (
                        self.skip_existing
                        and (
                            output_dir
                            / f"frame_{frame:04d}.{image_format(shot.quality.file_format).extension}"
                        ).is_file()
                    )
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


class OpenShotBlendWorker(ManagedWorker):
    """Open one shot .blend with the task sandbox and SVN lock protocol."""

    status = Signal(str, str)  # message, color
    finished_launch = Signal(str, bool, str)  # shot relative path, ok, message

    def __init__(
        self,
        *,
        config_factory,
        launch_service: LaunchService,
        sync_service,
        production_service,
        project_root: Path,
        project_id: str,
        project_name: str,
        shot,
        svn_user: str,
        svn_pwd: str,
        kitsu_user: str,
        kitsu_pwd: str,
        user_role: str,
    ) -> None:
        super().__init__()
        self.config_factory = config_factory
        self.launch_service = launch_service
        self.sync_service = sync_service
        self.production_service = production_service
        self.project_root = Path(project_root)
        self.project_id = str(project_id or "")
        self.project_name = str(project_name or self.project_root.name)
        self.shot = shot
        self.svn_user = svn_user
        self.svn_pwd = svn_pwd
        self.kitsu_user = kitsu_user
        self.kitsu_pwd = kitsu_pwd
        self.user_role = user_role
        self._cancelled = False

    def run(self) -> None:
        locked = False
        try:
            task_data = self._resolve_task_data()
            status = self.sync_service.lock_task_file(
                self.project_root,
                self.shot.relative_path,
                self.svn_user,
                self.svn_pwd,
            )
            locked, lock_message = status
            if not locked:
                self.finished_launch.emit(
                    self.shot.relative_path, False, lock_message
                )
                return
            self.status.emit(lock_message, "green")
            vfs_local = self.config_factory.get_vfs_local_name()
            config_path = self.project_root / vfs_local / "project_config.json"
            if not config_path.is_file():
                self.finished_launch.emit(
                    self.shot.relative_path,
                    False,
                    "The project configuration is missing. Reinstall the workspace.",
                )
                return
            self.launch_service.launch(
                project_root=self.project_root,
                config_path=config_path,
                svn_user=self.svn_user,
                svn_pwd=self.svn_pwd,
                kitsu_user=self.kitsu_user,
                kitsu_pwd=self.kitsu_pwd,
                kitsu_host=self.config_factory.get_kitsu_api_url(),
                user_role=self.user_role,
                task_data=task_data,
                target_file=self.shot.blend_path,
                status_callback=self.status.emit,
                production_folder=self.config_factory.get_vfs_svn_name(),
            )
            self.finished_launch.emit(
                self.shot.relative_path, True, "DCC session finished."
            )
        except Exception as error:  # noqa: BLE001
            self.finished_launch.emit(self.shot.relative_path, False, str(error))
        finally:
            if locked:
                ok, message = self.sync_service.unlock_task_file(
                    self.project_root,
                    self.shot.relative_path,
                    self.svn_user,
                    self.svn_pwd,
                )
                color = "green" if ok else "yellow"
                self.status.emit(message, color)

    def cancel(self) -> None:
        self._cancelled = True

    def _resolve_task_data(self) -> dict:
        target = Path(self.shot.blend_path).resolve()
        resolver = TaskFileResolver(self.config_factory)
        tasks = []
        if self.production_service is not None and self.project_id:
            try:
                tasks = self.production_service.get_project_task_board(self.project_id)
            except Exception:  # noqa: BLE001
                tasks = []
        for task in tasks or []:
            try:
                resolved = resolver.resolve(
                    self.project_root,
                    task,
                    production_folder=self.config_factory.get_vfs_svn_name(),
                )
            except Exception:  # noqa: BLE001
                continue
            if resolved is not None and resolved.absolute_path.resolve() == target:
                return dict(task)
        stem = Path(self.shot.relative_path).stem
        task_type = stem.rsplit("-", 1)[-1] if "-" in stem else "render"
        return {
            "task_type_name": task_type,
            "project_name": self.project_name,
            "project_id": self.project_id,
            "entity_type": "shot",
            "entity_name": self.shot.name,
            "sequence_name": self.shot.sequence,
            "data": {"filepath": self.shot.relative_path},
        }


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
        *,
        audit=None,
        run_id: str = "",
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.shot = shot
        self.settings = settings
        self.offer = offer
        self.audit = audit
        self.run_id = str(run_id or "")
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
            estimate = self.service.benchmark_estimate(
                self.project_root,
                self.shot,
                gpu_profile=self.settings.gpu_profile,
                price_per_hour=(
                    self.offer.price_per_hour if self.offer is not None else 0.0
                ),
                budget=self.settings.budget,
            )
            if not estimate.selection.frames:
                self.error.emit(
                    "The shot has no frames in its scene range to benchmark."
                )
                return
            plan = estimate.plan
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_root = (
                self.service.render_root(self.project_root)
                if estimate.selection.save_to_render
                else self.project_root / "03_render" / ".benchmarks" / timestamp
            )
            runner = self.service.build_burst_runner(
                self.project_root,
                plan,
                max_price_per_hour=self.settings.max_price_per_hour,
                output_root=output_root,
                preferred_region=self.settings.preferred_region,
                min_inet_down_mbps=self.settings.min_inet_down_mbps,
                min_inet_up_mbps=self.settings.min_inet_up_mbps,
                audit=self.audit,
                run_id=self.run_id,
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


class RenderBenchmarkBatchWorker(ManagedWorker):
    """Measure several shots on one Vast node with a single staging pass."""

    benchmarks_progress = Signal(object)
    benchmarks_finished = Signal(list, str)
    error = Signal(str)

    def __init__(
        self,
        service: RenderService,
        project_root: Path,
        shots: list[RenderShot],
        settings: RenderSettings,
        offer,
        *,
        audit=None,
        run_id: str = "",
    ) -> None:
        super().__init__()
        self.service = service
        self.project_root = Path(project_root)
        self.shots = list(shots)
        self.settings = settings
        self.offer = offer
        self.audit = audit
        self.run_id = str(run_id or "")
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
            estimate = self.service.benchmark_batch_estimate(
                self.project_root,
                self.shots,
                gpu_profile=self.settings.gpu_profile,
                price_per_hour=(
                    self.offer.price_per_hour if self.offer is not None else 0.0
                ),
                budget=self.settings.budget,
            )
            if not estimate.shots:
                self.error.emit(
                    "The selected shots have no frames in their scene ranges."
                )
                return
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            temp_root = (
                self.project_root / "03_render" / ".benchmarks" / timestamp
            )
            output_roots = {
                shot.relative_path: (
                    self.service.render_root(self.project_root)
                    if selection.save_to_render
                    else temp_root
                )
                for shot, selection in estimate.shots
            }
            runner = self.service.build_burst_runner(
                self.project_root,
                estimate.plan,
                max_price_per_hour=self.settings.max_price_per_hour,
                output_root=temp_root,
                output_roots=output_roots,
                preferred_region=self.settings.preferred_region,
                min_inet_down_mbps=self.settings.min_inet_down_mbps,
                min_inet_up_mbps=self.settings.min_inet_up_mbps,
                audit=self.audit,
                run_id=self.run_id,
            )
            self.runner = runner
            timings: dict[str, list[float]] = {}

            def on_progress(event) -> None:
                self.benchmarks_progress.emit(event)
                if getattr(event, "stage", "") != "frame":
                    return
                try:
                    payload = json.loads(str(getattr(event, "message", "") or "{}"))
                except ValueError:
                    return
                seconds = float(payload.get("seconds") or 0.0)
                if seconds <= 0:
                    return
                key = str(
                    getattr(event, "shot_path", "")
                    or getattr(event, "shot", "")
                )
                if key:
                    timings.setdefault(key, []).append(seconds)

            report = runner.run(
                estimate.plan.shots, estimate.plan, progress=on_progress
            )
            results: list[tuple[str, float]] = []
            missing: list[str] = []
            for shot, _selection in estimate.shots:
                values = timings.get(shot.relative_path)
                if not values and shot.name in timings:
                    values = timings[shot.name]
                if not values:
                    missing.append(shot.name)
                    continue
                median = float(statistics.median(values))
                self.service.record_measurement(
                    self.project_root,
                    shot,
                    self.settings.gpu_profile,
                    median,
                    gpu_label=(
                        self.offer.gpu_name if self.offer is not None else ""
                    ),
                )
                results.append((shot.name, median))
            if not results:
                self.error.emit(
                    "Benchmark failed: "
                    f"{getattr(report, 'message', 'no timing data')}"
                )
                return
            message = (
                f"Benchmarked {len(results)}/{len(estimate.shots)} shot(s)."
            )
            if missing:
                message += f" No timing for: {', '.join(missing)}."
            self.benchmarks_finished.emit(results, message)
        except Exception as error:  # noqa: BLE001
            self.error.emit(str(error))
