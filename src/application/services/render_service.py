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
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Sequence

from src.domain.render.capacity import (
    GPU_PROFILES,
    RenderCapacityCalculator,
    default_seconds_per_frame,
    gpu_relative_speed,
    scale_seconds_for_gpu,
)
from src.domain.render.frames import BenchmarkFrameSelection, benchmark_frames
from src.domain.render.image_formats import image_format
from src.domain.render.models import (
    DependencyIssue,
    RenderPlan,
    RenderQuality,
    RenderSettings,
    RenderShot,
)
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
from src.infrastructure.render.scan_cache import (
    CachedProbe,
    RenderScanCache,
    ScanCacheData,
)
from src.infrastructure.render.profiles import (
    PROFILES_FILENAME,
    RenderProfileStore,
)
from src.infrastructure.render.settings import SETTINGS_FILENAME, RenderSettingsStore
from src.infrastructure.render.staging import (
    StagingPlan,
    bake_cache_names,
    scan_staging,
    scan_staging_for_shots,
)
from src.infrastructure.render.comments import RenderCommentStore
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


@dataclass(frozen=True)
class BenchmarkEstimate:
    """Everything the UI needs before renting a node for a benchmark."""

    shot: RenderShot
    selection: BenchmarkFrameSelection
    plan: RenderPlan
    staging: StagingPlan


@dataclass(frozen=True)
class BenchmarkBatchEstimate:
    """One node that measures representative frames for several shots."""

    shots: tuple[tuple[RenderShot, BenchmarkFrameSelection], ...]
    plan: RenderPlan
    staging: StagingPlan

    @property
    def frames(self) -> int:
        return sum(len(selection.frames) for _shot, selection in self.shots)


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
    def production_folder_name(self, project_root: Path | str) -> str:
        root = Path(project_root)
        return self._production_folder(root, self.load_blueprint(root))

    def scan_cache(self, project_root: Path | str) -> RenderScanCache:
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        return RenderScanCache.for_project(root, blueprint.topography.vfs_local)

    def scan_shots(
        self,
        project_root: Path | str,
        *,
        quality_override: RenderQuality | None = None,
        gpu_profile: str = "rtx_3090",
        progress: ScanProgressCallback | None = None,
        task_files: dict[str, dict] | None = None,
        force: bool = False,
        save_cache: bool = True,
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
        cache = RenderScanCache.for_project(root, blueprint.topography.vfs_local)
        cached = ScanCacheData() if force else cache.load()
        reuse = (
            not force
            and cached.blender_version == blueprint.blender_version
        )
        candidates: list[tuple[Path, str]] = []
        for path in iter_blend_files(shots_root):
            relative = path.relative_to(production_root).as_posix()
            if task_files is not None and relative not in task_files:
                continue
            candidates.append((path, relative))

        shots: list[RenderShot] = []
        cache_entries: dict[str, CachedProbe] = {}
        for index, (path, relative) in enumerate(candidates, start=1):
            if progress is not None:
                progress(path.name, index, len(candidates))
            meta = (task_files or {}).get(relative) or {}
            task_type = str(meta.get("task_type") or "")
            task_id = str(meta.get("task_id") or "")
            previous = cached.entries.get(relative) if reuse else None
            try:
                stat = path.stat()
            except OSError:
                stat = None
            result: RenderProbeResult | None = None
            blend_hash = ""
            if (
                previous is not None
                and stat is not None
                and previous.size == stat.st_size
                and previous.mtime_ns == stat.st_mtime_ns
            ):
                try:
                    result = RenderProbeResult.from_dict(previous.probe)
                    blend_hash = previous.blend_hash
                except (TypeError, ValueError):
                    result = None
            if result is None:
                blend_hash = _file_hash(path)
                if (
                    previous is not None
                    and previous.blend_hash
                    and previous.blend_hash == blend_hash
                ):
                    try:
                        result = RenderProbeResult.from_dict(previous.probe)
                    except (TypeError, ValueError):
                        result = None
            if result is None:
                try:
                    result = probe.probe(path)
                except RenderProbeError as error:
                    shots.append(
                        RenderShot(
                            name=path.parent.name,
                            blend_path=path,
                            relative_path=relative,
                            sequence=path.parent.parent.name,
                            quality=quality_override or RenderQuality(),
                            frame_start=0,
                            frame_end=0,
                            task_type=task_type,
                            task_id=task_id,
                            warnings=(str(error),),
                        )
                    )
                    if previous is not None:
                        cache_entries[relative] = previous
                    continue
            if stat is not None:
                cache_entries[relative] = CachedProbe(
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    blend_hash=blend_hash,
                    probe=result.to_dict(),
                    task_type=task_type,
                    task_id=task_id,
                )
            shots.append(
                self._shot_with_measurements(
                    root,
                    production_root,
                    path,
                    result,
                    quality_override,
                    gpu_profile,
                    store,
                    blend_hash=blend_hash,
                    task_type=task_type,
                    task_id=task_id,
                )
            )
        if save_cache:
            cache.save(cache_entries, blender_version=blueprint.blender_version)
        return shots

    def cached_shots(
        self,
        project_root: Path | str,
        *,
        quality_override: RenderQuality | None = None,
        gpu_profile: str = "rtx_3090",
    ) -> list[RenderShot] | None:
        """Rebuild the shot list from the local cache without running Blender."""
        root = Path(project_root)
        try:
            blueprint = self.load_blueprint(root)
        except RenderServiceError:
            return None
        production_root = root / self._production_folder(root, blueprint)
        cache = RenderScanCache.for_project(root, blueprint.topography.vfs_local)
        cached = cache.load()
        if not cached.entries or cached.blender_version != blueprint.blender_version:
            return None
        store = self.profile_store(root, blueprint)
        shots: list[RenderShot] = []
        for relative, entry in sorted(cached.entries.items()):
            path = production_root / relative
            try:
                stat = path.stat()
            except OSError:
                continue
            if entry.size != stat.st_size or entry.mtime_ns != stat.st_mtime_ns:
                continue
            try:
                result = RenderProbeResult.from_dict(entry.probe)
            except (TypeError, ValueError):
                continue
            shots.append(
                self._shot_with_measurements(
                    root,
                    production_root,
                    path,
                    result,
                    quality_override,
                    gpu_profile,
                    store,
                    blend_hash=entry.blend_hash,
                    task_type=entry.task_type,
                    task_id=entry.task_id,
                )
            )
        return shots or None

    def fix_external_dependencies(
        self,
        project_root: Path | str,
        owners: Sequence[str],
    ) -> tuple[bool, str]:
        """Pack and locally unpack external files in the owner .blend files."""
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        blender = self.resolve_blender(root, blueprint)
        unique = sorted({str(item) for item in owners or () if str(item)})
        if not unique:
            return False, "No dependency owner files were found."
        script = """import bpy
import sys
owner = sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=owner)
bpy.ops.file.pack_all()
bpy.ops.file.unpack_all(method='USE_LOCAL')
bpy.ops.wm.save_mainfile()
print('OSDEPS::ok')
"""
        readonly = [
            owner
            for owner in unique
            if not os.access(root / owner, os.W_OK)
        ]
        if readonly:
            return (
                False,
                "Acquire the SVN lock for these files before packing: "
                + ", ".join(readonly),
            )
        failures: list[str] = []
        with tempfile.TemporaryDirectory(prefix="openstudio_deps_") as temp_dir:
            script_path = Path(temp_dir) / "fix_dependencies.py"
            script_path.write_text(script, encoding="utf-8")
            env = os.environ.copy()
            env.setdefault("LC_ALL", "C")
            env.setdefault("LANG", "C")
            for owner in unique:
                path = root / owner
                if not path.is_file():
                    failures.append(f"{owner}: not found")
                    continue
                command = [
                    str(blender),
                    "-b",
                    "--factory-startup",
                    "--python",
                    str(script_path),
                    "--",
                    str(path),
                ]
                try:
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=300,
                        env=env,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as error:
                    failures.append(f"{owner}: {error}")
                    continue
                if result.returncode != 0 or "OSDEPS::ok" not in (result.stdout or ""):
                    detail = (result.stderr or result.stdout or "").strip()
                    failures.append(f"{owner}: {detail[-300:] or result.returncode}")
        if failures:
            return False, "Dependency fix failed: " + "; ".join(failures)
        return True, f"Fixed {len(unique)} dependency owner file(s)."

    # ------------------------------------------------------------------
    # Dependency audit
    # ------------------------------------------------------------------
    def audit_dependencies(
        self,
        project_root: Path | str,
        shots: Sequence[RenderShot],
        *,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> list[RenderShot]:
        """Walk every shot's external files and linked .blend libraries."""
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        production_folder = self._production_folder(root, blueprint)
        production_root = root / production_folder
        blender = self.resolve_blender(root, blueprint)
        probe = BlenderProbe(blender)
        cache_path = (
            root
            / blueprint.topography.vfs_local
            / "render_dependency_cache.json"
        )
        cache = self._load_dependency_cache(cache_path)
        audited: list[RenderShot] = []
        total = len(shots)
        for index, shot in enumerate(shots, start=1):
            if progress is not None:
                progress(shot.name, index, total)
            dependencies: set[str] = set()
            issues: set[DependencyIssue] = set()
            self._walk_dependencies(
                shot.blend_path,
                project_root=root,
                production_root=production_root,
                local_root=root / blueprint.topography.vfs_local,
                pipeline_root=root / blueprint.topography.vfs_pipeline,
                probe=probe,
                cache=cache,
                dependencies=dependencies,
                issues=issues,
                visited=set(),
            )
            audited.append(
                replace(
                    shot,
                    dependencies=tuple(sorted(dependencies)),
                    dependencies_audited=True,
                    dependency_issues=tuple(
                        sorted(
                            issues,
                            key=lambda item: (
                                item.status,
                                item.path,
                                item.owner,
                            ),
                        )
                    ),
                )
            )
        self._save_dependency_cache(cache_path, cache)
        return audited

    def _walk_dependencies(
        self,
        blend_path: Path,
        *,
        project_root: Path,
        production_root: Path,
        local_root: Path,
        pipeline_root: Path,
        probe: BlenderProbe,
        cache: dict,
        dependencies: set[str],
        issues: set[DependencyIssue],
        visited: set[str],
    ) -> None:
        blend = Path(blend_path)
        try:
            key = str(blend.resolve())
        except OSError:
            key = str(blend)
        if key in visited:
            return
        visited.add(key)
        raw_paths, authoritative = self._probe_dependency_paths(
            probe, blend, cache
        )
        for raw in raw_paths:
            resolved = _resolve_path(blend.parent, raw)
            if resolved is None:
                continue
            owner = self._relative_or_absolute(blend, project_root)
            kind = self._dependency_kind(resolved)
            if not resolved.exists():
                if self._is_stale_dependency(resolved):
                    continue
                relative_raw = bool(raw) and not Path(raw).is_absolute()
                if relative_raw and not authoritative:
                    continue
                if resolved.suffix or kind == "blend":
                    issues.add(
                        DependencyIssue(
                            path=str(resolved),
                            kind=kind,
                            status="missing",
                            owner=owner,
                        )
                    )
                continue
            if not _is_inside(resolved, project_root):
                issues.add(
                    DependencyIssue(
                        path=str(resolved),
                        kind=kind,
                        status="external",
                        owner=owner,
                    )
                )
                continue
            if not _is_inside(resolved, production_root):
                if _is_inside(resolved, local_root) or _is_inside(
                    resolved, pipeline_root
                ):
                    continue
                issues.add(
                    DependencyIssue(
                        path=str(resolved),
                        kind=kind,
                        status="outside_production",
                        owner=owner,
                    )
                )
                continue
            if not resolved.is_file():
                continue
            try:
                relative = resolved.relative_to(project_root.resolve())
            except ValueError:
                continue
            dependencies.add(relative.as_posix())
            if resolved.suffix.lower() == ".blend":
                self._walk_dependencies(
                    resolved,
                    project_root=project_root,
                    production_root=production_root,
                    local_root=local_root,
                    pipeline_root=pipeline_root,
                    probe=probe,
                    cache=cache,
                    dependencies=dependencies,
                    issues=issues,
                    visited=visited,
                )

    def _probe_dependency_paths(
        self,
        probe: BlenderProbe,
        blend: Path,
        cache: dict,
    ) -> tuple[tuple[str, ...], bool]:
        try:
            stat = blend.stat()
            key = str(blend.resolve())
        except OSError:
            return (), False
        entry = cache.get(key)
        if (
            isinstance(entry, dict)
            and int(entry.get("size") or -1) == stat.st_size
            and int(entry.get("mtime_ns") or -1) == stat.st_mtime_ns
            and isinstance(entry.get("paths"), list)
            and "authoritative" in entry
        ):
            return (
                tuple(str(item) for item in entry["paths"]),
                bool(entry.get("authoritative")),
            )
        try:
            result = probe.probe(blend)
        except RenderProbeError:
            return (), False
        blend_paths = tuple(
            str(item) for item in (result.blend_paths or ()) if str(item)
        )
        authoritative = bool(blend_paths)
        if blend_paths:
            ordered = tuple(sorted(set(blend_paths)))
        else:
            paths = set(result.libraries)
            paths.update(result.images)
            ordered = tuple(sorted(str(item) for item in paths if str(item)))
        cache[key] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "paths": list(ordered),
            "authoritative": authoritative,
        }
        return ordered, authoritative

    @staticmethod
    def _is_stale_dependency(path: Path) -> bool:
        """Return True for known unused BlenderKit export leftovers."""
        text = str(path).replace("\\", "/").lower()
        name = Path(text).name
        if name == "export_blenderkit.blend":
            return True
        if "export_blenderkit" in text and (
            "/temp/" in text or "/tmp/" in text or "local/temp" in text
        ):
            return True
        return False

    @staticmethod
    def _dependency_kind(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".blend":
            return "blend"
        if "blendcache" in path.name.lower():
            return "cache"
        if suffix in (".exr", ".hdr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tx"):
            return "image"
        if suffix in (".mov", ".mp4", ".avi"):
            return "movie"
        if suffix in (".ttf", ".otf"):
            return "font"
        return "file"

    @staticmethod
    def _relative_or_absolute(path: Path, project_root: Path) -> str:
        try:
            return path.resolve().relative_to(project_root.resolve()).as_posix()
        except (OSError, ValueError):
            return str(path)

    @staticmethod
    def _load_dependency_cache(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _save_dependency_cache(path: Path, cache: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError:
            pass

    def _shot_with_measurements(
        self,
        project_root: Path,
        production_root: Path,
        path: Path,
        result: RenderProbeResult,
        quality_override: RenderQuality | None,
        gpu_profile: str,
        store: RenderProfileStore,
        *,
        blend_hash: str,
        task_type: str = "",
        task_id: str = "",
    ) -> RenderShot:
        quality = self._quality_for(result, quality_override)
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
        return self._shot_from_probe(
            project_root,
            production_root,
            path,
            result,
            quality,
            blend_hash,
            measured,
            measurement_stale=measurement_stale,
            measurement_scaled=measurement_scaled,
            measurement_source_gpu=measurement_source_gpu,
            local_measured_seconds=store.get(
                relative_path, "local", quality.key(), blend_hash=blend_hash
            ),
            task_type=task_type,
            task_id=task_id,
        )

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
        local_measured_seconds: float | None = None,
        task_type: str = "",
        task_id: str = "",
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
        missing_particles = [
            cache for cache in result.particle_caches if not cache.baked
        ]
        if missing_particles:
            warnings.append(
                f"{len(missing_particles)} particle system cache(s) missing; "
                "the node will not bake them (geometry-node bakes only)."
            )
        dependencies: set[str] = set()
        source_paths = (
            tuple(result.blend_paths)
            if result.blend_paths
            else (*result.libraries, *result.images)
        )
        for value in source_paths:
            resolved = _resolve_path(path.parent, value)
            if resolved is None:
                continue
            if not resolved.exists() and not Path(value).is_absolute():
                continue
            if not _is_inside(resolved, project_root):
                warnings.append(f"External dependency outside the project: {value}")
                continue
            try:
                dependency_relative = resolved.relative_to(
                    Path(project_root).resolve()
                )
            except ValueError:
                continue
            if resolved.is_file():
                dependencies.add(dependency_relative.as_posix())
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
            local_measured_seconds=local_measured_seconds,
            measurement_stale=measurement_stale,
            measurement_scaled=measurement_scaled,
            measurement_source_gpu=measurement_source_gpu,
            setup=result.setup,
            task_type=task_type,
            task_id=task_id,
            geometry_bakes=tuple(result.geometry_bakes),
            particle_caches=tuple(result.particle_caches),
            warnings=tuple(warnings),
            dependencies=tuple(sorted(dependencies)),
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
        measured_gpu_profile: str = "",
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
        measured_factor = 1.0
        if measured_gpu_profile and measured_gpu_profile != gpu_profile:
            source_speed = max(0.1, gpu_relative_speed(measured_gpu_profile))
            target_speed = max(0.1, gpu_relative_speed(gpu_profile))
            measured_factor = source_speed / target_speed
        return self.calculator.plan(
            list(shots),
            target_hours=target_hours,
            gpu_profile=gpu_profile,
            price_per_hour=price_per_hour,
            max_nodes=max_nodes,
            budget=budget,
            measured_speed_factor=measured_factor,
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

    def measurement(
        self,
        project_root: Path | str,
        shot: RenderShot,
        gpu_profile: str,
    ) -> dict | None:
        """Return the stored seconds-per-frame reference for one shot."""
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        store = self.profile_store(root, blueprint)
        return store.entry(
            shot.relative_path,
            gpu_profile,
            shot.quality.key(),
            blend_hash=shot.blend_hash,
        )

    # ------------------------------------------------------------------
    # Vast
    # ------------------------------------------------------------------
    def vast_provider(self) -> VastProvider:
        if self._vast is None:
            self._vast = VastProvider()
        return self._vast

    def vast_balance(self) -> float:
        return self.vast_provider().balance()

    def candidate_offers(
        self,
        gpu_profile: str,
        *,
        count: int = 1,
        max_price_per_hour: float = 0.0,
        min_disk_gb: int = 40,
        preferred_region: str = "prefer_us",
        min_inet_down_mbps: float = 0.0,
        min_inet_up_mbps: float = 0.0,
        min_cpu_ram_gb: float = 0.0,
        fill_similar: bool = False,
        similar_mode: str = "floor",
        allow_less_vram: bool = False,
    ) -> list[VastOffer]:
        """Return candidate offers for the requested number of nodes.

        These are offers, not reservations: Vast.ai availability can change
        before the instances are rented.
        """
        return self.vast_provider().choose_offers(
            gpu_profile,
            count=max(1, int(count or 1)),
            max_price_per_hour=max_price_per_hour,
            min_disk_gb=min_disk_gb,
            preferred_region=preferred_region,
            min_inet_down_mbps=min_inet_down_mbps,
            min_inet_up_mbps=min_inet_up_mbps,
            min_cpu_ram_gb=min_cpu_ram_gb,
            fill_similar=fill_similar,
            similar_mode=similar_mode,
            allow_less_vram=allow_less_vram,
        )

    def alternate_offers(
        self,
        gpu_profile: str,
        *,
        count: int = 1,
        max_price_per_hour: float = 0.0,
        min_disk_gb: int = 40,
        preferred_region: str = "prefer_us",
        min_inet_down_mbps: float = 0.0,
        min_inet_up_mbps: float = 0.0,
        min_cpu_ram_gb: float = 0.0,
    ):
        """Return valid offers from the other GPU profiles."""
        return self.vast_provider().search_other_profiles(
            gpu_profile,
            count=max(1, int(count or 1)),
            max_price_per_hour=max_price_per_hour,
            min_disk_gb=min_disk_gb,
            preferred_region=preferred_region,
            min_inet_down_mbps=min_inet_down_mbps,
            min_inet_up_mbps=min_inet_up_mbps,
            min_cpu_ram_gb=min_cpu_ram_gb,
        )

    def cheapest_offer(
        self,
        gpu_profile: str,
        *,
        max_price_per_hour: float = 0.0,
        min_disk_gb: int = 40,
        preferred_region: str = "prefer_us",
        min_inet_down_mbps: float = 0.0,
        min_inet_up_mbps: float = 0.0,
        min_cpu_ram_gb: float = 0.0,
        fill_similar: bool = False,
        similar_mode: str = "floor",
        allow_less_vram: bool = False,
    ) -> VastOffer:
        offers = self.candidate_offers(
            gpu_profile,
            count=1,
            max_price_per_hour=max_price_per_hour,
            min_disk_gb=min_disk_gb,
            preferred_region=preferred_region,
            min_inet_down_mbps=min_inet_down_mbps,
            min_inet_up_mbps=min_inet_up_mbps,
            min_cpu_ram_gb=min_cpu_ram_gb,
            fill_similar=fill_similar,
            similar_mode=similar_mode,
            allow_less_vram=allow_less_vram,
        )
        if not offers:
            raise RenderServiceError("No Vast.ai offer is available.")
        return offers[0]

    def local_runner(self, project_root: Path | str) -> LocalRenderRunner:
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        return LocalRenderRunner(self.resolve_blender(root, blueprint))

    def pending_shots(
        self,
        project_root: Path | str,
        shots: Sequence[RenderShot],
        *,
        task_type: str = "render",
    ) -> list[RenderShot]:
        """Return shots adjusted to the frames that still need rendering.

        Approved frames are excluded from the plan; rendered but unapproved
        frames stay in the count so the plan reflects what still needs review.
        """
        pending: list[RenderShot] = []
        for shot in shots:
            approved = len(
                self.frame_state_store(project_root, shot, task_type).approved_frames()
            )
            count = max(0, int(shot.frames) - approved)
            if count <= 0:
                continue
            pending.append(replace(shot, frames_override=count))
        return pending

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
        log_path=None,
    ) -> tuple[LocalRenderReport, Path]:
        root = Path(project_root)
        frame = self.preview_frame(shot, settings)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = self.preview_dir(
            root,
            shot,
            timestamp=timestamp,
            task_type=settings.task_type,
        )
        preview_quality = replace(
            settings.preview_quality,
            engine=shot.quality.engine,
            file_format="PNG",
            color_mode="RGBA",
            color_depth="8",
        )
        report = self.local_runner(root).render(
            shot.blend_path,
            preview_quality,
            [frame],
            output_dir,
            use_compositing=bool(shot.setup and shot.setup.is_compositing_ready),
            progress=progress,
            log_path=log_path,
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
        audit=None,
        run_id: str = "",
        bake_geometry_nodes: bool = False,
        min_cpu_ram_gb: float = 0.0,
    ) -> tuple[list[tuple[RenderShot, Path]], object]:
        """Render one preview frame per shot on a short-lived Vast node."""
        root = Path(project_root)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        preview_root = root / self.output_folder / ".previews" / timestamp
        preview_shots: list[RenderShot] = []
        frames: dict[str, int] = {}
        for shot in shots:
            frame = self.preview_frame(shot, settings)
            frames[shot.relative_path] = frame
            quality = replace(
                settings.preview_quality,
                engine=shot.quality.engine,
                file_format="PNG",
                color_mode="RGBA",
                color_depth="8",
            )
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
            audit=audit,
            run_id=run_id,
            bake_geometry_nodes=bake_geometry_nodes,
            min_cpu_ram_gb=min_cpu_ram_gb,
            fill_similar_gpus=settings.fill_similar_gpus,
            similar_gpu_mode=settings.similar_gpu_mode,
            fill_allow_less_vram=settings.fill_allow_less_vram,
            gpu_profile=settings.gpu_profile,
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

    def preview_frame(self, shot: RenderShot, settings: RenderSettings) -> int:
        override = settings.preview_frame_for(shot.relative_path)
        if override is not None:
            return max(shot.frame_start, min(shot.frame_end, override))
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

    def comment_store(
        self,
        project_root: Path | str,
        shot: RenderShot,
        task_type: str = "render",
    ) -> RenderCommentStore:
        return RenderCommentStore(
            self.shot_output_dir(project_root, shot, task_type)
        )

    def render_comments(
        self,
        project_root: Path | str,
        shot: RenderShot,
        task_type: str = "render",
    ) -> dict:
        return self.comment_store(project_root, shot, task_type).read()

    def add_render_comment(
        self,
        project_root: Path | str,
        shot: RenderShot,
        text: str,
        *,
        frame: int | None = None,
        author: str = "",
        task_type: str = "render",
    ) -> dict:
        return self.comment_store(project_root, shot, task_type).add(
            text, frame=frame, author=author
        )

    def delete_render_comment(
        self,
        project_root: Path | str,
        shot: RenderShot,
        comment_id: str,
        task_type: str = "render",
    ) -> dict:
        return self.comment_store(project_root, shot, task_type).delete(comment_id)

    def resolve_render_comment(
        self,
        project_root: Path | str,
        shot: RenderShot,
        comment_id: str,
        resolved: bool,
        task_type: str = "render",
    ) -> dict:
        return self.comment_store(project_root, shot, task_type).set_resolved(
            comment_id, resolved
        )

    def frame_extension(self, shot: RenderShot) -> str:
        return image_format(shot.quality.file_format).extension

    def frame_path(
        self,
        project_root: Path | str,
        shot: RenderShot,
        frame: int,
        task_type: str = "render",
    ) -> Path:
        folder = self.shot_output_dir(project_root, shot, task_type)
        return folder / f"frame_{int(frame):04d}.{self.frame_extension(shot)}"

    def proxy_frame_path(
        self,
        project_root: Path | str,
        shot: RenderShot,
        frame: int,
        task_type: str = "render",
    ) -> Path:
        folder = self.shot_output_dir(project_root, shot, task_type)
        return folder / ".proxies" / f"frame_{int(frame):04d}.png"

    def display_frame_path(
        self,
        project_root: Path | str,
        shot: RenderShot,
        frame: int,
        task_type: str = "render",
    ) -> Path:
        proxy = self.proxy_frame_path(project_root, shot, frame, task_type)
        if proxy.is_file():
            return proxy
        return self.frame_path(project_root, shot, frame, task_type)

    def sequence_entries(
        self,
        project_root: Path | str,
        shot: RenderShot,
        task_type: str = "render",
    ) -> list[tuple[int, Path | None]]:
        """Return the shot frame range with the existing PNG path for each frame."""
        entries: list[tuple[int, Path | None]] = []
        step = max(1, int(shot.frame_step or 1))
        for frame in range(shot.frame_start, shot.frame_end + 1, step):
            path = self.display_frame_path(project_root, shot, frame, task_type)
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
        ok, message, _deleted = self.delete_frames(
            project_root, shot, [frame], task_type=task_type
        )
        return ok, message

    def delete_frames(
        self,
        project_root: Path | str,
        shot: RenderShot,
        frames: list[int],
        task_type: str = "render",
    ) -> tuple[bool, str, tuple[int, ...]]:
        """Move rendered frames to a local trash folder, skipping approved ones."""
        folder = self.shot_output_dir(project_root, shot, task_type)
        store = RenderFrameStateStore(folder)
        approved = store.approved_frames()
        deleted: list[int] = []
        skipped = 0
        trash = folder / ".frame_trash"
        for frame in sorted({int(item) for item in frames or ()}):
            source = self.frame_path(project_root, shot, frame, task_type)
            if not source.is_file():
                skipped += 1
                continue
            if frame in approved:
                skipped += 1
                continue
            trash.mkdir(parents=True, exist_ok=True)
            destination = trash / source.name
            try:
                if destination.exists():
                    destination = trash / (
                        f"{source.stem}-{int(datetime.now().timestamp())}{source.suffix}"
                    )
                shutil.move(str(source), str(destination))
                proxy = self.proxy_frame_path(project_root, shot, frame, task_type)
                if proxy.is_file():
                    proxy.unlink(missing_ok=True)
            except OSError as error:
                return False, f"Could not move the frames to the trash: {error}", tuple(deleted)
            deleted.append(frame)
        if not deleted:
            return False, "No frames were deleted (approved or missing).", ()
        message = f"Moved {len(deleted)} frame(s) to {trash}."
        if skipped:
            message += f" Skipped {skipped} approved or missing frame(s)."
        return True, message, tuple(deleted)

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
        return self.approve_frames(
            project_root,
            shot,
            [frame],
            approved,
            user=user,
            task_type=task_type,
        )

    def approve_frames(
        self,
        project_root: Path | str,
        shot: RenderShot,
        frames: list[int],
        approved: bool,
        *,
        user: str = "",
        task_type: str = "render",
    ) -> tuple[bool, str]:
        folder = self.shot_output_dir(project_root, shot, task_type)
        selected = sorted({int(item) for item in frames or ()})
        if not selected:
            return False, "Select at least one frame."
        if approved:
            missing = [
                frame
                for frame in selected
                if not self.frame_path(project_root, shot, frame, task_type).is_file()
            ]
            if missing:
                return False, "Only rendered frames can be approved."
        store = RenderFrameStateStore(folder)
        try:
            store.set_approved(selected, approved, user=user)
        except OSError as error:
            return False, f"Could not update the frame state: {error}"
        state = "approved" if approved else "unlocked"
        return True, f"{len(selected)} frame(s) {state}."

    def _video_source(
        self, root: Path, shot: RenderShot, settings: RenderSettings
    ) -> tuple[Path, str]:
        final_dir = self.shot_output_dir(root, shot, settings.task_type)
        final_format = image_format(shot.quality.file_format)
        proxy_dir = final_dir / ".proxies"
        if final_format.identifier != "PNG" and proxy_dir.is_dir():
            if any(proxy_dir.glob("frame_*.png")):
                return proxy_dir, "png"
        return final_dir, final_format.extension

    def create_preview_video(
        self,
        project_root: Path | str,
        shot: RenderShot,
        settings: RenderSettings,
    ) -> Path:
        """Create a fast, half-resolution MP4 for quick review."""
        root = Path(project_root)
        source, extension = self._video_source(root, shot, settings)
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
            extension=extension,
        )
        return path

    def create_publish_video(
        self,
        project_root: Path | str,
        shot: RenderShot,
        settings: RenderSettings,
        *,
        first_frame: int,
        last_frame: int,
        version: str = "",
    ) -> Path:
        """Create the low-quality MP4 that is published to Kitsu."""
        root = Path(project_root)
        source, extension = self._video_source(root, shot, settings)
        review_dir = self.kitsu_review_dir(
            root, shot, settings.video_task_type or settings.task_type
        )
        review_dir.mkdir(parents=True, exist_ok=True)
        chosen_version = version.strip() or next_version(
            review_dir,
            f"{shot.name}-{settings.video_task_type or settings.task_type}",
        )
        video_path = review_dir / (
            f"{shot.name}-{settings.video_task_type or settings.task_type}"
            f"-{chosen_version}.mp4"
        )
        self.video.create_video_with_placeholders(
            source,
            int(first_frame),
            int(last_frame),
            shot.setup.fps if shot.setup else 24.0,
            video_path,
            width=max(1, shot.quality.effective_width),
            height=max(1, shot.quality.effective_height),
            icon_path=(
                Path(__file__).resolve().parents[3]
                / "assets"
                / "icons"
                / "image-off.svg"
            ),
            extension=extension,
            crf=28,
            preset="veryfast",
            video_filter="scale=iw/2:-2",
        )
        self.video.write_review_metadata(review_dir, video_path.name, source)
        return video_path

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
        if frames_dir is not None:
            source = Path(frames_dir)
            extension = image_format(shot.quality.file_format).extension
        else:
            source, extension = self._video_source(root, shot, settings)
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
            extension=extension,
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
        speed = max(1.0, float(local_speed_factor))
        total_seconds = 0.0
        used_local = False
        for shot in plan.shots:
            if shot.local_measured_seconds and shot.local_measured_seconds > 0:
                seconds = float(shot.local_measured_seconds)
                used_local = True
            else:
                seconds = shot.measured_seconds
                if seconds is None:
                    seconds = default_seconds_per_frame(
                        shot.quality, shot.geometry_node_objects
                    ) / max(0.1, gpu_relative_speed(plan.gpu_profile))
                seconds = float(seconds) * speed
            total_seconds += max(0, shot.frames) * max(0.0, seconds)
        detail = (
            "Local estimate uses the measured local times where available"
            if used_local
            else "Local estimate uses the measured RTX 3090 time"
        )
        warnings = tuple(plan.warnings) + (
            f"{detail} × {speed:.1f} for unmeasured shots; the real time depends "
            "on this workstation.",
        )
        return replace(
            plan,
            required_nodes=1 if plan.total_frames else 0,
            estimated_wall_seconds=(
                plan.setup_seconds + total_seconds if plan.total_frames else 0.0
            ),
            estimated_cost=0.0,
            price_per_hour=0.0,
            warnings=warnings,
        )

    def staging_estimate(
        self,
        project_root: Path | str,
        *,
        exclude_names=(),
        shots=None,
    ) -> StagingPlan:
        """Measure the files a Vast node needs for the selected shots."""
        root = Path(project_root)
        blueprint = self.load_blueprint(root)
        return scan_staging_for_shots(
            root,
            self._production_folder(root, blueprint),
            shots,
            exclude_names=exclude_names,
        )

    def benchmark_estimate(
        self,
        project_root: Path | str,
        shot: RenderShot,
        *,
        gpu_profile: str = "rtx_3090",
        price_per_hour: float = 0.0,
        budget: float = 0.0,
        bake_geometry_nodes: bool = False,
    ) -> BenchmarkEstimate:
        """Plan the benchmark frames and the upload they need."""
        root = Path(project_root)
        approved = self.frame_state_store(root, shot, "render").approved_frames()
        selection = benchmark_frames(shot, approved)
        bench_shots = [
            replace(
                shot,
                frame_start=frame,
                frame_end=frame,
                frame_step=1,
                measured_seconds=None,
                measurement_stale=False,
            )
            for frame in selection.frames
        ]
        plan = self.plan(
            root,
            target_hours=1.0,
            gpu_profile=gpu_profile,
            quality_override=shot.quality,
            price_per_hour=price_per_hour,
            max_nodes=1,
            budget=budget,
            shots=bench_shots,
        )
        exclude_names = (
            bake_cache_names((shot,)) if bake_geometry_nodes else ()
        )
        return BenchmarkEstimate(
            shot=shot,
            selection=selection,
            plan=plan,
            staging=self.staging_estimate(
                root,
                exclude_names=exclude_names,
                shots=[shot],
            ),
        )

    def benchmark_batch_estimate(
        self,
        project_root: Path | str,
        shots: Sequence[RenderShot],
        *,
        gpu_profile: str = "rtx_3090",
        price_per_hour: float = 0.0,
        budget: float = 0.0,
        bake_geometry_nodes: bool = False,
    ) -> BenchmarkBatchEstimate:
        """Plan several benchmarks on one node with a single staging pass."""
        root = Path(project_root)
        selections: list[tuple[RenderShot, BenchmarkFrameSelection]] = []
        bench_shots: list[RenderShot] = []
        for shot in shots:
            approved = self.frame_state_store(
                root, shot, "render"
            ).approved_frames()
            selection = benchmark_frames(shot, approved)
            if not selection.frames:
                continue
            selections.append((shot, selection))
            bench_shots.extend(
                replace(
                    shot,
                    frame_start=frame,
                    frame_end=frame,
                    frame_step=1,
                    measured_seconds=None,
                    measurement_stale=False,
                )
                for frame in selection.frames
            )
        plan = self.plan(
            root,
            target_hours=1.0,
            gpu_profile=gpu_profile,
            price_per_hour=price_per_hour,
            max_nodes=1,
            budget=budget,
            shots=bench_shots,
        )
        exclude_names = (
            bake_cache_names(tuple(shot for shot, _selection in selections))
            if bake_geometry_nodes
            else ()
        )
        return BenchmarkBatchEstimate(
            shots=tuple(selections),
            plan=plan,
            staging=self.staging_estimate(root, exclude_names=exclude_names),
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
        bake_geometry_nodes: bool = False,
        min_cpu_ram_gb: float = 0.0,
        fill_similar_gpus: bool = False,
        similar_gpu_mode: str = "floor",
        fill_allow_less_vram: bool = False,
        gpu_profile: str = "",
        audit: RenderRunAuditLogger | None = None,
        run_id: str = "",
        skip_existing: bool = False,
        output_roots: dict[str, Path | str] | None = None,
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
            bake_geometry_nodes=bake_geometry_nodes,
            min_cpu_ram_gb=min_cpu_ram_gb,
            fill_similar_gpus=fill_similar_gpus,
            similar_gpu_mode=similar_gpu_mode,
            fill_allow_less_vram=fill_allow_less_vram,
            gpu_profile=gpu_profile,
            audit=audit,
            run_id=run_id,
            skip_existing=skip_existing,
            output_roots=output_roots,
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
        bake_geometry_nodes: bool = False,
        min_cpu_ram_gb: float = 0.0,
        fill_similar_gpus: bool = False,
        similar_gpu_mode: str = "floor",
        fill_allow_less_vram: bool = False,
        gpu_profile: str = "",
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
            bake_geometry_nodes=bake_geometry_nodes,
            min_cpu_ram_gb=min_cpu_ram_gb,
            fill_similar_gpus=fill_similar_gpus,
            similar_gpu_mode=similar_gpu_mode,
            fill_allow_less_vram=fill_allow_less_vram,
            gpu_profile=gpu_profile,
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
