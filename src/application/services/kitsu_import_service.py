# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/kitsu_import_service.py
# Architectural role: Application service / Kitsu project import (.oshproject)
# =========================================================================================

"""Import a ``.oshproject`` archive into the TARGET Kitsu server and recreate the
Hub project on the machine.

Runs while the user is logged into the TARGET server with a super-admin account
(gazu's client is a process-global singleton). IDs differ between servers, so the
service builds old->new maps for people, studio resources, entities and tasks.
Non-VCS files are recreated on the NAS, then the VCS repository is either loaded
from the embedded dump or left to be checked out on demand.
"""

from __future__ import annotations

import gzip
import json
import queue
import shlex
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.application.services.addon_config_generator import AddonConfigGenerator
from src.application.services.oshproject_format import (
    FILES_DIR,
    MEDIA_ATTACHMENTS_DIR,
    MEDIA_PREVIEWS_DIR,
    SVN_DUMP_NAME,
    ManifestError,
    OshProjectReader,
)
from src.application.services.workspace_operations import (
    BlueprintGenerator,
    WorkspaceScaffolder,
)
from src.domain.workspace.blueprint import ProjectBlueprint
from src.domain.workspace.vcs_server import (
    infer_mode_from_url,
    reconcile_server_mode,
    url_host,
)
from src.domain.workspace.vcs_server_profile import LOCAL_DOCKER
from src.infrastructure.vcs.repository_admin import build_repository_admin, normalize_repo_name

StatusCallback = Callable[[str, str], None]
ProgressCallback = Callable[[int], None]


@dataclass
class ImportOptions:
    target_vcs_server_id: str = ""
    dry_run: bool = False
    topography: dict = field(default_factory=dict)
    rename_repository: bool = False

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "ImportOptions":
        data = data or {}
        return cls(
            target_vcs_server_id=str(data.get("target_vcs_server_id", "") or ""),
            dry_run=bool(data.get("dry_run", False)),
            topography=dict(data.get("topography") or {}),
            rename_repository=bool(data.get("rename_repository", False)),
        )


@dataclass
class ImportPlan:
    archive_path: Path
    manifest: dict
    project: dict
    persons: List[dict]
    persons_json: List[dict]
    counts: dict
    vcs: dict
    inclusion: dict
    source_kitsu_url: str = ""

    @property
    def project_name(self) -> str:
        return str(self.project.get("name", "") or "")

    @property
    def source_topography(self) -> dict:
        blueprint = self.manifest.get("blueprint") or {}
        return dict(blueprint.get("topography_signature") or {})


@dataclass
class PersonMappingRow:
    source: dict
    target: Optional[dict] = None

    @property
    def matched(self) -> bool:
        return self.target is not None

    @property
    def email(self) -> str:
        return str(self.source.get("email", "") or "").strip().lower()


@dataclass
class ImportReport:
    success: bool
    message: str
    dry_run: bool = False
    project_id: str = ""
    project_name: str = ""
    created_persons: List[str] = field(default_factory=list)
    phases: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    needs_checkout: bool = False
    rollback_available: bool = False
    archive_path: Optional[Path] = None
    project_root: Optional[Path] = None


class _ImportContext:
    def __init__(self, target_project: dict) -> None:
        self.project = target_project
        self.project_id = str(target_project.get("id", "") or "")
        self.person_map: Dict[str, dict] = {}
        self.status_map: Dict[str, dict] = {}
        self.task_type_map: Dict[str, dict] = {}
        self.asset_type_map: Dict[str, dict] = {}
        self.department_map: Dict[str, dict] = {}
        self.episode_map: Dict[str, dict] = {}
        self.sequence_map: Dict[str, dict] = {}
        self.shot_map: Dict[str, dict] = {}
        self.asset_map: Dict[str, dict] = {}
        self.edit_map: Dict[str, dict] = {}
        self.task_map: Dict[str, dict] = {}
        self.comment_map: Dict[str, dict] = {}
        # Per-step success counters (created vs reused) for user-facing progress.
        self.counters: Dict[str, int] = {}

    def bump(self, key: str, amount: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + amount

    def counter(self, key: str) -> int:
        return self.counters.get(key, 0)


class KitsuImportService:
    def __init__(
        self,
        kitsu,
        config_factory=None,
        credential_vault=None,
        nas_manager=None,
        installation_service=None,
        app_version: str = "",
        status_callback: Optional[StatusCallback] = None,
        progress_callback: Optional[ProgressCallback] = None,
        event_sink: Optional["queue.Queue"] = None,
    ) -> None:
        self.kitsu = kitsu
        self.config_factory = config_factory
        self.credential_vault = credential_vault
        self.nas_manager = nas_manager
        self.installation_service = installation_service
        self.app_version = app_version
        self._status = status_callback or (lambda _message, _color: None)
        self._progress_cb = progress_callback or (lambda _percent: None)
        self._event_sink = event_sink
        self._cancel = threading.Event()
        self._log_lines: List[str] = []
        # Last server-side command (diagnostics for the repository probe).
        self._last_server_command_detail: Optional[dict] = None
        # Last repository existence/listing probe (diagnostics + state).
        self._last_repo_probe: Optional[dict] = None

    # ------------------------------------------------------------------
    # Event / log plumbing
    # ------------------------------------------------------------------
    def _emit(self, kind: str, payload=None) -> None:
        if self._event_sink is not None:
            try:
                self._event_sink.put((kind, payload))
            except Exception:  # noqa: BLE001
                pass

    def _log(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log_lines.append(line)
        self._emit("log", f"[{stamp}] {line}")
        print(f"[KitsuImport] {line}")

    def _phase(self, message: str, color: str = "yellow") -> None:
        self._emit("phase", message)
        self._status(message, color)

    def _progress(self, percent: int) -> None:
        percent = max(0, min(100, int(percent)))
        self._progress_cb(percent)
        self._emit("percent", percent)

    def cancel(self) -> None:
        self._cancel.set()

    def _safe(self, func, default):
        try:
            result = func()
            return result if result is not None else default
        except Exception as error:  # noqa: BLE001
            self._log(f"Warning: a Kitsu operation failed ({error}); continuing.")
            return default

    # ------------------------------------------------------------------
    # Inspection / planning
    # ------------------------------------------------------------------
    def inspect(self, archive_path: Path) -> ImportPlan:
        archive_path = Path(archive_path)
        with OshProjectReader(archive_path) as reader:
            manifest = reader.read_manifest()
            project = reader.read_json("kitsu/project.json") or {}
            persons_json = reader.read_json("kitsu/persons.json") or []
        return ImportPlan(
            archive_path=archive_path,
            manifest=manifest,
            project=project,
            persons=persons_json,
            persons_json=persons_json,
            counts=manifest.get("counts") or {},
            vcs=manifest.get("vcs") or {},
            inclusion=manifest.get("inclusion") or {},
            source_kitsu_url=manifest.get("source_kitsu_url", ""),
        )

    def verify(self, archive_path: Path) -> Tuple[bool, List[str]]:
        with OshProjectReader(archive_path) as reader:
            return reader.verify_checksums()

    def check_conflict(self, plan: ImportPlan) -> Optional[str]:
        name = plan.project_name
        if not name:
            return "The archive does not declare a project name."
        exists = self._safe(lambda: self.kitsu.get_project_by_name(name), None)
        if exists:
            return (
                f"A project named '{name}' already exists on this Kitsu server. "
                "Import aborted to avoid overwriting production data."
            )
        return None

    def preview_person_mapping(self, plan: ImportPlan) -> List[PersonMappingRow]:
        target_persons = self._safe(lambda: self.kitsu.all_persons(), [])
        by_email = {
            str(person.get("email", "") or "").strip().lower(): person
            for person in target_persons
            if isinstance(person, dict) and person.get("email")
        }
        rows: List[PersonMappingRow] = []
        for person in plan.persons_json:
            email = str(person.get("email", "") or "").strip().lower()
            rows.append(PersonMappingRow(source=person, target=by_email.get(email)))
        return rows

    def probe_repository(self, plan: ImportPlan, target_server_id: str = "") -> dict:
        """Inspect the target repository's top-level folder against the target vfs_svn.

        Returns a status dict with ``state`` in ``ok`` / ``rename_needed`` /
        ``missing`` / ``unknown`` plus the resolved ``source``/``target`` names.
        ``diagnostics`` carries the actual values used for the probe (transport,
        mode, repository URL, resolved path, command and its output) so a mismatch
        between the declared server mode and the repository URL is visible.
        """
        target_vfs_svn = self._vfs_svn()
        source_vfs_svn = str(plan.source_topography.get("vfs_svn") or "")
        repo_name = normalize_repo_name(plan.project_name)
        result = {
            "state": "unknown",
            "repo_name": repo_name,
            "source": source_vfs_svn,
            "target": target_vfs_svn,
            "server_name": "",
            "dirs": [],
            "diagnostics": {},
        }

        server = self._target_server(target_server_id)
        diagnostics = self._base_probe_diagnostics(
            server, repo_name, source_vfs_svn, target_vfs_svn
        )
        result["diagnostics"] = diagnostics

        if server is None or not target_vfs_svn:
            diagnostics["reason"] = (
                "No target VCS server is selected." if server is None
                else "The target topography has no vfs_svn folder."
            )
            return self._finish_probe(result, "probe skipped")

        declared_mode = diagnostics["declared_mode"]
        inferred_mode = diagnostics["url_mode"]
        if inferred_mode and inferred_mode != declared_mode:
            diagnostics["mismatch"] = (
                f"Server '{server.name}' declares mode '{declared_mode}' but the "
                f"repository URL '{server.repository_url}' implies '{inferred_mode}'."
            )

        # The URL is the source of truth for the transport (checkout already uses
        # it); align server-side operations with it.
        server = reconcile_server_mode(server)
        result["server_name"] = server.name
        diagnostics["effective_mode"] = server.profile.mode
        diagnostics["remote"] = server.profile.remote.to_dict()
        diagnostics["local_container"] = server.profile.local_container
        diagnostics["local_repo_root"] = server.profile.local_repo_root

        if server.profile.is_remote and not server.profile.remote.is_configured:
            result["state"] = "unknown"
            diagnostics["reason"] = (
                f"Repository URL '{server.repository_url}' is remote but the server's "
                "SSH/Docker coordinates are incomplete. Set the host, SSH user and "
                "container in the Infrastructure panel."
            )
            return self._finish_probe(result, "server not configured")

        repo_path = self._repo_path(server, repo_name)
        diagnostics["repo_root"] = (
            server.profile.local_repo_root
            if server.profile.mode == LOCAL_DOCKER
            else server.profile.remote.repo_root
        )
        diagnostics["repo_path"] = repo_path
        diagnostics["file_url"] = f"file://{repo_path}"

        self._last_repo_probe = None
        dirs = self._repo_top_level_dirs(server, repo_path)
        probe = self._last_repo_probe or {}
        diagnostics.update(probe)
        result["dirs"] = list(dirs)

        exists = probe.get("exists")
        if exists is None and probe:
            result["state"] = "unknown"
            diagnostics["reason"] = "The repository host could not be reached."
            return self._finish_probe(result, "host unreachable")
        if exists is False:
            if bool(plan.inclusion.get("embed_svn_dump")):
                # The repo does not exist yet: the import creates it from the dump,
                # so only a source->target rename may still be required.
                result["state"] = (
                    "rename_needed"
                    if source_vfs_svn and source_vfs_svn != target_vfs_svn
                    else "ok"
                )
            else:
                result["state"] = "missing"
            return self._finish_probe(result, "repository directory absent")
        if exists is True and probe.get("returncode") not in (None, 0):
            result["state"] = "unknown"
            diagnostics["reason"] = "The repository exists but its contents could not be listed."
            return self._finish_probe(result, "svn ls failed")

        if not dirs:
            if bool(plan.inclusion.get("embed_svn_dump")):
                result["state"] = (
                    "rename_needed"
                    if source_vfs_svn and source_vfs_svn != target_vfs_svn
                    else "ok"
                )
            elif exists is True:
                result["state"] = "unknown"
                diagnostics["reason"] = (
                    "The repository exists but has no top-level folder; there is "
                    "nothing to check out."
                )
            else:
                # No probe detail available (e.g. a stubbed probe): keep the
                # historical 'missing' state so callers can block the import.
                result["state"] = "missing"
            return self._finish_probe(result, "no top-level folders")

        if target_vfs_svn in dirs:
            entries, listing_ok = self._list_dir_url(
                server, f"file://{repo_path}/{target_vfs_svn}"
            )
            if not listing_ok or entries:
                result["state"] = "ok"
                result["source"] = target_vfs_svn
                return self._finish_probe(result, "target folder present")
            # The target folder exists but is empty (e.g. a previous partial
            # import). If the content lives under another folder, offer to rename
            # it over the empty target so checkout is not silently empty.
            candidate = (
                source_vfs_svn
                if source_vfs_svn in dirs and source_vfs_svn != target_vfs_svn
                else ""
            )
            if not candidate:
                others = [name for name in dirs if name != target_vfs_svn]
                if len(others) == 1:
                    candidate = others[0]
            if candidate:
                result["source"] = candidate
                result["state"] = "rename_needed"
                diagnostics["reason"] = (
                    f"Target folder '{target_vfs_svn}' is empty; '{candidate}' holds the content."
                )
                return self._finish_probe(result, "empty target folder")
            result["state"] = "unknown"
            diagnostics["reason"] = f"Target folder '{target_vfs_svn}' is empty."
            return self._finish_probe(result, "empty target folder")

        candidate = source_vfs_svn if source_vfs_svn in dirs else ""
        if not candidate and len(dirs) == 1:
            # The repo root normally holds exactly one folder (the old vfs root).
            candidate = dirs[0]
        if candidate:
            result["source"] = candidate
            result["state"] = "rename_needed"
            return self._finish_probe(result, "rename needed")
        diagnostics["reason"] = (
            f"Repository has no '{target_vfs_svn}' folder and no single candidate to "
            f"rename (found: {', '.join(dirs) or 'none'})."
        )
        return self._finish_probe(result, "no candidate folder")

    def _base_probe_diagnostics(
        self, server, repo_name: str, source_vfs_svn: str, target_vfs_svn: str
    ) -> dict:
        """Server/URL values used by a probe, before any command is executed."""
        if server is None:
            return {
                "server_id": "",
                "server_name": "",
                "declared_mode": "",
                "url_mode": infer_mode_from_url(""),
                "effective_mode": "",
                "repository_url": "",
                "repo_name": repo_name,
                "source_vfs_svn": source_vfs_svn,
                "target_vfs_svn": target_vfs_svn,
            }
        return {
            "server_id": server.id,
            "server_name": server.name,
            "declared_mode": server.profile.mode,
            "url_mode": infer_mode_from_url(server.repository_url),
            "effective_mode": server.profile.mode,
            "repository_url": server.repository_url,
            "host": url_host(server.repository_url),
            "local_container": server.profile.local_container,
            "local_repo_root": server.profile.local_repo_root,
            "remote": server.profile.remote.to_dict(),
            "repo_name": repo_name,
            "source_vfs_svn": source_vfs_svn,
            "target_vfs_svn": target_vfs_svn,
        }

    def _finish_probe(self, result: dict, reason: str) -> dict:
        """Log the actual probe values and stash them on the status dict."""
        diagnostics = result.setdefault("diagnostics", {})
        lines = [
            f"[KitsuImport] Repository probe ({reason}):",
            f"  state={result.get('state')} repo={result.get('repo_name')} "
            f"target={result.get('target')} source={result.get('source')}",
            f"  server={diagnostics.get('server_name')} id={diagnostics.get('server_id')} "
            f"declared_mode={diagnostics.get('declared_mode')} "
            f"url_mode={diagnostics.get('url_mode')} "
            f"effective_mode={diagnostics.get('effective_mode')} "
            f"url={diagnostics.get('repository_url')}",
        ]
        if diagnostics.get("mismatch"):
            lines.append(f"  mismatch={diagnostics['mismatch']}")
        if diagnostics.get("repo_path"):
            lines.append(
                f"  repo_path={diagnostics.get('repo_path')} "
                f"file_url={diagnostics.get('file_url')}"
            )
        if diagnostics.get("command"):
            lines.append(
                f"  command={diagnostics.get('command')!r} "
                f"returncode={diagnostics.get('returncode')}"
            )
            lines.append(f"  stdout={diagnostics.get('stdout', '')!r}")
            lines.append(f"  stderr={diagnostics.get('stderr', '')!r}")
        lines.append(f"  dirs={result.get('dirs')}")
        if diagnostics.get("reason"):
            lines.append(f"  reason={diagnostics['reason']}")
        text = "\n".join(lines)
        diagnostics["log"] = text
        print(text)
        return result

    def create_target_person(self, source_person: dict) -> dict:
        """Create a person on the target with NO password (admin finishes setup)."""
        full_name = str(source_person.get("full_name", "") or "").strip()
        first_name = str(source_person.get("first_name", "") or "").strip()
        last_name = str(source_person.get("last_name", "") or "").strip()
        if not first_name and full_name:
            parts = full_name.split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""
        return self.kitsu.new_person(
            first_name=first_name or full_name or "Artist",
            last_name=last_name,
            email=str(source_person.get("email", "") or ""),
            role=str(source_person.get("role", "user") or "user"),
            password=None,
        )

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------
    def import_project(
        self,
        plan: ImportPlan,
        person_map: Optional[Dict[str, dict]] = None,
        options: Optional[ImportOptions] = None,
    ) -> ImportReport:
        self._cancel.clear()
        self._log_lines = []
        options = options or ImportOptions()
        person_map = person_map or {}

        conflict = self.check_conflict(plan)
        if conflict:
            return ImportReport(False, conflict, archive_path=plan.archive_path)

        self._phase("Verifying archive integrity...")
        try:
            ok, mismatches = self.verify(plan.archive_path)
        except ManifestError as error:
            return ImportReport(False, str(error), archive_path=plan.archive_path)
        if not ok:
            preview = ", ".join(mismatches[:5])
            return ImportReport(
                False,
                f"Archive checksum verification failed ({len(mismatches)} file(s)): {preview}",
                archive_path=plan.archive_path,
            )

        status = self.probe_repository(plan, options.target_vcs_server_id)
        if status["state"] == "missing":
            return ImportReport(
                False,
                f"Repository '{status['repo_name']}' was not found on "
                f"'{status['server_name'] or 'the target server'}'. Create/push it first.",
                archive_path=plan.archive_path,
            )
        if status["state"] == "rename_needed" and not options.rename_repository:
            return ImportReport(
                False,
                f"Repository '{status['repo_name']}' contains folder '{status['source']}' "
                f"instead of '{status['target']}'. Enable the repository rename to continue.",
                archive_path=plan.archive_path,
            )

        if options.dry_run:
            rows = self.preview_person_mapping(plan)
            unmatched = [row.source.get("email", "") for row in rows if not row.matched]
            message = (
                f"Dry run OK for '{plan.project_name}'. "
                f"{len(rows)} person(s) referenced, {len(unmatched)} without a target match. "
                f"Repository state: {status['state']}. Counts: {plan.counts}."
            )
            return ImportReport(
                True, message, dry_run=True,
                project_name=plan.project_name, archive_path=plan.archive_path,
            )

        extract_dir = Path(tempfile.mkdtemp(prefix="oshproject_import_"))
        report = ImportReport(False, "", project_name=plan.project_name, archive_path=plan.archive_path)
        context: Optional[_ImportContext] = None
        try:
            self._phase(f"Reading '{plan.project_name}' from the archive...")
            self._progress(3)
            with OshProjectReader(plan.archive_path) as reader:
                reader.extract_to(extract_dir)
            media_index = _index_media(extract_dir)

            self._phase("Creating the Kitsu project...")
            target_project = self._create_project(plan)
            if not target_project:
                return ImportReport(False, "Failed to create the project on the target Kitsu server.", archive_path=plan.archive_path)
            context = _ImportContext(target_project)
            report.project_id = context.project_id
            # Grant the importing user manager rights on the new project before
            # any task metadata update; otherwise Kitsu rejects task writes with
            # a 403 (project role inherited from the global/person role).
            self._ensure_current_user_manager(context)
            self._progress(10)

            self._register_person_map(context, person_map, source_persons=plan.persons_json)
            self._create_or_get_studio(context, plan, extract_dir)
            self._progress(20)

            self._create_entities(context, extract_dir)
            self._progress(45)

            self._apply_casting(context, extract_dir)
            self._create_tasks(context, extract_dir)
            self._progress(65)

            self._create_comments(context, extract_dir, media_index)
            self._create_working_files(context, extract_dir)
            self._create_time_spent(context, extract_dir)
            self._progress(78)

            self._add_team(context)

            project_root, needs_checkout = self._recreate_hub_project(plan, context, options, extract_dir)
            report.project_root = project_root
            report.needs_checkout = needs_checkout
            report.rollback_available = True
            self._progress(100)

            message = (
                f"Imported '{plan.project_name}' into Kitsu: "
                f"{context.counter('assets_created')} assets, {context.counter('shots_created')} shots, "
                f"{context.counter('tasks_created')} tasks, {context.counter('comments_created')} comments, "
                f"{context.counter('replies_created')} replies, {context.counter('previews_created')} previews, "
                f"{context.counter('working_files_created')} working files, "
                f"{context.counter('team_members')} team members."
            )
            if needs_checkout:
                message += " Check out the files from VCS to finish the local install."
            report.success = True
            report.message = message
            report.created_persons = list(context.person_map.keys())
            report.phases = [line for line in (self._log_lines or [])]
            self._phase(message, "green")
            self._log(message)
            return report

        except ManifestError as error:
            return ImportReport(False, str(error), archive_path=plan.archive_path)
        except Exception as error:  # noqa: BLE001
            import traceback

            print(f"[KitsuImport] CRASH:\n{traceback.format_exc()}")
            if context is not None:
                report.rollback_available = True
            return ImportReport(
                False, f"Import failed: {error}",
                project_id=context.project_id if context else "",
                project_name=plan.project_name,
                rollback_available=context is not None,
                archive_path=plan.archive_path,
            )
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------
    def rollback(self, plan: ImportPlan, project_id: str) -> Tuple[bool, str]:
        """Best-effort deletion of the partially-created Kitsu project."""
        if not project_id:
            return False, "Nothing to roll back."
        return self.kitsu.delete_project(project_id)

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------
    def _create_project(self, plan: ImportPlan) -> dict:
        name = plan.project_name
        success, _message, project = self.kitsu.create_project(name)
        if not success or not project:
            project = self._safe(lambda: self.kitsu.get_project_by_name(name), None)
        if not project:
            return {}
        data = plan.project.get("data") or {}
        if data:
            self._safe(lambda: self.kitsu.update_project_data(project, data), None)
        # Project status: create-or-get by name, then best-effort update.
        status_name = plan.project.get("project_status_name")
        if status_name:
            status = self._safe(lambda: self.kitsu.get_project_status_by_name(status_name), None)
            if status:
                project = dict(project)
                project["project_status_id"] = status.get("id", "")
                self._safe(lambda: self.kitsu.update_project(project), None)
        self._log(f"Kitsu project '{name}' created (id {project.get('id', '')}).")
        return project

    def _register_person_map(self, context: _ImportContext, person_map: Dict[str, dict], source_persons: List[dict]) -> None:
        for source in source_persons:
            source_id = str(source.get("id", "") or "")
            target = person_map.get(source_id)
            if isinstance(target, str):
                target = {"id": target}
            if isinstance(target, dict) and target.get("id"):
                context.person_map[source_id] = target
        self._log(f"People mapped: {len(context.person_map)}/{len(source_persons)} referenced person(s).")

    def _map_person(self, context: _ImportContext, person) -> Optional[dict]:
        """Resolve a source person (id string or dict) to its mapped target."""
        if person is None:
            return None
        if isinstance(person, str):
            return context.person_map.get(person)
        if not isinstance(person, dict):
            return None
        source_id = str(person.get("id", "") or person.get("person_id", "") or "")
        if source_id and source_id in context.person_map:
            return context.person_map[source_id]
        email = str(person.get("email", "") or "").strip().lower()
        if email:
            for mapped in context.person_map.values():
                if str(mapped.get("email", "") or "").strip().lower() == email:
                    return mapped
        return None

    def _create_or_get_studio(self, context: _ImportContext, plan: ImportPlan, extract_dir: Path) -> None:
        self._phase("Creating studio resources...")
        statuses = _read_json(extract_dir, "kitsu/studio/task_statuses.json")
        task_types = _read_json(extract_dir, "kitsu/studio/task_types.json")
        asset_types = _read_json(extract_dir, "kitsu/studio/asset_types.json")
        departments = _read_json(extract_dir, "kitsu/studio/departments.json")

        target_statuses = {_name_key(s): s for s in self._safe(lambda: self.kitsu.all_task_statuses(), [])}
        for source in statuses:
            key = _name_key(source)
            target = target_statuses.get(key)
            if target is None:
                target = self._safe(
                    lambda s=source: self.kitsu.new_task_status(
                        s.get("name", ""), s.get("short_name", ""), s.get("color", "#000000")
                    ),
                    None,
                )
                if target:
                    context.bump("statuses_created")
            else:
                context.bump("statuses_reused")
            if target:
                target_statuses[key] = target
                context.status_map[str(source.get("id", ""))] = target

        self._link_task_statuses_to_project(context, extract_dir)

        target_types = {_name_key(t): t for t in self._safe(lambda: self.kitsu.all_task_types(), [])}
        for source in task_types:
            key = _name_key(source)
            target = target_types.get(key)
            if target is None:
                target = self._safe(
                    lambda t=source: self.kitsu.new_task_type(
                        t.get("name", ""), t.get("color", "#000000"), t.get("for_entity", "Asset")
                    ),
                    None,
                )
                if target:
                    context.bump("task_types_created")
            else:
                context.bump("task_types_reused")
            if target:
                target_types[key] = target
                context.task_type_map[str(source.get("id", ""))] = target

        target_asset_types = {_name_key(a): a for a in self._safe(lambda: self.kitsu.all_asset_types(), [])}
        for source in asset_types:
            key = _name_key(source)
            target = target_asset_types.get(key)
            if target is None:
                target = self._safe(lambda a=source: self.kitsu.new_asset_type(a.get("name", "")), None)
                if target:
                    context.bump("asset_types_created")
            else:
                context.bump("asset_types_reused")
            if target:
                target_asset_types[key] = target
                context.asset_type_map[str(source.get("id", ""))] = target

        target_departments = {_name_key(d): d for d in self._safe(lambda: self.kitsu.all_departments(), [])}
        for source in departments:
            key = _name_key(source)
            target = target_departments.get(key)
            if target is None:
                target = self._safe(
                    lambda d=source: self.kitsu.new_department(d.get("name", ""), d.get("color", "")), None
                )
                if target:
                    context.bump("departments_created")
            else:
                context.bump("departments_reused")
            if target:
                target_departments[key] = target
                context.department_map[str(source.get("id", ""))] = target

        self._log(
            "Studio resources ready: "
            f"task statuses {context.counter('statuses_created')} new/"
            f"{context.counter('statuses_reused')} reused, "
            f"task types {context.counter('task_types_created')} new/"
            f"{context.counter('task_types_reused')} reused, "
            f"asset types {context.counter('asset_types_created')} new/"
            f"{context.counter('asset_types_reused')} reused, "
            f"departments {context.counter('departments_created')} new/"
            f"{context.counter('departments_reused')} reused."
        )

    def _link_task_statuses_to_project(
        self,
        context: _ImportContext,
        extract_dir: Path,
    ) -> None:
        """Link every task status referenced by the import to the project.

        The exported ``kitsu/studio/task_statuses.json`` is per-production and
        can be empty even when tasks reference global statuses. Any referenced
        id missing from :attr:`_ImportContext.status_map` is therefore resolved
        against the global status list before linking, so migrated productions
        do not end up with zero ``project_task_status_link`` entries.
        """
        if not context.project_id:
            return

        global_statuses = self._safe(lambda: self.kitsu.all_task_statuses(), []) or []
        global_by_id = {str(s.get("id", "")): s for s in global_statuses if s.get("id")}

        referenced: List[str] = []
        for task in _read_json(extract_dir, "kitsu/tasks.json"):
            status_id = str(task.get("task_status_id", "") or "")
            if status_id and status_id not in context.status_map and status_id not in referenced:
                referenced.append(status_id)

        for status_id in referenced:
            status = global_by_id.get(status_id)
            if status is None:
                status = self._safe(lambda sid=status_id: self.kitsu.get_task_status(sid), None)
            if status:
                context.status_map[status_id] = status

        targets: List[dict] = []
        seen: set = set()
        for status in context.status_map.values():
            status_id = str(status.get("id", "") or "")
            if status_id and status_id not in seen:
                seen.add(status_id)
                targets.append(status)

        if not targets:
            return

        existing = {
            str(s.get("id", ""))
            for s in self._safe(
                lambda: self.kitsu.all_task_statuses_for_project(context.project_id), []
            )
        }
        for status in targets:
            status_id = str(status.get("id", "") or "")
            if status_id in existing:
                continue
            linked = self._safe(
                lambda sid=status_id: self.kitsu.link_task_status_to_project(context.project_id, sid),
                None,
            )
            if linked is not None:
                context.bump("statuses_linked")

        self._log(
            f"Task statuses linked to project: {context.counter('statuses_linked')} new "
            f"({len(targets)} referenced)."
        )

    def _create_entities(self, context: _ImportContext, extract_dir: Path) -> None:
        self._phase("Recreating episodes, sequences, shots, assets and edits...")
        project = context.project

        for source in _read_json(extract_dir, "kitsu/entities/episodes.json"):
            target = self._safe(lambda s=source: self.kitsu.get_episode_by_name(project, s.get("name", "")), None)
            if target is None:
                target = self._safe(lambda s=source: self.kitsu.new_episode(project, s.get("name", "")), None)
                if target:
                    context.bump("episodes_created")
            else:
                context.bump("episodes_reused")
            if target:
                context.episode_map[str(source.get("id", ""))] = target

        for source in _read_json(extract_dir, "kitsu/entities/sequences.json"):
            episode = context.episode_map.get(str(source.get("parent_id", "") or ""))
            target = self._safe(lambda s=source: self.kitsu.get_sequence_by_name(project, s.get("name", ""), episode=episode), None)
            if target is None:
                target = self._safe(
                    lambda s=source, e=episode: self.kitsu.new_sequence(project, s.get("name", ""), episode=e), None
                )
                if target:
                    context.bump("sequences_created")
            else:
                context.bump("sequences_reused")
            if target:
                context.sequence_map[str(source.get("id", ""))] = target

        for source in _read_json(extract_dir, "kitsu/entities/shots.json"):
            sequence = context.sequence_map.get(str(source.get("parent_id", "") or ""))
            if sequence is None:
                sequence = _first(context.sequence_map.values())
            if sequence is None:
                continue
            target = self._safe(lambda s=source: self.kitsu.get_shot_by_name(sequence, s.get("name", "")), None)
            if target is None:
                target = self._safe(
                    lambda s=source, seq=sequence: self.kitsu.new_shot(
                        project, seq, s.get("name", ""),
                        nb_frames=s.get("nb_frames"), frame_in=s.get("frame_in"),
                        frame_out=s.get("frame_out"), description=s.get("description"),
                        data=s.get("data"),
                    ),
                    None,
                )
                if target:
                    context.bump("shots_created")
            else:
                context.bump("shots_reused")
            if target:
                context.shot_map[str(source.get("id", ""))] = target
                self._copy_entity_data("shot", target, source)

        for source in _read_json(extract_dir, "kitsu/entities/assets.json"):
            asset_type = context.asset_type_map.get(str(source.get("entity_type_id", "") or ""))
            episode = context.episode_map.get(str(source.get("source_id", "") or "")) or context.episode_map.get(str(source.get("episode_id", "") or ""))
            target = self._safe(lambda s=source: self.kitsu.get_asset_by_name(project, s.get("name", ""), asset_type), None)
            if target is None:
                target = self._safe(
                    lambda s=source, at=asset_type, ep=episode: self.kitsu.new_asset(
                        project, at, s.get("name", ""), description=s.get("description"),
                        extra_data=s.get("data"), episode=ep, is_shared=bool(s.get("is_shared", False)),
                    ),
                    None,
                )
                if target:
                    context.bump("assets_created")
            else:
                context.bump("assets_reused")
            if target:
                context.asset_map[str(source.get("id", ""))] = target
                self._copy_entity_data("asset", target, source)

        for source in _read_json(extract_dir, "kitsu/entities/edits.json"):
            episode = context.episode_map.get(str(source.get("episode_id", "") or ""))
            target = self._safe(lambda s=source: self.kitsu.get_edit_by_name(project, s.get("name", "")), None)
            if target is None:
                target = self._safe(
                    lambda s=source, ep=episode: self.kitsu.new_edit(
                        project, s.get("name", ""), description=s.get("description"),
                        data=s.get("data"), episode=ep,
                    ),
                    None,
                )
                if target:
                    context.bump("edits_created")
            else:
                context.bump("edits_reused")
            if target:
                context.edit_map[str(source.get("id", ""))] = target
                self._copy_entity_data("edit", target, source)

        self._log(
            "Entities ready: "
            f"episodes {context.counter('episodes_created')} new/{context.counter('episodes_reused')} reused, "
            f"sequences {context.counter('sequences_created')} new/{context.counter('sequences_reused')} reused, "
            f"shots {context.counter('shots_created')} new/{context.counter('shots_reused')} reused, "
            f"assets {context.counter('assets_created')} new/{context.counter('assets_reused')} reused, "
            f"edits {context.counter('edits_created')} new/{context.counter('edits_reused')} reused."
        )

    def _copy_entity_data(self, kind: str, target: dict, source: dict) -> None:
        data = source.get("data")
        if not data:
            return
        setter = {
            "shot": self.kitsu.update_shot_data,
            "asset": self.kitsu.update_asset_data,
            "edit": self.kitsu.update_edit_data,
        }.get(kind)
        if setter is not None:
            self._safe(lambda: setter(target, data), None)

    def _map_entity(self, context: _ImportContext, entity_id: str) -> Optional[dict]:
        entity_id = str(entity_id or "")
        for mapping in (context.shot_map, context.asset_map, context.edit_map, context.sequence_map, context.episode_map):
            if entity_id in mapping:
                return mapping[entity_id]
        return None

    def _apply_casting(self, context: _ImportContext, extract_dir: Path) -> None:
        casting = _read_json(extract_dir, "kitsu/casting.json") or {}
        project = context.project

        for link in casting.get("entity_links") or []:
            asset = context.asset_map.get(str(link.get("asset_id", "") or ""))
            entity = self._map_entity(context, link.get("entity_id", ""))
            if asset is None or entity is None:
                continue
            self._safe(
                lambda a=asset, e=entity, l=link: self.kitsu.cast_asset(
                    project, e, a, nb_occurences=l.get("nb_occurences"), label=l.get("label")
                ),
                None,
            )

        shots_casting = casting.get("shots_casting") or {}
        for shot_id, casting_value in shots_casting.items():
            shot = context.shot_map.get(str(shot_id))
            if shot is None:
                continue
            remapped = self._remap_casting(casting_value, context)
            self._safe(lambda s=shot, c=remapped: self.kitsu.update_shot_casting(project, s, c), None)

    def _remap_casting(self, value, context: _ImportContext):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                new_key = self._remap_casting(key, context)
                result[new_key] = self._remap_casting(item, context)
            return result
        if isinstance(value, list):
            return [self._remap_casting(item, context) for item in value]
        if isinstance(value, str):
            for mapping in (context.asset_map, context.asset_type_map, context.shot_map, context.sequence_map):
                if value in mapping:
                    return str(mapping[value].get("id", value))
        return value

    def _create_tasks(self, context: _ImportContext, extract_dir: Path) -> None:
        self._phase("Recreating tasks (preserving file paths)...")
        for source in _read_json(extract_dir, "kitsu/tasks.json"):
            entity = self._map_entity(context, source.get("entity_id", ""))
            task_type = context.task_type_map.get(str(source.get("task_type_id", "") or ""))
            task_status = context.status_map.get(str(source.get("task_status_id", "") or ""))
            if entity is None or task_type is None:
                continue
            assignees = [
                mapped for mapped in (self._map_person(context, person) for person in _as_list(source.get("assignees")))
                if mapped is not None
            ]
            target = self._safe(
                lambda s=source, e=entity, tt=task_type, st=task_status, a=assignees: self.kitsu.new_task(
                    e, tt, name=s.get("name", "main"), task_status=st, assignees=a or None,
                ),
                None,
            )
            if target is None:
                continue
            context.task_map[str(source.get("id", ""))] = target
            context.bump("tasks_created")

            # Apply the status and the custom data in a SINGLE update. gazu's
            # ``update_task`` replaces the whole task (including its custom data),
            # so issuing separate PUTs from stale copies would let each overwrite
            # what the other wrote -- which silently wiped ``data.filepath``.
            data = source.get("data") or {}
            if task_status or data:
                updated = dict(target)
                if task_status:
                    updated["task_status_id"] = task_status.get("id", "")
                if data:
                    updated["data"] = dict(data)
                self._safe(lambda t=updated: self.kitsu.update_task(t), None)
                if data:
                    self._log(
                        f"Task '{source.get('name', 'main')}' filepath: "
                        f"{data.get('filepath') or '(none)'}"
                    )
            assigner = self._map_person(context, source.get("assigner") or source.get("assigner_id"))
            if assigner:
                self._safe(lambda t=target, p=assigner: self.kitsu.assign_task(t, p), None)
            for person in assignees:
                self._safe(lambda t=target, p=person: self.kitsu.assign_task(t, p), None)
                context.bump("task_assignments")

        self._log(
            f"Tasks ready: {context.counter('tasks_created')} created, "
            f"{context.counter('task_assignments')} assignment(s)."
        )

    def _create_comments(self, context: _ImportContext, extract_dir: Path, media_index: dict) -> None:
        self._phase("Recreating comments, replies and previews...")
        comments = _read_json(extract_dir, "kitsu/comments.json")
        by_id = {str(c.get("id", "")): c for c in comments}
        ordered = _sort_comments(comments)

        for source in ordered:
            task = context.task_map.get(str(source.get("task_id", "") or ""))
            if task is None:
                continue
            person = self._map_person(context, source.get("person_id") or source.get("person"))
            status = context.status_map.get(str(source.get("task_status_id", "") or ""))
            text = source.get("text") or source.get("comment") or ""
            parent_id = _comment_parent_id(source)
            parent_source = by_id.get(parent_id)
            parent_target = context.comment_map.get(parent_id) if parent_source else None

            if parent_target is not None:
                target = self._safe(
                    lambda t=task, p=parent_target, x=text, pe=person: self.kitsu.reply_to_comment(t, p, x, person=pe),
                    None,
                )
                if target is not None:
                    context.bump("replies_created")
            else:
                target = self._safe(
                    lambda t=task, st=status, x=text, pe=person, c=source: self.kitsu.add_comment(
                        t, st, comment=x, person=pe, created_at=c.get("created_at"),
                        for_client=bool(c.get("for_client", False)),
                    ),
                    None,
                )
                if target is not None:
                    context.bump("comments_created")
            if target is None:
                continue
            context.comment_map[str(source.get("id", ""))] = target

            attachments = self._resolve_attachments(source, media_index)
            if attachments:
                self._safe(lambda t=task, c=target, a=attachments: self.kitsu.add_attachment_files_to_comment(t, c, a), None)
                context.bump("attachments_uploaded", len(attachments))

        # Previews: re-publish downloaded files against their task.
        for task_id, paths in media_index.get("previews", {}).items():
            task = context.task_map.get(str(task_id))
            if task is None:
                continue
            status = _first(context.status_map.values())
            for path in paths:
                if "_thumb." in Path(path).name:
                    continue
                result = self._safe(
                    lambda t=task, p=path, st=status: self.kitsu.publish_preview(
                        t, st, comment="Imported preview", preview_file_path=str(p),
                    ),
                    None,
                )
                if result is not None:
                    context.bump("previews_created")

        self._log(
            f"Comments ready: {context.counter('comments_created')} comment(s), "
            f"{context.counter('replies_created')} reply(ies), "
            f"{context.counter('attachments_uploaded')} attachment(s), "
            f"{context.counter('previews_created')} preview(s)."
        )

    def _resolve_attachments(self, source: dict, media_index: dict) -> List[str]:
        paths: List[str] = []
        # Kitsu comments expose ``attachment_files``; older exports used
        # ``attachments``. Both may hold ids or expanded dicts.
        raw = source.get("attachment_files") or source.get("attachments") or []
        for attachment in _as_list(raw):
            if isinstance(attachment, dict):
                attachment_id = str(attachment.get("id", "") or "")
            else:
                attachment_id = str(attachment or "")
            local = media_index.get("attachments", {}).get(attachment_id)
            if local is not None:
                paths.append(str(local))
        return paths

    def _create_working_files(self, context: _ImportContext, extract_dir: Path) -> None:
        working_files = _read_json(extract_dir, "kitsu/working_files.json")
        if not working_files:
            return
        self._phase("Recreating working-file revisions (metadata only)...")
        for source in working_files:
            task = context.task_map.get(str(source.get("task_id", "") or ""))
            if task is None:
                continue
            person = self._map_person(context, source.get("person") or source.get("person_id"))
            software = self._resolve_software(source.get("software"))
            result = self._safe(
                lambda t=task, s=source, p=person, sw=software: self.kitsu.new_working_file(
                    t, name=s.get("name", "main"), mode=s.get("mode", "working"),
                    software=sw, comment=s.get("comment", ""), person=p,
                    revision=int(s.get("revision", 0) or 0), sep=s.get("sep", "/"),
                ),
                None,
            )
            if result is not None:
                context.bump("working_files_created")
        self._log(f"Working-file revisions ready: {context.counter('working_files_created')}.")

    def _resolve_software(self, software):
        name = None
        if isinstance(software, dict):
            name = software.get("name")
        elif isinstance(software, str):
            name = software
        if not name:
            return None
        return self._safe(lambda: self.kitsu.get_software_by_name(name), None)

    def _create_time_spent(self, context: _ImportContext, extract_dir: Path) -> None:
        entries = _read_json(extract_dir, "kitsu/time_spent.json")
        if not entries:
            return
        self._phase("Restoring time spent...")
        for entry in entries:
            task = context.task_map.get(str(entry.get("task_id", "") or ""))
            if task is None:
                continue
            target_person = context.person_map.get(str(entry.get("person_id", "") or ""))
            if target_person is None and entry.get("person"):
                target_person = self._map_person(context, entry.get("person"))
            if target_person is None:
                continue
            result = self._safe(
                lambda t=task, p=target_person, e=entry: self.kitsu.add_time_spent(
                    t, p, str(e.get("date", "") or ""), int(e.get("duration", 0) or 0)
                ),
                None,
            )
            if result is not None:
                context.bump("time_entries_created")
        self._log(f"Time-spent entries ready: {context.counter('time_entries_created')}.")

    def _add_team(self, context: _ImportContext) -> None:
        """Add every mapped person to the project team with a valid team role."""
        project = context.project
        current_id = self._current_user_id()
        for person in context.person_map.values():
            role = _team_role(person)
            if current_id and str(person.get("id", "")) == current_id and role != "manager":
                # The importing user must keep manager rights to write task data.
                role = "manager"
            result = self._safe(
                lambda p=person, r=role: self.kitsu.add_person_to_team(project, p, role=r),
                None,
            )
            if result is not None:
                context.bump("team_members")
        self._log(f"Project team ready: {context.counter('team_members')} member(s).")

    def _current_user_id(self) -> str:
        try:
            current = self.kitsu.get_current_user()
        except Exception:  # noqa: BLE001
            return ""
        return str((current or {}).get("id", "") or "") if isinstance(current, dict) else ""

    def _ensure_current_user_manager(self, context: _ImportContext) -> None:
        """Grant the importing user manager rights on the freshly created project.

        Kitsu rejects task writes with a 403 unless the caller is an admin or a
        project manager; a project-specific team role overrides the global role,
        so we pin the current user to ``manager`` before touching any task.
        """
        current_id = self._current_user_id()
        if not current_id:
            return
        project = context.project
        try:
            self.kitsu.update_team_member_role(project, current_id, "manager")
            self._log("Importing user set as project manager.")
            return
        except Exception:  # noqa: BLE001 - not a team member yet
            pass
        try:
            self.kitsu.add_person_to_team(project, current_id, role="manager")
            self._log("Importing user added to the project team as manager.")
        except Exception as error:  # noqa: BLE001
            self._log(
                "Warning: could not grant manager access to the importing user "
                f"({error}). Task metadata updates may fail with 403 unless this "
                "account is a global admin or a project manager on the target."
            )

    # ------------------------------------------------------------------
    # Hub project recreation
    # ------------------------------------------------------------------
    def _recreate_hub_project(
        self, plan: ImportPlan, context: _ImportContext, options: ImportOptions, extract_dir: Path
    ) -> Tuple[Optional[Path], bool]:
        self._phase("Recreating the Hub project on this machine...")
        project_root = self._project_root(plan.project_name)
        blueprint = ProjectBlueprint.from_dict(plan.manifest.get("blueprint") or {})
        blueprint.project_name = plan.project_name
        blueprint.kitsu_project_id = context.project_id

        # The source studio's topography may differ from this machine's (e.g. the
        # pipeline folder name). Use the target topography so the blueprint lands
        # where InstallationService expects it.
        source_vfs_svn = str(plan.source_topography.get("vfs_svn") or "")
        target_topography = self._target_topography()
        if target_topography is not None:
            blueprint.topography = target_topography
        target_vfs_svn = blueprint.topography.vfs_svn
        repo_name = normalize_repo_name(plan.project_name)

        server = self._target_server(options.target_vcs_server_id)
        if server is not None:
            blueprint.vcs_server_id = server.id
            blueprint.vcs_base_url = server.repository_url
        elif plan.vcs:
            blueprint.vcs_server_id = str(plan.vcs.get("server_id", "") or "")
            blueprint.vcs_base_url = str(plan.vcs.get("server_url", "") or "")

        # Do NOT pre-create the VCS folders: the repository already owns them and
        # a later checkout into an unversioned tree raises tree conflicts.
        WorkspaceScaffolder.build_directories(project_root, blueprint, include_vcs=False)
        # Restore the non-VCS payload (local/ is never exported) before writing
        # the blueprint so our target-topography project_init.json wins.
        self._restore_non_vcs_files(project_root, blueprint, extract_dir)
        BlueprintGenerator.write_manifests(project_root, blueprint)
        self._safe(
            lambda: AddonConfigGenerator(self.config_factory).generate(
                project_root, blueprint.addon_configuration, blueprint.topography
            ),
            None,
        )
        self._upload_project_splash(context, blueprint, project_root)

        dump_path = Path(extract_dir) / SVN_DUMP_NAME
        embed_dump = bool(plan.inclusion.get("embed_svn_dump")) and dump_path.exists()
        if embed_dump and server is not None:
            ok, message = self._load_dump(server, plan.project_name, dump_path)
            self._log(message)
            if not ok:
                self._log("Warning: the embedded dump could not be loaded.")
                return project_root, True
            self._map_repo_topography(
                server, repo_name, source_vfs_svn, target_vfs_svn, blueprint,
                rename=options.rename_repository,
            )
            return project_root, False

        # No dump: the referenced repository is expected to exist already. If it
        # exists with the source folder name, reconcile it so checkout succeeds.
        if server is not None:
            self._map_repo_topography(
                server, repo_name, source_vfs_svn, target_vfs_svn, blueprint,
                rename=options.rename_repository,
            )
        return project_root, True

    def _map_repo_topography(
        self, server, repo_name: str, source_vfs_svn: str, target_vfs_svn: str, blueprint,
        rename: bool = False,
    ) -> None:
        """Reconcile the repository's top-level folder and svn:ignore properties."""
        if not target_vfs_svn:
            return
        repo_path = self._repo_path(server, repo_name)
        dirs = self._repo_top_level_dirs(server, repo_path)
        if not dirs:
            self._log(f"Repository '{repo_name}' not found on the target; skipping topology mapping.")
            return
        target_present = target_vfs_svn in dirs
        if target_present:
            entries, listing_ok = self._list_dir_url(
                server, f"file://{repo_path}/{target_vfs_svn}"
            )
            # An empty target folder is not usable: treat it as absent so the
            # rename (or the "no folder" warning) applies.
            target_present = (not listing_ok) or bool(entries)
        if target_present:
            self._log(f"Repository topology already uses '{target_vfs_svn}'.")
        elif rename:
            candidate = source_vfs_svn if source_vfs_svn in dirs else ""
            if not candidate:
                others = [name for name in dirs if name != target_vfs_svn]
                if len(others) == 1:
                    candidate = others[0]
            if candidate:
                ok, message = self._reconcile_repo_topology(server, repo_path, candidate, target_vfs_svn)
                self._log(message)
                if not ok:
                    self._log("Warning: the repository topology may need manual adjustment.")
            else:
                self._log(f"Repository has no single folder to rename to '{target_vfs_svn}'.")
        else:
            self._log(f"Repository has no '{target_vfs_svn}' folder; rename not authorized.")
        self._rewrite_repo_ignore(server, repo_path, target_vfs_svn, blueprint)

    @staticmethod
    def _remote_docker_inner(server, inner: str) -> str:
        container = shlex.quote(server.profile.remote.container)
        return f"docker exec {container} sh -c {shlex.quote(inner)}"

    def _server_command(self, server, inner: str):
        """Run a command on the VCS server (local Docker or remote SSH).

        Records the executed command and its output on
        ``self._last_server_command_detail`` so the repository probe can log the
        actual values (transport, command, exit code, stdout/stderr).
        """
        detail = {
            "transport": "local_docker" if self._is_local(server) else "remote_ssh",
            "command": inner,
            "returncode": None,
            "stdout": "",
            "stderr": "",
        }
        try:
            if self._is_local(server):
                result = subprocess.run(
                    ["docker", "exec", server.profile.local_container, "sh", "-c", inner],
                    capture_output=True, text=True,
                )
            else:
                from src.infrastructure.vcs.ssh_runner import SshRunner

                runner = SshRunner(server.profile.remote, passphrase_provider=self._passphrase_provider(server))
                result = runner.run(self._remote_docker_inner(server, inner), check=False)
        except Exception as error:  # noqa: BLE001 - never let a probe crash the import
            result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=str(error))

        detail["returncode"] = getattr(result, "returncode", None)
        detail["stdout"] = _as_text(getattr(result, "stdout", ""))
        detail["stderr"] = _as_text(getattr(result, "stderr", ""))
        self._last_server_command_detail = detail
        return result

    def _list_dir_url(self, server, url: str) -> Tuple[List[str], bool]:
        """List entries of a repository URL; ``(entries, listing_ok)``."""
        result = self._server_command(server, f"svn ls {shlex.quote(url)}")
        returncode = getattr(result, "returncode", 1)
        stdout = _as_text(getattr(result, "stdout", ""))
        entries = [line.strip().rstrip("/") for line in stdout.splitlines() if line.strip()]
        return entries, returncode == 0

    def _repo_dir_exists(self, server, repo_path: str) -> Optional[bool]:
        """Whether the repository directory exists on the host.

        Returns ``True`` when present, ``False`` when definitively absent and
        ``None`` when the host could not be reached (so a transport failure is
        never reported as a missing repository).
        """
        result = self._server_command(server, f"test -d {shlex.quote(repo_path)}")
        returncode = getattr(result, "returncode", 1)
        stderr = _as_text(getattr(result, "stderr", "")).strip()
        if returncode == 0:
            return True
        if returncode == 1 and not stderr:
            return False
        return None

    def _repo_top_level_dirs(self, server, repo_path: str) -> List[str]:
        """List the repository root and record the probe detail for diagnostics.

        Sets ``self._last_repo_probe`` with the resolved ``exists`` state and the
        raw command output so callers can tell a genuinely missing repository
        from an unreachable host or an empty/unreadable one.
        """
        exists = self._repo_dir_exists(server, repo_path)
        if exists is not True:
            self._last_repo_probe = {
                "exists": exists,
                **(self._last_server_command_detail or {}),
            }
            return []

        url = f"file://{repo_path}"
        inner = f"svn ls {shlex.quote(url)}"
        result = self._server_command(server, inner)
        detail = self._last_server_command_detail or {}
        returncode = getattr(result, "returncode", 1)
        stdout = _as_text(getattr(result, "stdout", ""))
        self._last_repo_probe = {
            "exists": True,
            "transport": detail.get("transport", ""),
            "command": inner,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": _as_text(getattr(result, "stderr", "")),
        }
        if returncode != 0:
            return []
        return [line.strip().rstrip("/") for line in stdout.splitlines() if line.strip()]

    def _reconcile_repo_topology(self, server, repo_path: str, source_vfs_svn: str, target_vfs_svn: str) -> Tuple[bool, str]:
        source_url = f"file://{repo_path}/{source_vfs_svn}"
        target_url = f"file://{repo_path}/{target_vfs_svn}"
        # An existing (empty) target folder would block ``svn mv``; drop it first.
        entries, listing_ok = self._list_dir_url(server, target_url)
        if listing_ok and not entries:
            self._server_command(
                server,
                f"svn rm {shlex.quote(target_url)} -m 'Hub: drop empty target folder'",
            )
        inner = (
            f"svn mv {shlex.quote(source_url)} {shlex.quote(target_url)} "
            f"-m 'Hub: map topography {source_vfs_svn} -> {target_vfs_svn}'"
        )
        result = self._server_command(server, inner)
        if getattr(result, "returncode", 1) != 0:
            stderr = result.stderr or ""
            if isinstance(stderr, (bytes, bytearray)):
                stderr = stderr.decode("utf-8", "replace")
            return False, f"Failed to rename '{source_vfs_svn}' to '{target_vfs_svn}': {stderr.strip()}"
        return True, f"Renamed repository folder '{source_vfs_svn}' -> '{target_vfs_svn}'."

    def _rewrite_repo_ignore(self, server, repo_path: str, target_vfs_svn: str, blueprint) -> None:
        topography = blueprint.topography
        patterns = [
            topography.vfs_local, topography.vfs_shared, topography.vfs_pipeline,
            "*.blend1", "*.blend2",
        ]
        value = "\n".join(str(item) for item in patterns if item) + "\n"
        safe = value.replace("'", "'\\''")
        target_url = f"file://{repo_path}/{target_vfs_svn}"
        inner = (
            f"printf '%s' '{safe}' > /tmp/osh_ignore && "
            f"svn propset svn:ignore -F /tmp/osh_ignore {shlex.quote(target_url)} "
            f"-m 'Hub: topographic ignores' && rm -f /tmp/osh_ignore"
        )
        result = self._server_command(server, inner)
        if getattr(result, "returncode", 1) == 0:
            self._log("Rewrote the repository svn:ignore properties for the target topography.")
        else:
            self._log("Warning: could not rewrite the repository svn:ignore properties.")

    def _load_dump(self, server, project_name: str, dump_gz_path: Path) -> Tuple[bool, str]:
        repo_name = normalize_repo_name(project_name)
        vfs_svn = self._vfs_svn()
        admin = build_repository_admin(server.profile, self._passphrase_provider(server))
        if not admin.create(repo_name, vfs_svn, initialize_topology=False):
            return False, f"Failed to create the target repository '{repo_name}'."

        raw = dump_gz_path.with_suffix("")
        with gzip.open(dump_gz_path, "rb") as source, open(raw, "wb") as dest:
            shutil.copyfileobj(source, dest)

        try:
            if self._is_local(server):
                proc = subprocess.Popen(
                    ["docker", "exec", "-i", server.profile.local_container, "sh", "-c", f"svnadmin load {shlex.quote(self._repo_path(server, repo_name))}"],
                    stdin=open(raw, "rb"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
            else:
                from src.infrastructure.vcs.ssh_runner import SshRunner

                runner = SshRunner(server.profile.remote, passphrase_provider=self._passphrase_provider(server))
                inner = f"svnadmin load {shlex.quote(self._repo_path(server, repo_name))}"
                container = shlex.quote(server.profile.remote.container)
                proc, _cleanup = runner.popen(
                    f"docker exec -i {container} sh -c {shlex.quote(inner)}",
                    stdin=open(raw, "rb"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
            _out, err = proc.communicate()
        except Exception as error:  # noqa: BLE001
            return False, f"svnadmin load failed: {error}"
        if proc.returncode != 0:
            text = (err or b"").decode("utf-8", "replace") if isinstance(err, (bytes, bytearray)) else str(err)
            return False, f"svnadmin load failed: {text.strip()}"
        return True, f"Loaded the embedded SVN dump into '{repo_name}'."

    # ------------------------------------------------------------------
    # Checkout helper (post-import, when no dump was embedded)
    # ------------------------------------------------------------------
    def checkout_project(self, project_root: Path, vcs_user: str, vcs_pwd: str, user_role: str = "td") -> Tuple[bool, str]:
        if self.installation_service is None:
            return False, "The installation service is not available."
        status = lambda message, color="white": self._status(message, color)
        try:
            return self.installation_service.instalar_entorno(
                Path(project_root), vcs_user, vcs_pwd, status, user_role=user_role,
            )
        except Exception as error:  # noqa: BLE001
            return False, f"Checkout failed: {error}"

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------
    def _target_server(self, server_id: str):
        if self.config_factory is None:
            return None
        getter = getattr(self.config_factory, "get_server", None)
        server = getter(server_id) if callable(getter) and server_id else None
        if server is None:
            default = getattr(self.config_factory, "get_default_server", None)
            server = default() if callable(default) else None
        return server

    def _project_root(self, project_name: str) -> Path:
        if self.nas_manager is not None:
            resolved = self.nas_manager.resolve_project_dir(project_name)
            if resolved is not None:
                return Path(resolved)
            base = getattr(self.nas_manager, "base_dir", None)
            if base:
                return Path(base) / project_name.strip().lower().replace(" ", "-")
        if self.config_factory is not None:
            return self.config_factory.get_workspace_root() / project_name.strip().lower().replace(" ", "-")
        return Path(project_name.strip().lower().replace(" ", "-"))

    def _vfs_svn(self) -> str:
        if self.config_factory is not None:
            try:
                return self.config_factory.get_vfs_svn_name()
            except Exception:  # noqa: BLE001
                pass
        return "svn"

    def _target_topography(self):
        if self.config_factory is None:
            return None
        getter = getattr(self.config_factory, "get_topography", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:  # noqa: BLE001
            return None

    def _restore_non_vcs_files(self, project_root: Path, blueprint, extract_dir: Path) -> None:
        """Copy the archived non-VCS payload into the target project tree.

        `pipeline/` is always exported (and is SVN-ignored), `shared/` only when
        requested; `local/` is never exported (machine-specific).
        """
        files_root = Path(extract_dir) / FILES_DIR
        destinations = (
            ("pipeline", getattr(blueprint.topography, "vfs_pipeline", "pipeline")),
            ("shared", getattr(blueprint.topography, "vfs_shared", "shared")),
        )
        for archive_name, target_name in destinations:
            source = files_root / archive_name
            if not source.is_dir():
                continue
            destination = Path(project_root) / target_name
            destination.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copytree(source, destination, dirs_exist_ok=True)
                self._log(f"Restored {archive_name}/ into {target_name}/.")
            except Exception as error:  # noqa: BLE001
                self._log(f"Warning: could not restore {archive_name}/: {error}")

        # Custom dirs are project-root siblings (not in SVN); restore by name.
        custom_root = files_root / "custom"
        if custom_root.is_dir():
            for source in sorted(custom_root.iterdir()):
                if not source.is_dir():
                    continue
                destination = Path(project_root) / source.name
                destination.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copytree(source, destination, dirs_exist_ok=True)
                    self._log(f"Restored custom dir {source.name}/.")
                except Exception as error:  # noqa: BLE001
                    self._log(f"Warning: could not restore custom dir {source.name}/: {error}")

    def _upload_project_splash(self, context: _ImportContext, blueprint, project_root: Path) -> None:
        """Re-upload the pipeline splash as the Kitsu project thumbnail."""
        splash = Path(project_root) / getattr(blueprint.topography, "vfs_pipeline", "pipeline") / "splash.png"
        if not splash.is_file():
            return
        self._safe(lambda: self.kitsu.upload_project_splash(context.project_id, str(splash)), None)
        self._log("Uploaded the project thumbnail from pipeline/splash.png.")

    @staticmethod
    def _is_local(server) -> bool:
        from src.domain.workspace.vcs_server_profile import LOCAL_DOCKER

        return server.profile.mode == LOCAL_DOCKER

    @staticmethod
    def _repo_path(server, repo_name: str) -> str:
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


# ---------------------------------------------------------------------------
# Free helpers
# ---------------------------------------------------------------------------
def _as_text(value) -> str:
    """Normalize subprocess stdout/stderr (str or bytes) to text."""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _read_json(extract_dir: Path, relative: str):
    path = Path(extract_dir) / relative
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _name_key(item) -> str:
    if isinstance(item, dict):
        return str(item.get("name", "") or "").strip().lower()
    return str(item or "").strip().lower()


def _first(values):
    for value in values:
        return value
    return None


# Kitsu restricts the role a person may hold *on a project team*.
TEAM_ROLES = ("user", "supervisor", "manager", "client", "vendor")


def _team_role(person: dict) -> Optional[str]:
    """Project role to set for a team member, or ``None`` to inherit the global role.

    The archive only carries global roles, so pinning a project role here would
    wrongly downgrade global managers/admins. Invalid values (e.g. ``admin``,
    which is global-only) inherit instead.
    """
    role = str((person or {}).get("role", "") or "").strip().lower()
    return role if role in TEAM_ROLES else None


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _comment_parent_id(comment: dict) -> str:
    """Kitsu/older exports may name the parent link differently."""
    for key in ("parent_id", "reply_to_id", "reply_to", "parent"):
        value = comment.get(key)
        if isinstance(value, dict):
            value = value.get("id")
        if value:
            return str(value)
    return ""


def _sort_comments(comments: List[dict]) -> List[dict]:
    """Parents before replies (stable by created_at when available)."""
    by_id = {str(c.get("id", "")): c for c in comments}
    ordered: List[dict] = []
    seen = set()

    def visit(comment: dict) -> None:
        comment_id = str(comment.get("id", ""))
        if comment_id in seen:
            return
        parent_id = _comment_parent_id(comment)
        parent = by_id.get(parent_id)
        if parent is not None and parent is not comment:
            visit(parent)
        seen.add(comment_id)
        ordered.append(comment)

    for comment in sorted(comments, key=lambda c: str(c.get("created_at", ""))):
        visit(comment)
    return ordered


def _index_media(extract_dir: Path) -> dict:
    """Map preview/attachment ids to their extracted local paths."""
    index: dict = {"previews": {}, "attachments": {}}
    preview_root = Path(extract_dir) / MEDIA_PREVIEWS_DIR
    if preview_root.is_dir():
        for task_dir in preview_root.iterdir():
            if not task_dir.is_dir():
                continue
            for item in task_dir.iterdir():
                if not item.is_file():
                    continue
                preview_id = item.name.split("_", 1)[0]
                index["previews"].setdefault(task_dir.name, []).append(item)
    attachment_root = Path(extract_dir) / MEDIA_ATTACHMENTS_DIR
    if attachment_root.is_dir():
        for item in attachment_root.iterdir():
            if item.is_file():
                attachment_id = item.name.split("_", 1)[0]
                index["attachments"][attachment_id] = item
    return index
