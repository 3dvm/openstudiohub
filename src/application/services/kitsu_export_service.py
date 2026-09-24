# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/kitsu_export_service.py
# Architectural role: Application service / Kitsu project export (.oshproject)
# =========================================================================================

"""Export a Kitsu project (metadata + media + optional non-VCS files/dump) to a
``.oshproject`` archive.

The service runs while the user is logged into the SOURCE Kitsu server. It never
touches Qt: all feedback is pushed as structured events to a thread-safe
``queue.Queue`` (drained by the UI) plus optional plain callbacks. Credentials
never reach the archive.
"""

from __future__ import annotations

import json
import queue
import shlex
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.application.services.oshproject_format import (
    FILES_DIR,
    KITSU_DIR,
    MEDIA_ATTACHMENTS_DIR,
    MEDIA_PREVIEWS_DIR,
    OshProjectWriter,
    SVN_DUMP_NAME,
    build_manifest,
    default_archive_name,
    directory_size,
    human_bytes,
    unique_path,
)
from src.infrastructure.nas_manager import NasManager
from src.infrastructure.vcs.repository_admin import normalize_repo_name

DEFAULT_MEDIA_CAP_MB = 200
MOVIE_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v"}

# Archive file names (kept local so the service owns its layout).
PROJECT_JSON = f"{KITSU_DIR}/project.json"
PERSONS_JSON = f"{KITSU_DIR}/persons.json"
TASK_TYPES_JSON = f"{KITSU_DIR}/studio/task_types.json"
TASK_STATUSES_JSON = f"{KITSU_DIR}/studio/task_statuses.json"
ASSET_TYPES_JSON = f"{KITSU_DIR}/studio/asset_types.json"
DEPARTMENTS_JSON = f"{KITSU_DIR}/studio/departments.json"
PROJECT_STATUSES_JSON = f"{KITSU_DIR}/studio/project_statuses.json"
EPISODES_JSON = f"{KITSU_DIR}/entities/episodes.json"
SEQUENCES_JSON = f"{KITSU_DIR}/entities/sequences.json"
SHOTS_JSON = f"{KITSU_DIR}/entities/shots.json"
ASSETS_JSON = f"{KITSU_DIR}/entities/assets.json"
EDITS_JSON = f"{KITSU_DIR}/entities/edits.json"
CASTING_JSON = f"{KITSU_DIR}/casting.json"
TASKS_JSON = f"{KITSU_DIR}/tasks.json"
WORKING_FILES_JSON = f"{KITSU_DIR}/working_files.json"
COMMENTS_JSON = f"{KITSU_DIR}/comments.json"
TIME_SPENT_JSON = f"{KITSU_DIR}/time_spent.json"

StatusCallback = Callable[[str, str], None]
ProgressCallback = Callable[[int], None]


@dataclass
class ExportOptions:
    include_media: bool = True
    include_shared: bool = False
    embed_svn_dump: bool = False
    media_cap_mb: int = DEFAULT_MEDIA_CAP_MB

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "ExportOptions":
        data = data or {}
        return cls(
            include_media=bool(data.get("include_media", True)),
            include_shared=bool(data.get("include_shared", False)),
            embed_svn_dump=bool(data.get("embed_svn_dump", False)),
            media_cap_mb=int(data.get("media_cap_mb", DEFAULT_MEDIA_CAP_MB) or DEFAULT_MEDIA_CAP_MB),
        )


@dataclass
class ExportOutcome:
    success: bool
    message: str
    archive_path: Optional[Path] = None
    manifest: dict = field(default_factory=dict)
    skipped_media: List[str] = field(default_factory=list)


class KitsuExportService:
    def __init__(
        self,
        kitsu,
        config_factory=None,
        credential_vault=None,
        app_version: str = "",
        status_callback: Optional[StatusCallback] = None,
        progress_callback: Optional[ProgressCallback] = None,
        event_sink: Optional["queue.Queue"] = None,
    ) -> None:
        self.kitsu = kitsu
        self.config_factory = config_factory
        self.credential_vault = credential_vault
        self.app_version = app_version
        self._status = status_callback or (lambda _message, _color: None)
        self._progress_cb = progress_callback or (lambda _percent: None)
        self._event_sink = event_sink
        self._cancel = threading.Event()
        self._procs: list = []

    # ------------------------------------------------------------------
    # Event / log plumbing (never touches Qt)
    # ------------------------------------------------------------------
    def _emit(self, kind: str, payload=None) -> None:
        if self._event_sink is not None:
            try:
                self._event_sink.put((kind, payload))
            except Exception:  # noqa: BLE001
                pass

    def _log(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{stamp}] {line}"
        print(f"[KitsuExport] {line}")
        self._emit("log", entry)

    def _phase(self, message: str, color: str = "yellow") -> None:
        self._emit("phase", message)
        self._status(message, color)

    def _progress(self, percent: int) -> None:
        self._progress_cb(max(0, min(100, int(percent))))
        self._emit("percent", max(0, min(100, int(percent))))

    def cancel(self) -> None:
        self._cancel.set()
        for proc in list(self._procs):
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Safe fetch helpers
    # ------------------------------------------------------------------
    def _safe(self, func, default):
        try:
            result = func()
            return result if result is not None else default
        except Exception as error:  # noqa: BLE001
            self._log(f"Warning: a Kitsu query failed ({error}); continuing.")
            return default

    # ------------------------------------------------------------------
    # Data gathering
    # ------------------------------------------------------------------
    def gather(self, project_id: str) -> Dict[str, object]:
        """Fetch the full production payload for a project (metadata only)."""
        kitsu = self.kitsu
        project = self._safe(lambda: kitsu.get_project(project_id), {}) or {}
        tasks = self._safe(lambda: kitsu.all_tasks_for_project(project_id), [])
        comments = self._safe(lambda: kitsu.all_comments_for_project(project_id), [])
        preview_files = self._safe(lambda: kitsu.all_preview_files_for_project(project_id), [])
        attachments = self._safe(lambda: kitsu.get_all_attachment_files_for_project(project_id), [])

        working_files_by_task: Dict[str, list] = {}
        time_by_task: Dict[str, list] = {}
        for task in tasks:
            task_id = str(task.get("id", ""))
            working_files_by_task[task_id] = self._safe(
                lambda t=task: kitsu.get_working_files_for_task(t), []
            )
            raw_time = self._safe(lambda t=task: kitsu.get_time_spent(t), {})
            time_by_task[task_id] = _normalize_time_entries(raw_time)

        return {
            "project": project,
            "episodes": self._safe(lambda: kitsu.all_episodes_for_project(project_id), []),
            "sequences": self._safe(lambda: kitsu.all_sequences_for_project(project_id), []),
            "shots": self._safe(lambda: kitsu.all_shots_for_project(project_id), []),
            "assets": self._safe(lambda: kitsu.all_assets_for_project(project_id), []),
            "edits": self._safe(lambda: kitsu.all_edits_for_project(project_id), []),
            "casting": {
                "shots_casting": self._safe(lambda: kitsu.get_project_shots_casting(project_id), {}),
                "entity_links": self._safe(lambda: kitsu.all_entity_links_for_project(project_id), []),
            },
            "tasks": tasks,
            "task_types": self._safe(lambda: kitsu.all_task_types(), []),
            "task_statuses": self._safe(lambda: kitsu.all_task_statuses_for_project(project_id), []),
            "asset_types": self._safe(lambda: kitsu.all_asset_types(), []),
            "departments": self._safe(lambda: kitsu.all_departments(), []),
            "project_statuses": self._safe(lambda: kitsu.all_project_status(), []),
            "all_persons": self._safe(lambda: kitsu.all_persons(), []),
            "comments": comments,
            "preview_files": preview_files,
            "attachments": attachments,
            "working_files_by_task": working_files_by_task,
            "time_by_task": time_by_task,
        }

    def collect_persons(self, data: dict) -> List[dict]:
        """Referenced people (email/full_name/role only, never avatars).

        Kitsu payloads reference people by ID (tasks: ``assigner_id`` /
        ``assignees``; comments: ``person_id``; working files: ``person_id``),
        but some endpoints expand the person dict. Both shapes are handled and
        resolved against the server's person directory (``all_persons``).
        """
        directory: Dict[str, dict] = {}
        for person in data.get("all_persons") or []:
            if not isinstance(person, dict):
                continue
            person_id = str(person.get("id", "") or "")
            if person_id:
                directory.setdefault(person_id, _person_record(person))

        referenced: List[str] = []

        def reference(value) -> None:
            for person_id in _person_ids(value):
                if person_id not in referenced:
                    referenced.append(person_id)

        for value in (data.get("project") or {}).get("team") or []:
            reference(value)
        for task in data.get("tasks") or []:
            reference(task.get("assigner_id"))
            reference(task.get("assigner"))
            reference(task.get("assignees"))
            reference(task.get("person_id"))
            reference(task.get("person"))
        for comment in data.get("comments") or []:
            reference(comment.get("person_id"))
            reference(comment.get("person"))
        for working_files in (data.get("working_files_by_task") or {}).values():
            for working_file in working_files:
                reference(working_file.get("person_id"))
                reference(working_file.get("person"))
        for entries in (data.get("time_by_task") or {}).values():
            for entry in entries:
                reference(entry.get("person_id"))
                reference(entry.get("person"))

        persons: List[dict] = []
        for person_id in referenced:
            record = directory.get(person_id)
            if record is None:
                # Referenced but absent from the directory: still let the user map it.
                record = {
                    "id": person_id, "email": "", "full_name": "",
                    "first_name": "", "last_name": "", "role": "user",
                }
            persons.append(record)
        return persons

    # ------------------------------------------------------------------
    # Estimation
    # ------------------------------------------------------------------
    def estimate(self, project_id: str, project_name: str, options: Optional[ExportOptions] = None) -> dict:
        """Approximate per-category sizes for the export dialog."""
        options = options or ExportOptions()
        data = self.gather(project_id)
        metadata_bytes = len(json.dumps(_jsonable(data), default=str).encode("utf-8"))

        preview_bytes = sum(_size_of(item) for item in data.get("preview_files") or [])
        attachment_bytes = sum(_size_of(item) for item in data.get("attachments") or [])

        project_root = self._project_root(project_name)
        pipeline_bytes = directory_size(project_root / self._vfs("vfs_pipeline"))
        shared_bytes = directory_size(project_root / self._vfs("vfs_shared")) if options.include_shared else 0

        dump_bytes = 0
        if options.embed_svn_dump:
            dump_bytes = max(directory_size(project_root / self._vfs("vfs_svn")), 0)

        sizes = {
            "kitsu": metadata_bytes,
            "media_previews": preview_bytes if options.include_media else 0,
            "media_attachments": attachment_bytes if options.include_media else 0,
            "files_pipeline": pipeline_bytes,
            "files_shared": shared_bytes,
            "vcs_dump": dump_bytes,
            "approximate": True,
        }
        sizes["total"] = sum(
            value for key, value in sizes.items() if key not in ("approximate", "total")
        )
        self._emit("size_estimate", sizes)
        return sizes

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export(
        self,
        project_id: str,
        project_name: str,
        destination_dir: Path,
        options: Optional[ExportOptions] = None,
        archive_name: Optional[str] = None,
    ) -> ExportOutcome:
        self._cancel.clear()
        options = options or ExportOptions()
        destination_dir = Path(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        archive_path = unique_path(destination_dir / (archive_name or default_archive_name(project_name)))

        skipped_media: List[str] = []
        try:
            self._phase(f"Reading project '{project_name}' from Kitsu...")
            self._progress(2)
            data = self.gather(project_id)
            if not data.get("project"):
                return ExportOutcome(False, "The project could not be read from Kitsu.")

            persons = self.collect_persons(data)
            vcs = self._vcs_reference(project_name)
            blueprint = self._blueprint_snapshot(project_name)
            counts = {
                "episodes": len(data.get("episodes") or []),
                "sequences": len(data.get("sequences") or []),
                "shots": len(data.get("shots") or []),
                "assets": len(data.get("assets") or []),
                "edits": len(data.get("edits") or []),
                "tasks": len(data.get("tasks") or []),
                "comments": len(data.get("comments") or []),
                "previews": len(data.get("preview_files") or []),
                "attachments": len(data.get("attachments") or []),
                "working_files": sum(len(v) for v in (data.get("working_files_by_task") or {}).values()),
                "time_entries": sum(len(v) for v in (data.get("time_by_task") or {}).values()),
                "persons": len(persons),
            }

            inclusion = {
                "media": options.include_media,
                "shared": options.include_shared,
                "embed_svn_dump": options.embed_svn_dump,
                "media_cap_mb": options.media_cap_mb,
            }

            self._emit("stats", {"percent": 8, "phase": "packing metadata"})
            with OshProjectWriter(archive_path) as writer:
                self._write_metadata(writer, data, persons)
                self._progress(25)

                if options.include_media:
                    self._write_media(writer, data, options, skipped_media)
                self._progress(55)

                self._write_files(writer, project_name, options)
                self._progress(72)

                if options.embed_svn_dump and vcs.get("server_id"):
                    self._write_dump(writer, vcs, project_name)
                self._progress(90)

                manifest = build_manifest(
                    project=_project_record(data.get("project") or {}),
                    blueprint=blueprint,
                    inclusion=inclusion,
                    vcs=vcs,
                    counts=counts,
                    source_kitsu_url=self._kitsu_url(),
                    app_version=self.app_version,
                )
                writer.write_manifest(manifest)

            if self._cancel.is_set():
                try:
                    archive_path.unlink()
                except OSError:
                    pass
                return ExportOutcome(False, "Export cancelled by the user.")

            self._progress(100)
            size = archive_path.stat().st_size if archive_path.exists() else 0
            message = f"Exported '{project_name}' to {archive_path.name} ({human_bytes(size)})."
            if skipped_media:
                message += f" {len(skipped_media)} oversized media item(s) were skipped."
            self._phase(message, "green")
            self._log(message)
            return ExportOutcome(True, message, archive_path, manifest, skipped_media)

        except Exception as error:  # noqa: BLE001
            import traceback

            print(f"[KitsuExport] CRASH:\n{traceback.format_exc()}")
            try:
                if archive_path.exists():
                    archive_path.unlink()
            except OSError:
                pass
            return ExportOutcome(False, f"Export failed: {error}")

    # ------------------------------------------------------------------
    # Bundle writers
    # ------------------------------------------------------------------
    def _write_metadata(self, writer: OshProjectWriter, data: dict, persons: List[dict]) -> None:
        writer.add_json(PROJECT_JSON, _project_record(data.get("project") or {}))
        writer.add_json(PERSONS_JSON, persons)
        writer.add_json(TASK_TYPES_JSON, data.get("task_types") or [])
        writer.add_json(TASK_STATUSES_JSON, data.get("task_statuses") or [])
        writer.add_json(ASSET_TYPES_JSON, data.get("asset_types") or [])
        writer.add_json(DEPARTMENTS_JSON, data.get("departments") or [])
        writer.add_json(PROJECT_STATUSES_JSON, data.get("project_statuses") or [])
        writer.add_json(EPISODES_JSON, data.get("episodes") or [])
        writer.add_json(SEQUENCES_JSON, data.get("sequences") or [])
        writer.add_json(SHOTS_JSON, data.get("shots") or [])
        writer.add_json(ASSETS_JSON, data.get("assets") or [])
        writer.add_json(EDITS_JSON, data.get("edits") or [])
        writer.add_json(CASTING_JSON, data.get("casting") or {})
        writer.add_json(TASKS_JSON, data.get("tasks") or [])
        working_files = []
        for task_id, entries in (data.get("working_files_by_task") or {}).items():
            for entry in entries:
                record = dict(entry)
                record.setdefault("task_id", task_id)
                working_files.append(record)
        writer.add_json(WORKING_FILES_JSON, working_files)
        writer.add_json(COMMENTS_JSON, data.get("comments") or [])
        time_entries = []
        for task_id, entries in (data.get("time_by_task") or {}).items():
            for entry in entries:
                record = dict(entry)
                record.setdefault("task_id", task_id)
                time_entries.append(record)
        writer.add_json(TIME_SPENT_JSON, time_entries)

    def _write_media(self, writer: OshProjectWriter, data: dict, options: ExportOptions, skipped: List[str]) -> None:
        cap = max(0, int(options.media_cap_mb)) * 1024 * 1024
        self._phase("Downloading previews and attachments...")
        tmpdir = Path(tempfile.mkdtemp(prefix="oshproject_media_"))

        try:
            for preview in data.get("preview_files") or []:
                if self._cancel.is_set():
                    return
                self._download_preview(writer, preview, cap, skipped, tmpdir)
            for attachment in data.get("attachments") or []:
                if self._cancel.is_set():
                    return
                self._download_attachment(writer, attachment, cap, skipped, tmpdir)
        finally:
            _rmtree(tmpdir)

    def _download_preview(self, writer, preview, cap, skipped, tmpdir) -> None:
        preview_id = str(preview.get("id", "") or "")
        if not preview_id:
            return
        task_id = str(preview.get("task_id", "") or "unassigned")
        original = preview.get("original_name") or preview.get("file") or f"preview_{preview_id}"
        extension = str(preview.get("extension", "") or Path(str(original)).suffix).lstrip(".").lower()
        size = _size_of(preview)
        # Kitsu often stores the extension separately from the name; without it the
        # uploaded file is rejected on import ("Wrong file format").
        stored_name = _with_extension(Path(str(original)).name, extension)
        arcname = f"{MEDIA_PREVIEWS_DIR}/{task_id}/{preview_id}_{stored_name}"

        try:
            if f".{extension}" in MOVIE_EXTENSIONS:
                use_lowdef = bool(cap) and size > cap
                if use_lowdef:
                    self._log(f"Preview '{original}' exceeds the media cap; using low-def movie.")
                temp = _temp_path(tmpdir, f"{preview_id}.{extension or 'mp4'}")
                try:
                    download = self.kitsu.download_preview_lowdef_movie if use_lowdef else self.kitsu.download_preview_movie
                    download(preview, str(temp))
                except Exception:  # noqa: BLE001 - low-def may not exist
                    if use_lowdef:
                        self.kitsu.download_preview_movie(preview, str(temp))
                    else:
                        raise
                if cap and temp.stat().st_size > cap:
                    skipped.append(arcname)
                    self._log(f"Skipping '{original}': still larger than the {cap // (1024 * 1024)} MB cap.")
                    return
                writer.add_file(arcname, temp)
            else:
                temp = _temp_path(tmpdir, f"{preview_id}.{extension or 'png'}")
                self.kitsu.download_preview_file(preview, str(temp))
                writer.add_file(arcname, temp)
        except Exception as error:  # noqa: BLE001
            self._log(f"Warning: failed to download preview '{original}': {error}")
            skipped.append(arcname)

        # Best-effort thumbnail alongside the preview.
        try:
            thumb = _temp_path(tmpdir, f"{preview_id}_thumb.{extension or 'png'}")
            self.kitsu.download_preview_file_thumbnail(preview, str(thumb))
            if thumb.exists() and thumb.stat().st_size > 0:
                writer.add_file(f"{MEDIA_PREVIEWS_DIR}/{task_id}/{preview_id}_thumb.{extension or 'png'}", thumb)
        except Exception:  # noqa: BLE001
            pass

    def _download_attachment(self, writer, attachment, cap, skipped, tmpdir) -> None:
        attachment_id = str(attachment.get("id", "") or "")
        if not attachment_id:
            return
        original = attachment.get("original_name") or attachment.get("name") or attachment.get("file") or f"attachment_{attachment_id}"
        extension = str(attachment.get("extension", "") or "").lstrip(".").lower()
        stored_name = _with_extension(Path(str(original)).name, extension)
        size = _size_of(attachment)
        if cap and size > cap:
            skipped.append(original)
            self._log(f"Skipping attachment '{original}': larger than the media cap.")
            return
        arcname = f"{MEDIA_ATTACHMENTS_DIR}/{attachment_id}_{stored_name}"
        try:
            temp = _temp_path(tmpdir, f"{attachment_id}_{stored_name}")
            self.kitsu.download_attachment_file(attachment, str(temp))
            writer.add_file(arcname, temp)
        except Exception as error:  # noqa: BLE001
            self._log(f"Warning: failed to download attachment '{original}': {error}")
            skipped.append(arcname)

    def _write_files(self, writer: OshProjectWriter, project_name: str, options: ExportOptions) -> None:
        project_root = self._project_root(project_name)
        pipeline = project_root / self._vfs("vfs_pipeline")
        shared = project_root / self._vfs("vfs_shared")

        self._phase("Packing non-VCS project files...")
        if pipeline.is_dir():
            writer.add_directory(f"{FILES_DIR}/pipeline", pipeline)
            self._log(f"Packed pipeline/ ({human_bytes(directory_size(pipeline))}).")
        if options.include_shared and shared.is_dir():
            writer.add_directory(f"{FILES_DIR}/shared", shared)
            self._log(f"Packed shared/ ({human_bytes(directory_size(shared))}).")
        for custom_dir in self._source_custom_dirs(project_name):
            source = project_root / custom_dir
            if source.is_dir():
                writer.add_directory(f"{FILES_DIR}/custom/{custom_dir}", source)
                self._log(f"Packed {custom_dir}/ ({human_bytes(directory_size(source))}).")

    def _write_dump(self, writer: OshProjectWriter, vcs: dict, project_name: str) -> None:
        self._phase("Dumping the SVN repository (this can take a while)...")
        repo_name = normalize_repo_name(project_name)
        tmpdir = Path(tempfile.mkdtemp(prefix="oshproject_dump_"))
        raw = tmpdir / "svn.dump"
        gz = tmpdir / "svn.dump.gz"
        try:
            ok, message = self._stream_svn_dump(vcs.get("server_id", ""), repo_name, raw)
            if not ok:
                self._log(f"Warning: could not dump the SVN repository ({message}); continuing without it.")
                return
            from src.application.services.oshproject_format import gzip_path

            def _progress(written: int) -> None:
                self._emit("bytes", {"phase": "svn dump", "bytes": written})

            gzip_path(raw, gz, progress=_progress)
            writer.add_file(SVN_DUMP_NAME, gz)
            self._log(f"Embedded SVN dump: {human_bytes(gz.stat().st_size)}.")
        finally:
            _rmtree(tmpdir)

    def _stream_svn_dump(self, server_id: str, repo_name: str, dest: Path) -> Tuple[bool, str]:
        """Stream ``svnadmin dump`` of the bound server into ``dest``."""
        server = self._server(server_id)
        if server is None:
            return False, "the project is not bound to a VCS server"
        repo_path = self._repo_path(server, repo_name)
        inner = f"svnadmin dump --quiet {shlex.quote(repo_path)}"

        try:
            if self._is_local(server):
                proc = subprocess.Popen(
                    ["docker", "exec", server.profile.local_container, "sh", "-c", inner],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
            else:
                from src.infrastructure.vcs.ssh_runner import SshRunner

                runner = SshRunner(server.profile.remote, passphrase_provider=self._passphrase_provider(server))
                proc, _cleanup = runner.popen(self._remote_inner(server, inner), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._procs.append(proc)
        except Exception as error:  # noqa: BLE001
            return False, str(error)

        with open(dest, "wb") as handle:
            while True:
                if self._cancel.is_set():
                    proc.kill()
                    return False, "cancelled"
                chunk = proc.stdout.read(1 << 16)
                if not chunk:
                    break
                handle.write(chunk)
        proc.wait()
        self._procs = [p for p in self._procs if p is not proc]
        if proc.returncode != 0:
            stderr = (proc.stderr.read() or b"").decode("utf-8", "replace")
            return False, stderr.strip() or f"svnadmin exited with {proc.returncode}"
        return True, "ok"

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------
    def _server(self, server_id: str):
        if self.config_factory is None:
            return None
        getter = getattr(self.config_factory, "get_server", None)
        server = getter(server_id) if callable(getter) and server_id else None
        if server is None:
            default = getattr(self.config_factory, "get_default_server", None)
            server = default() if callable(default) else None
        return server

    @staticmethod
    def _is_local(server) -> bool:
        from src.domain.workspace.vcs_server_profile import LOCAL_DOCKER

        return server.profile.mode == LOCAL_DOCKER

    @staticmethod
    def _remote_inner(server, inner: str) -> str:
        container = shlex.quote(server.profile.remote.container)
        return f"docker exec {container} sh -c {shlex.quote(inner)}"

    def _repo_path(self, server, repo_name: str) -> str:
        from src.domain.workspace.vcs_server_profile import LOCAL_DOCKER

        if server.profile.mode == LOCAL_DOCKER:
            root = server.profile.local_repo_root.rstrip("/")
        else:
            root = server.profile.remote.repo_root.rstrip("/")
        return f"{root}/{repo_name}"

    def _passphrase_provider(self, server):
        if self.credential_vault is None:
            return None
        server_id = server.id if server is not None else ""
        return lambda: self.credential_vault.get_ssh_passphrase(server_id)

    def _project_root(self, project_name: str) -> Path:
        if self.config_factory is None:
            return Path(project_name)
        try:
            nas = NasManager(config_factory=self.config_factory)
            resolved = nas.resolve_project_dir(project_name)
            if resolved is not None:
                return resolved
            return self.config_factory.get_workspace_root() / project_name.strip().lower().replace(" ", "-")
        except Exception:  # noqa: BLE001
            return Path(project_name)

    def _vfs(self, attr: str) -> str:
        if self.config_factory is None:
            return {"vfs_pipeline": "pipeline", "vfs_shared": "shared", "vfs_svn": "svn"}.get(attr, attr)
        topography = self.config_factory.get_topography()
        return getattr(topography, attr)

    def _source_custom_dirs(self, project_name: str) -> List[str]:
        snapshot = self._blueprint_snapshot(project_name)
        signature = (snapshot or {}).get("topography_signature") or {}
        custom = list(signature.get("custom_dirs") or [])
        if custom:
            return [str(item) for item in custom if str(item).strip()]
        if self.config_factory is not None:
            try:
                return list(self.config_factory.get_topography().custom_dirs)
            except Exception:  # noqa: BLE001
                return []
        return []

    def _blueprint_snapshot(self, project_name: str) -> dict:
        project_root = self._project_root(project_name)
        pipeline_name = self._vfs("vfs_pipeline")
        for candidate in (
            project_root / pipeline_name / "project_init.json",
        ):
            if candidate.exists():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    break
        # Fallback skeleton derived from the local topography.
        topography = self.config_factory.get_topography() if self.config_factory else None
        return {
            "project_name": project_name,
            "template": "",
            "topography_signature": {
                "vfs_svn": getattr(topography, "vfs_svn", "svn"),
                "vfs_shared": getattr(topography, "vfs_shared", "shared"),
                "vfs_local": getattr(topography, "vfs_local", "local"),
                "vfs_pipeline": getattr(topography, "vfs_pipeline", "pipeline"),
            },
        }

    def _vcs_reference(self, project_name: str) -> dict:
        project_root = self._project_root(project_name)
        server = None
        if self.config_factory is not None:
            getter = getattr(self.config_factory, "get_server_for_project", None)
            if callable(getter):
                try:
                    server = getter(project_root)
                except Exception:  # noqa: BLE001
                    server = None
        if server is None:
            server = self._server("")
        if server is None:
            return {}
        return {
            "server_id": server.id,
            "server_name": server.name,
            "adapter": server.adapter,
            "server_url": server.repository_url,
        }

    def _kitsu_url(self) -> str:
        if self.config_factory is None:
            return ""
        try:
            return self.config_factory.get_kitsu_api_url()
        except Exception:  # noqa: BLE001
            return ""


# ---------------------------------------------------------------------------
# Free helpers
# ---------------------------------------------------------------------------
def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _person_ids(value) -> List[str]:
    """Yield person ids from either an id, a person dict, or a list thereof."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        person_id = value.get("id") or value.get("person_id")
        return [str(person_id)] if person_id else []
    if isinstance(value, (list, tuple, set)):
        ids: List[str] = []
        for item in value:
            ids.extend(_person_ids(item))
        return ids
    return []


def _person_record(person: dict) -> dict:
    return {
        "id": str(person.get("id", "") or ""),
        "email": str(person.get("email", "") or ""),
        "full_name": str(person.get("full_name", "") or ""),
        "first_name": str(person.get("first_name", "") or ""),
        "last_name": str(person.get("last_name", "") or ""),
        "role": str(person.get("role", "user") or "user"),
    }


def _project_record(project: dict) -> dict:
    return {
        "id": str(project.get("id", "") or ""),
        "name": str(project.get("name", "") or ""),
        "description": str(project.get("description", "") or ""),
        "production_type": str(project.get("production_type", "short") or "short"),
        "production_style": str(project.get("production_style", "") or ""),
        "data": project.get("data") or {},
        "project_status_id": str(project.get("project_status_id", "") or ""),
        "project_status_name": str(project.get("project_status_name", "") or ""),
        "fps": project.get("fps"),
        "team": [
            _person_record(person)
            for person in (project.get("team") or [])
            if isinstance(person, dict)
        ],
    }


def _with_extension(name: str, extension: str) -> str:
    """Append ``extension`` to ``name`` when it is missing (Kitsu stores it apart)."""
    name = name or "file"
    extension = (extension or "").lstrip(".").lower()
    if not extension:
        return name
    if name.lower().endswith(f".{extension}"):
        return name
    return f"{name}.{extension}"


def _size_of(item: dict) -> int:
    for key in ("file_size", "size", "bytes"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _normalize_time_entries(raw) -> List[dict]:
    """Flatten gazu's time-spent payload into ``{person_id, date, duration}`` rows."""
    entries: List[dict] = []
    if not isinstance(raw, dict):
        return entries
    for key, value in raw.items():
        if isinstance(value, dict) and isinstance(value.get("duration"), (int, float)):
            entries.append({
                "person_id": str(value.get("person_id", key) or key),
                "date": str(value.get("date", "") or ""),
                "duration": int(value.get("duration") or 0),
            })
        elif isinstance(value, dict):
            # Nested shape: {date: {person_id: {"duration": ...}}}
            for person_key, entry in value.items():
                if isinstance(entry, dict) and isinstance(entry.get("duration"), (int, float)):
                    entries.append({
                        "person_id": str(entry.get("person_id", person_key) or person_key),
                        "date": str(entry.get("date", key) or key),
                        "duration": int(entry.get("duration") or 0),
                    })
    return entries


def _temp_path(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / name


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
