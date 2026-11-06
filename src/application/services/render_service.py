# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/render_service.py
# Architectural role: Application service / render capacity and cloud burst
# =========================================================================================

"""Application service for project render planning and direct Vast bursts.

The service scans shot files with the project's isolated Blender, joins the
results with measured render profiles, calculates the node count for a target
duration, and can start a short-lived Vast.ai burst. It has no Qt dependency so
the ViewModel can run it in a worker thread.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from dataclasses import replace
from pathlib import Path
from typing import Callable, Sequence

from src.domain.render.capacity import (
    GPU_PROFILES,
    RenderCapacityCalculator,
    scale_seconds_for_gpu,
)
from src.domain.render.models import RenderPlan, RenderQuality, RenderSettings, RenderShot
from src.domain.workspace.blueprint import ProjectBlueprint
from src.infrastructure.render.burst import (
    BurstProgress,
    BurstReport,
    RenderBurstRunner,
)
from src.infrastructure.render.probe import (
    BlenderProbe,
    RenderProbeError,
    RenderProbeResult,
    iter_blend_files,
)
from src.infrastructure.render.run_audit import RenderRunAuditLogger
from src.infrastructure.render.profiles import (
    PROFILES_FILENAME,
    RenderProfileStore,
)
from src.infrastructure.render.settings import SETTINGS_FILENAME, RenderSettingsStore
from src.infrastructure.render.frame_state import RenderFrameStateStore
from src.infrastructure.render.local import LocalRenderReport, LocalRenderRunner
from src.infrastructure.render.vast import (
    VastProvider,
    VastOffer,
)
from src.infrastructure.render.video import RenderVideoService
from src.infrastructure.sandbox.blender_locator import BlenderLocator

DEFAULT_VAST_SSH_KEY = "~/.ssh/id_ed25519_ppf"
DEFAULT_OUTPUT_FOLDER = "03_render"

ScanProgressCallback = Callable[[str, int, int], None]


class RenderServiceError(RuntimeError):
    """Raised when a render request cannot be completed."""


class RenderService:
    def __init__(
        self,
        vast_provider: VastProvider | None = None,
        *,
        production_folder: str = "",
        output_folder: str = DEFAULT_OUTPUT_FOLDER,
        ssh_key_path: str = DEFAULT_VAST_SSH_KEY,
        calculator: RenderCapacityCalculator | None = None,
    ) -> None:
        self._vast = vast_provider
        self.production_folder = production_folder
        self.output_folder = output_folder
        self.ssh_key_path = ssh_key_path
        self.calculator = calculator or RenderCapacityCalculator()
        self.video = RenderVideoService()

    # ------------------------------------------------------------------
    # Project discovery
    # ------------------------------------------------------------------
    @staticmethod
    def load_blueprint(project_root: Path | str) -> ProjectBlueprint:
        root = Path(project_root)
        for candidate in sorted(root.glob("*/project_init.json")):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data:
                return ProjectBlueprint.from_dict(data)
        raise RenderServiceError(f"No project_init.json found under {root}")

    def _production_folder(self, project_root: Path, blueprint: ProjectBlueprint) -> str:
        return self.production_folder or blueprint.topography.vfs_svn

    def profile_store(self, project_root: Path, blueprint: ProjectBlueprint) -> RenderProfileStore:
        return RenderProfileStore(
            Path(project_root) / blueprint.topography.vfs_pipeline / PROFILES_FILENAME
        )

    def settings_store(self, project_root: Path, blueprint: ProjectBlueprint) -> RenderSettingsStore:
        return RenderSettingsStore(
            Path(project_root) / blueprint.topography.vfs_pipeline / SETTINGS_FILENAME
        )

    def load_settings(self, project_root: Path | str) -> RenderSettings:
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        return self.settings_store(root, blueprint).load()

    def save_settings(self, project_root: Path | str, settings: RenderSettings) -> None:
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        self.settings_store(root, blueprint).save(settings)

    def render_root(self, project_root: Path | str) -> Path:
        return Path(project_root) / self.output_folder

    def shot_output_dir(
        self,
        project_root: Path | str,
        shot: RenderShot,
        task_type: str = "render",
    ) -> Path:
        """Blender Studio Tools layout: 03_render/shots/<seq>/<shot>.<task>/."""
        return (
            self.render_root(project_root)
            / "shots"
            / (shot.sequence or "shots")
            / f"{shot.name}.{task_type or 'render'}"
        )

    def preview_dir(
        self,
        project_root: Path | str,
        shot: RenderShot,
        *,
        timestamp: str = "",
        task_type: str = "render",
    ) -> Path:
        base = self.shot_output_dir(project_root, shot, task_type) / ".previews"
        return base / timestamp if timestamp else base

    def kitsu_review_dir(
        self,
        project_root: Path | str,
        shot: RenderShot,
        task_type: str = "render",
    ) -> Path:
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        return (
            root
            / blueprint.topography.vfs_shared
            / "editorial"
            / "footage"
            / "pro"
            / (shot.sequence or "shots")
            / shot.name
            / f"{shot.name}-{task_type or 'render'}"
        )

    def kitsu_review_video_path(
        self,
        project_root: Path | str,
        shot: RenderShot,
        task_type: str = "render",
        version: str = "",
    ) -> Path:
        folder = self.kitsu_review_dir(project_root, shot, task_type)
        version = (version or "").strip()
        if not version:
            version = next_version(folder, f"{shot.name}-{task_type}")
        return folder / f"{shot.name}-{task_type}-{version}.mp4"

    def render_review_video_path(
        self,
        project_root: Path | str,
        shot: RenderShot,
        first_frame: int,
        last_frame: int,
        task_type: str = "render",
    ) -> Path:
        folder = self.shot_output_dir(project_root, shot, task_type)
        return folder / f"{shot.name}-{int(first_frame)}-{int(last_frame)}.mp4"

    def resolve_blender(self, project_root: Path, blueprint: ProjectBlueprint) -> Path:
        build_dir = (
            Path(project_root)
            / blueprint.topography.vfs_local
            / "blender-build"
        )
        return BlenderLocator.resolve(build_dir, version=blueprint.blender_version)

    # ------------------------------------------------------------------
    # Shot scanning
    # ------------------------------------------------------------------
    def scan_shots(
        self,
        project_root: Path | str,
        *,
        quality_override: RenderQuality | None = None,
        gpu_profile: str = "rtx_3090",
        progress: ScanProgressCallback | None = None,
    ) -> list[RenderShot]:
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        production_folder = self._production_folder(root, blueprint)
        production_root = root / production_folder
        shots_root = production_root / "pro" / "shots"
        if not shots_root.is_dir():
            raise RenderServiceError(f"No shots folder found at {shots_root}")

        blender = self.resolve_blender(root, blueprint)
        probe = BlenderProbe(blender)
        store = self.profile_store(root, blueprint)
        files = list(iter_blend_files(shots_root))
        shots: list[RenderShot] = []
        for index, path in enumerate(files, start=1):
            if progress is not None:
                progress(path.name, index, len(files))
            try:
                result = probe.probe(path)
            except RenderProbeError as error:
                shots.append(
                    RenderShot(
                        name=path.parent.name,
                        blend_path=path,
                        relative_path=path.relative_to(production_root).as_posix(),
                        sequence=path.parent.parent.name,
                        quality=quality_override or RenderQuality(),
                        frame_start=0,
                        frame_end=0,
                        warnings=(str(error),),
                    )
                )
                continue
            quality = self._quality_for(result, quality_override)
            blend_hash = _file_hash(path)
            relative_path = path.relative_to(production_root).as_posix()
            measured = store.get(
                relative_path,
                gpu_profile,
                quality.key(),
                blend_hash=blend_hash,
            )
            measurement_stale = False
            measurement_scaled = False
            measurement_source_gpu = ""
            if measured is None:
                measured = store.get(relative_path, gpu_profile, quality.key())
                measurement_stale = measured is not None
            if measured is None:
                source_order = [
                    key
                    for key in (
                        "rtx_3090",
                        "rtx_4090",
                        "rtx_a6000",
                        "rtx_4070",
                        "rtx_3080",
                        "rtx_3070",
                    )
                    if key != gpu_profile
                ]
                for source_gpu in source_order:
                    source_seconds = store.get(
                        relative_path,
                        source_gpu,
                        quality.key(),
                        blend_hash=blend_hash,
                    )
                    source_stale = False
                    if source_seconds is None:
                        source_seconds = store.get(
                            relative_path, source_gpu, quality.key()
                        )
                        source_stale = source_seconds is not None
                    if source_seconds is not None:
                        measured = scale_seconds_for_gpu(
                            source_seconds, source_gpu, gpu_profile
                        )
                        measurement_scaled = True
                        measurement_source_gpu = source_gpu
                        measurement_stale = source_stale
                        break
            shots.append(
                self._shot_from_probe(
                    root,
                    production_root,
                    path,
                    result,
                    quality,
                    blend_hash,
                    measured,
                    measurement_stale=measurement_stale,
                    measurement_scaled=measurement_scaled,
                    measurement_source_gpu=measurement_source_gpu,
                )
            )
        return shots

    def _quality_for(
        self,
        result: RenderProbeResult,
        override: RenderQuality | None,
    ) -> RenderQuality:
        if override is None:
            return RenderQuality(
                engine=result.engine,
                resolution_x=result.resolution_x,
                resolution_y=result.resolution_y,
                resolution_percentage=result.resolution_percentage,
                samples=result.samples,
                denoise=result.denoise,
            )
        return replace(override, engine=result.engine)

    def _shot_from_probe(
        self,
        project_root: Path,
        production_root: Path,
        path: Path,
        result: RenderProbeResult,
        quality: RenderQuality,
        blend_hash: str,
        measured: float | None,
        *,
        measurement_stale: bool = False,
        measurement_scaled: bool = False,
        measurement_source_gpu: str = "",
    ) -> RenderShot:
        relative = path.relative_to(production_root).as_posix()
        warnings: list[str] = []
        if not result.has_camera:
            warnings.append("No active scene camera.")
        if result.object_count <= 10 or result.mesh_count == 0:
            warnings.append("Empty or placeholder scene; not ready for render.")
        if result.geometry_node_objects:
            warnings.append(
                f"{result.geometry_node_objects} geometry-node modifier(s); "
                "benchmark this shot before trusting the estimate."
            )
        if measured is None:
            warnings.append("No measured render profile; using a conservative estimate.")
        elif measurement_stale:
            warnings.append(
                "Using a benchmark from a previous version of the .blend; re-benchmark if the scene changed."
            )
        if measurement_scaled:
            source = GPU_PROFILES.get(measurement_source_gpu)
            source_label = source.label if source is not None else measurement_source_gpu
            warnings.append(
                f"Estimated from a {source_label} benchmark; benchmark this GPU for accuracy."
            )
        setup = result.setup
        if not setup.use_nodes or not setup.compositing_enabled:
            warnings.append(
                "Compositing is not enabled; only the active view layer may be written."
            )
        elif setup.enabled_layers:
            disconnected = [
                layer.name
                for layer in setup.enabled_layers
                if not layer.connected_to_output
            ]
            if disconnected:
                warnings.append(
                    "View layer(s) not connected to the compositor output: "
                    + ", ".join(disconnected)
                )
        if setup.use_sequencer:
            warnings.append(
                "Sequencer rendering is enabled; the 3D render may not be what you expect."
            )
        if not setup.writes_per_layer_files:
            warnings.append("Only the composite is written; no per-layer File Output nodes.")
        for image in result.images:
            resolved = _resolve_path(path.parent, image)
            if resolved is not None and not _is_inside(resolved, project_root):
                warnings.append(f"External dependency outside the project: {image}")
        return RenderShot(
            name=path.parent.name,
            blend_path=path,
            relative_path=relative,
            sequence=path.parent.parent.name,
            quality=quality,
            frame_start=result.frame_start,
            frame_end=result.frame_end,
            frame_step=result.frame_step,
            object_count=result.object_count,
            mesh_count=result.mesh_count,
            library_count=result.library_count,
            geometry_node_objects=result.geometry_node_objects,
            has_camera=result.has_camera,
            blend_hash=blend_hash,
            measured_seconds=measured,
            measurement_stale=measurement_stale,
            measurement_scaled=measurement_scaled,
            measurement_source_gpu=measurement_source_gpu,
            setup=result.setup,
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------
    def plan(
        self,
        project_root: Path | str,
        *,
        target_hours: float,
        gpu_profile: str = "rtx_3090",
        quality_override: RenderQuality | None = None,
        price_per_hour: float = 0.0,
        max_nodes: int = 0,
        budget: float = 0.0,
        shots: Sequence[RenderShot] | None = None,
        progress: ScanProgressCallback | None = None,
    ) -> RenderPlan:
        if shots is None:
            shots = self.scan_shots(
                project_root,
                quality_override=quality_override,
                gpu_profile=gpu_profile,
                progress=progress,
            )
        if gpu_profile not in GPU_PROFILES:
            raise RenderServiceError(f"Unknown GPU profile: {gpu_profile}")
        return self.calculator.plan(
            list(shots),
            target_hours=target_hours,
            gpu_profile=gpu_profile,
            price_per_hour=price_per_hour,
            max_nodes=max_nodes,
            budget=budget,
        )

    def record_measurement(
        self,
        project_root: Path | str,
        shot: RenderShot,
        gpu_profile: str,
        seconds: float,
        *,
        gpu_label: str = "",
    ) -> None:
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        store = self.profile_store(root, blueprint)
        store.set(
            shot.relative_path,
            gpu_profile,
            shot.quality.key(),
            seconds,
            blend_hash=shot.blend_hash,
            gpu_label=gpu_label,
        )
        store.save()

    # ------------------------------------------------------------------
    # Vast
    # ------------------------------------------------------------------
    def vast_provider(self) -> VastProvider:
        if self._vast is None:
            self._vast = VastProvider()
        return self._vast

    def vast_balance(self) -> float:
        return self.vast_provider().balance()

    def cheapest_offer(
        self,
        gpu_profile: str,
        *,
        max_price_per_hour: float = 0.0,
        min_disk_gb: int = 40,
        preferred_region: str = "prefer_us",
        min_inet_down_mbps: float = 0.0,
        min_inet_up_mbps: float = 0.0,
    ) -> VastOffer:
        offers = self.vast_provider().choose_offers(
            gpu_profile,
            count=1,
            max_price_per_hour=max_price_per_hour,
            min_disk_gb=min_disk_gb,
            preferred_region=preferred_region,
            min_inet_down_mbps=min_inet_down_mbps,
            min_inet_up_mbps=min_inet_up_mbps,
        )
        if not offers:
            raise RenderServiceError("No Vast.ai offer is available.")
        return offers[0]

    def local_runner(self, project_root: Path | str) -> LocalRenderRunner:
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        return LocalRenderRunner(self.resolve_blender(root, blueprint))

    def selected_shots(
        self,
        shots: Sequence[RenderShot],
        settings: RenderSettings,
    ) -> list[RenderShot]:
        selected = set(settings.selected_shots or ())
        ready = [shot for shot in shots if shot.is_ready]
        if not selected:
            return ready
        return [shot for shot in ready if shot.relative_path in selected]

    def preview_local(
        self,
        project_root: Path | str,
        shot: RenderShot,
        settings: RenderSettings,
        *,
        progress=None,
    ) -> tuple[LocalRenderReport, Path]:
        root = Path(project_root)
        frame = self._preview_frame(shot, settings)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = self.preview_dir(
            root,
            shot,
            timestamp=timestamp,
            task_type=settings.task_type,
        )
        preview_quality = replace(
            settings.preview_quality, engine=shot.quality.engine
        )
        report = self.local_runner(root).render(
            shot.blend_path,
            preview_quality,
            [frame],
            output_dir,
            use_compositing=bool(shot.setup and shot.setup.is_compositing_ready),
            progress=progress,
        )
        return report, output_dir / f"frame_{frame:04d}.png"

    def preview_vast(
        self,
        project_root: Path | str,
        shots: Sequence[RenderShot],
        settings: RenderSettings,
        *,
        offer=None,
        progress=None,
    ) -> tuple[list[tuple[RenderShot, Path]], object]:
        """Render one preview frame per shot on a short-lived Vast node."""
        root = Path(project_root)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        preview_root = root / self.output_folder / ".previews" / timestamp
        preview_shots: list[RenderShot] = []
        frames: dict[str, int] = {}
        for shot in shots:
            frame = self._preview_frame(shot, settings)
            frames[shot.relative_path] = frame
            quality = replace(settings.preview_quality, engine=shot.quality.engine)
            preview_shots.append(
                replace(
                    shot,
                    frame_start=frame,
                    frame_end=frame,
                    frame_step=1,
                    quality=quality,
                    measured_seconds=None,
                    measurement_stale=False,
                )
            )
        price = offer.price_per_hour if offer is not None else 0.0
        plan = self.plan(
            root,
            target_hours=1.0,
            gpu_profile=settings.gpu_profile,
            quality_override=settings.preview_quality,
            price_per_hour=price,
            max_nodes=1,
            budget=settings.budget,
            shots=preview_shots,
        )
        runner = self.build_burst_runner(
            root,
            plan,
            max_price_per_hour=settings.max_price_per_hour,
            output_root=preview_root,
            preferred_region=settings.preferred_region,
            min_inet_down_mbps=settings.min_inet_down_mbps,
            min_inet_up_mbps=settings.min_inet_up_mbps,
        )
        report = runner.run(plan.shots, plan, progress=progress)
        results: list[tuple[RenderShot, Path]] = []
        for shot in preview_shots:
            frame = frames[shot.relative_path]
            image = (
                preview_root
                / "shots"
                / (shot.sequence or "shots")
                / f"{shot.name}.render"
                / f"frame_{frame:04d}.png"
            )
            if image.is_file():
                results.append((shot, image))
        return results, report

    def _preview_frame(self, shot: RenderShot, settings: RenderSettings) -> int:
        mode = (settings.preview_frame_mode or "middle").lower()
        if mode == "first":
            return shot.frame_start
        if mode == "last":
            return shot.frame_end
        if mode == "custom" and settings.preview_frame:
            return max(shot.frame_start, min(shot.frame_end, settings.preview_frame))
        return (shot.frame_start + shot.frame_end) // 2

    def frame_state_store(
        self,
        project_root: Path | str,
        shot: RenderShot,
        task_type: str = "render",
    ) -> RenderFrameStateStore:
        return RenderFrameStateStore(
            self.shot_output_dir(project_root, shot, task_type)
        )

    def sequence_entries(
        self,
        project_root: Path | str,
        shot: RenderShot,
        task_type: str = "render",
    ) -> list[tuple[int, Path | None]]:
        """Return the shot frame range with the existing PNG path for each frame."""
        folder = self.shot_output_dir(project_root, shot, task_type)
        entries: list[tuple[int, Path | None]] = []
        step = max(1, int(shot.frame_step or 1))
        for frame in range(shot.frame_start, shot.frame_end + 1, step):
            path = folder / f"frame_{frame:04d}.png"
            entries.append((frame, path if path.is_file() else None))
        return entries

    def delete_frame(
        self,
        project_root: Path | str,
        shot: RenderShot,
        frame: int,
        task_type: str = "render",
    ) -> tuple[bool, str]:
        """Move one rendered frame to a local trash folder."""
        folder = self.shot_output_dir(project_root, shot, task_type)
        source = folder / f"frame_{int(frame):04d}.png"
        if not source.is_file():
            return False, f"Frame {frame} was not found."
        store = RenderFrameStateStore(folder)
        if store.is_approved(frame):
            return False, "This frame is approved. Unlock it before deleting."
        trash = folder / ".frame_trash"
        trash.mkdir(parents=True, exist_ok=True)
        destination = trash / source.name
        try:
            if destination.exists():
                destination = trash / f"{source.stem}-{int(datetime.now().timestamp())}{source.suffix}"
            shutil.move(str(source), str(destination))
        except OSError as error:
            return False, f"Could not move the frame to the trash: {error}"
        return True, f"Frame {frame} moved to {destination}."

    def approve_frame(
        self,
        project_root: Path | str,
        shot: RenderShot,
        frame: int,
        approved: bool,
        *,
        user: str = "",
        task_type: str = "render",
    ) -> tuple[bool, str]:
        """Lock or unlock a rendered frame so future renders skip it."""
        folder = self.shot_output_dir(project_root, shot, task_type)
        path = folder / f"frame_{int(frame):04d}.png"
        if approved and not path.is_file():
            return False, "Only rendered frames can be approved."
        store = RenderFrameStateStore(folder)
        try:
            if approved:
                store.approve(frame, user=user)
            else:
                store.unapprove(frame)
        except OSError as error:
            return False, f"Could not update the frame state: {error}"
        state = "approved" if approved else "unlocked"
        return True, f"Frame {frame} {state}."

    def create_preview_video(
        self,
        project_root: Path | str,
        shot: RenderShot,
        settings: RenderSettings,
    ) -> Path:
        """Create a fast, half-resolution MP4 for quick review."""
        root = Path(project_root)
        source = self.shot_output_dir(root, shot, settings.task_type)
        preview_dir = self.preview_dir(root, shot, task_type=settings.task_type)
        preview_dir.mkdir(parents=True, exist_ok=True)
        path = preview_dir / (
            f"{shot.name}-preview-{shot.frame_start}-{shot.frame_end}.mp4"
        )
        self.video.create_video(
            source,
            shot.frame_start,
            shot.frame_end,
            shot.setup.fps if shot.setup else 24.0,
            path,
            crf=28,
            preset="veryfast",
            video_filter="scale=iw/2:-2",
        )
        return path

    def create_review_video(
        self,
        project_root: Path | str,
        shot: RenderShot,
        settings: RenderSettings,
        *,
        frames_dir: Path | str | None = None,
        version: str = "",
    ) -> Path:
        root = Path(project_root)
        task_type = settings.video_task_type or settings.task_type or "render"
        source = (
            Path(frames_dir)
            if frames_dir is not None
            else self.shot_output_dir(root, shot, settings.task_type)
        )
        review_dir = self.kitsu_review_dir(root, shot, task_type)
        review_dir.mkdir(parents=True, exist_ok=True)
        chosen_version = version or settings.video_version or next_version(
            review_dir, f"{shot.name}-{task_type}"
        )
        video_path = review_dir / f"{shot.name}-{task_type}-{chosen_version}.mp4"
        first = shot.frame_start
        last = shot.frame_end
        self.video.create_video(
            source,
            first,
            last,
            shot.setup.fps if shot.setup else 24.0,
            video_path,
        )
        render_review = self.render_review_video_path(
            root, shot, first, last, settings.task_type
        )
        try:
            self.video.copy_for_render_review(video_path, render_review)
        except Exception:  # noqa: BLE001 - the review copy is the primary artifact
            pass
        self.video.write_review_metadata(review_dir, video_path.name, source)
        return video_path

    def adjust_plan_for_backend(
        self,
        plan: RenderPlan,
        backend: str,
        local_speed_factor: float = 8.0,
    ) -> RenderPlan:
        """Local rendering uses one workstation and an approximate GPU factor."""
        if (backend or "").strip().lower() != "local":
            return plan
        warnings = tuple(plan.warnings) + (
            "Local estimate uses the measured RTX 3090 time × "
            f"{local_speed_factor:.1f}; the real time depends on this workstation.",
        )
        return replace(
            plan,
            required_nodes=1 if plan.total_frames else 0,
            estimated_wall_seconds=plan.total_gpu_seconds * max(1.0, local_speed_factor),
            estimated_cost=0.0,
            price_per_hour=0.0,
            warnings=warnings,
        )

    def build_burst_runner(
        self,
        project_root: Path | str,
        plan: RenderPlan,
        *,
        max_price_per_hour: float = 0.0,
        output_root: Path | str | None = None,
        preferred_region: str = "prefer_us",
        min_inet_down_mbps: float = 0.0,
        min_inet_up_mbps: float = 0.0,
        bake_particles: bool = False,
        audit: RenderRunAuditLogger | None = None,
        run_id: str = "",
        skip_existing: bool = False,
    ) -> RenderBurstRunner:
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        destination = Path(output_root) if output_root is not None else root / self.output_folder
        return RenderBurstRunner(
            self.vast_provider(),
            project_root=root,
            output_root=destination,
            ssh_key_path=Path(self.ssh_key_path).expanduser(),
            production_folder=self._production_folder(root, blueprint),
            blender_version=blueprint.blender_version,
            max_price_per_hour=max_price_per_hour,
            task_type="render",
            preferred_region=preferred_region,
            min_inet_down_mbps=min_inet_down_mbps,
            min_inet_up_mbps=min_inet_up_mbps,
            bake_particles=bake_particles,
            audit=audit,
            run_id=run_id,
            skip_existing=skip_existing,
        )

    def start_burst(
        self,
        project_root: Path | str,
        plan: RenderPlan,
        *,
        max_price_per_hour: float = 0.0,
        progress: Callable[[BurstProgress], None] | None = None,
        output_root: Path | str | None = None,
        preferred_region: str = "prefer_us",
        min_inet_down_mbps: float = 0.0,
        min_inet_up_mbps: float = 0.0,
        bake_particles: bool = False,
    ) -> BurstReport:
        runner = self.build_burst_runner(
            project_root,
            plan,
            max_price_per_hour=max_price_per_hour,
            output_root=output_root,
            preferred_region=preferred_region,
            min_inet_down_mbps=min_inet_down_mbps,
            min_inet_up_mbps=min_inet_up_mbps,
            bake_particles=bake_particles,
        )
        return runner.run(plan.shots, plan, progress=progress)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _resolve_path(base: Path, value: str) -> Path | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("//"):
        candidate = base / text[2:]
    else:
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = base / candidate
    try:
        return candidate.resolve()
    except OSError:
        return candidate


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def next_version(folder: Path, prefix: str) -> str:
    """Return the next v### for a folder, ignoring non-matching files."""
    highest = 0
    if folder.is_dir():
        for path in folder.iterdir():
            name = path.name
            if not name.startswith(prefix + "-v"):
                continue
            suffix = name[len(prefix) + 2 :]
            digits = suffix.split(".", 1)[0]
            if digits.isdigit():
                highest = max(highest, int(digits))
    return f"v{highest + 1:03d}"
