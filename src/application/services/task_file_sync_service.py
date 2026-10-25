# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/task_file_sync_service.py
# Architectural role: Application service / VCS sync for task files
# =========================================================================================

"""Detects and publishes working-copy changes to the project's VCS.

After a DCC session ends the artist may have saved the task ``.blend`` plus
textures, libraries or other dependencies. This service inspects the VCS status
of the project workspace and reports the files that differ from the server so
the UI can present a checklist. Publishing commits only the selected files and
explicitly ``add``s the new (unversioned) ones.

The VCS engine is resolved exactly like ``InstallationService`` does: the
project workspace is ``<project_root>/<vfs_svn>`` and the repository URL is the
base URL plus ``<project_folder>/<vfs_svn>``.
"""

import fnmatch
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from src.domain.production.value_objects import FileChange
from src.infrastructure.vcs.svn_errors import SvnAlreadyLockedError
from src.infrastructure.vcs.svn_xml import status_code
from src.infrastructure.vcs.vcs_router import VCSRouter

# Files that are never worth publishing (DCC backups, caches, OS junk).
JUNK_GLOBS = (
    "*.pyc",
    "*.pyo",
    "*.tmp",
    "*.swp",
    "*.bak",
    "*.log",
    "*.lock",
    ".DS_Store",
    "Thumbs.db",
)

# ``file.blend1``, ``file.blend2``... are Blender's rotating backups.
JUNK_REGEXES = (re.compile(r"\.blend\d+$", re.IGNORECASE),)


@dataclass(frozen=True)
class VcsUpdateReport:
    """Outcome of an update, including the paths that need attention."""

    ok: bool
    message: str
    issues: Tuple[FileChange, ...] = ()


class TaskFileSyncService:
    def __init__(self, config_factory, router_factory=VCSRouter) -> None:
        self.config_factory = config_factory
        self.router_factory = router_factory

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def is_vcs_enabled(self, project_root: Path | None = None) -> bool:
        """True when the project is under version control (adapter != none)."""
        server = self._resolve_project_server(project_root) if project_root else None
        if server is not None:
            return server.adapter not in ("", "none")
        adapter = (self.config_factory.get_vcs_adapter_type() or "").strip().lower()
        return adapter not in ("", "none")

    def workspace_root(self, project_root: Path) -> Path:
        return Path(project_root) / self.config_factory.get_vfs_svn_name()

    def _build_adapter(self, project_root: Path):
        server = self._resolve_project_server(project_root)
        if server is not None:
            vcs_type = server.adapter
            profile = server.profile
            base_repo_url = self._resolve_project_repo_url(project_root) or server.repository_url
        else:
            vcs_type = self.config_factory.get_vcs_adapter_type()
            profile = self._server_profile()
            base_repo_url = self._resolve_project_repo_url(project_root)

        vfs_svn = self.config_factory.get_vfs_svn_name()
        workspace_root = self.workspace_root(project_root)
        final_repo_url = f"{base_repo_url}/{Path(project_root).name}/{vfs_svn}"

        router = self.router_factory(
            vcs_type=vcs_type,
            repo_url=final_repo_url,
            workspace_dir=workspace_root,
            server_profile=profile,
        )
        adapter = router.get_adapter()
        setter = getattr(adapter, "set_local_ignores", None)
        if callable(setter):
            try:
                setter(self.load_local_ignores(project_root))
            except Exception:  # noqa: BLE001 - ignores are best effort
                pass
        return adapter

    def _resolve_project_server(self, project_root: Path | None):
        getter = getattr(self.config_factory, "get_server_for_project", None)
        if project_root is None or not callable(getter):
            return None
        try:
            return getter(project_root)
        except Exception:  # noqa: BLE001
            return None

    def _resolve_project_repo_url(self, project_root: Path) -> str:
        """Prefer the per-project override stored in the blueprint, if present."""
        try:
            blueprint_path = Path(project_root) / self.config_factory.get_vfs_pipeline_name() / "project_init.json"
            if blueprint_path.exists():
                import json

                with open(blueprint_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                override = (data or {}).get("vcs_base_url")
                if override:
                    return override
        except Exception:  # noqa: BLE001
            pass
        return self.config_factory.get_vcs_repository_url()

    def _server_profile(self):
        getter = getattr(self.config_factory, "get_vcs_server_profile", None)
        return getter() if callable(getter) else None

    @classmethod
    def _is_junk(cls, relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/")
        if any(part == "__pycache__" for part in normalized.split("/")):
            return True

        name = normalized.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(name, pattern) for pattern in JUNK_GLOBS):
            return True
        return any(regex.search(name) for regex in JUNK_REGEXES)

    @staticmethod
    def _status_entries(adapter):
        """Use structured status when the adapter supports it."""
        getter = getattr(adapter, "get_status_entries", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:  # noqa: BLE001 - fall back to the legacy text scan
            return None

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------
    def scan_local_changes(self, project_root: Path) -> List[FileChange]:
        """Return the committable files that differ from the VCS server.

        ``.blend`` files are listed first so the artist's main work file is at
        the top of the checklist, followed by the rest alphabetically.
        """
        if not self.is_vcs_enabled():
            return []

        adapter = self._build_adapter(project_root)
        if adapter is None:
            return []

        changes = []
        entries = self._status_entries(adapter)
        if entries is not None:
            for entry in entries:
                if self._is_junk(entry.path):
                    continue
                change = FileChange(
                    relative_path=entry.path,
                    status=status_code(entry),
                    tree_conflicted=entry.tree_conflicted,
                    property_conflicted=entry.props == "conflicted",
                )
                if change.is_changed:
                    changes.append(change)
        else:
            status = adapter.get_status()
            for path, state in status.items():
                if self._is_junk(path):
                    continue
                change = FileChange(relative_path=path, status=state)
                if change.is_changed:
                    changes.append(change)
        changes.sort(
            key=lambda change: (
                not change.relative_path.lower().endswith(".blend"),
                change.relative_path.lower(),
            )
        )
        return changes

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update_working_copy(
        self,
        project_root: Path,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Pull the latest changes, returning only success and a message."""
        report = self.update_working_copy_detailed(project_root, username, password)
        return report.ok, report.message

    def update_working_copy_detailed(
        self,
        project_root: Path,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> VcsUpdateReport:
        """Pull the latest changes and report conflicts/obstructions."""
        if not self.is_vcs_enabled(project_root):
            return VcsUpdateReport(False, "Version Control is disabled for this project.")

        try:
            adapter = self._build_adapter(project_root)
        except Exception as error:  # noqa: BLE001
            return VcsUpdateReport(False, f"Could not initialize the VCS adapter: {error}")
        if adapter is None:
            return VcsUpdateReport(False, "VCS enabled but no adapter is available.")

        try:
            adapter.full_pull(username, password)
            ok = True
            message = "Workspace updated from the VCS."
        except Exception as error:  # noqa: BLE001
            ok = False
            message = str(error)

        issues = tuple(self.collect_update_issues(project_root))
        if ok and issues:
            ok = False
            message = (
                "The update left conflicts or obstructed paths that must be handled "
                "before the workspace is clean."
            )
        return VcsUpdateReport(ok, message, issues)

    def collect_update_issues(self, project_root: Path) -> List[FileChange]:
        """Return conflicts and obstructions currently present in the workspace."""
        try:
            adapter = self._build_adapter(project_root)
        except Exception:  # noqa: BLE001
            return []
        if adapter is None:
            return []

        entries = self._status_entries(adapter)
        if entries is None:
            return []

        issues: list[FileChange] = []
        seen: set[str] = set()
        for entry in entries:
            code = status_code(entry)
            if code not in ("C", "~", "B") and not entry.is_conflicted and entry.item != "obstructed":
                continue
            if entry.path in seen:
                continue
            seen.add(entry.path)
            issues.append(
                FileChange(
                    relative_path=entry.path,
                    status=code,
                    tree_conflicted=entry.tree_conflicted,
                    property_conflicted=entry.props == "conflicted",
                )
            )
        return issues

    def move_path_aside(self, project_root: Path, relative_path: str) -> Tuple[bool, str]:
        """Move an obstructing path out of the workspace so the update can proceed."""
        if not relative_path:
            return False, "Select a path to move aside."
        workspace = self.workspace_root(project_root)
        try:
            source = (workspace / relative_path).resolve()
            source.relative_to(workspace.resolve())
        except (OSError, ValueError):
            return False, "The selected path is outside the project workspace."
        if not source.exists():
            return False, "The selected path no longer exists."

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = workspace / ".openstudio_aside" / stamp / relative_path
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        except OSError as error:
            return False, f"Could not move the path aside: {error}"

        self.add_local_ignore(project_root, ".openstudio_aside")
        return True, f"Moved '{relative_path}' aside to '{destination}'."

    # ------------------------------------------------------------------
    # Local ignore list
    # ------------------------------------------------------------------
    def _local_ignore_file(self, project_root: Path) -> Path:
        local_name = getattr(self.config_factory, "get_vfs_local_name", lambda: "local")()
        return Path(project_root) / local_name / "vcs_local_ignores.json"

    def load_local_ignores(self, project_root: Path) -> List[str]:
        """Return the project-local ignore patterns for this machine."""
        path = self._local_ignore_file(project_root)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        patterns = data.get("patterns") if isinstance(data, dict) else data
        if not isinstance(patterns, list):
            return []
        return [str(pattern).strip() for pattern in patterns if str(pattern).strip()]

    def add_local_ignore(self, project_root: Path, pattern: str) -> Tuple[bool, str]:
        """Persist a local ignore pattern without touching the repository."""
        pattern = (pattern or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
        if not pattern:
            return False, "The ignore pattern is empty."
        path = self._local_ignore_file(project_root)
        patterns = self.load_local_ignores(project_root)
        if pattern not in patterns:
            patterns.append(pattern)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"patterns": patterns}, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError as error:
            return False, f"Could not save the local ignore: {error}"
        return True, f"Local ignore added for '{pattern}'."

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------
    def publish(
        self,
        project_root: Path,
        selected_paths: List[str],
        unversioned_paths: Optional[List[str]] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        message: str = "",
    ) -> Tuple[bool, str]:
        """Commit ``selected_paths``, adding the unversioned ones first."""
        if not selected_paths:
            return False, "No files selected for publishing."

        if not self.is_vcs_enabled():
            return False, "Version Control is disabled for this project."

        adapter = self._build_adapter(project_root)
        if adapter is None:
            return False, "VCS enabled but no adapter is available."

        unversioned = [path for path in (unversioned_paths or []) if path]
        if unversioned:
            adapter.add(unversioned)

        adapter.commit(message, list(selected_paths), username, password)
        return True, f"Published {len(selected_paths)} file(s) to the VCS."

    # ------------------------------------------------------------------
    # Conflict resolution
    # ------------------------------------------------------------------
    def resolve_conflict(
        self,
        project_root: Path,
        relative_path: str,
        strategy: str = "working",
    ) -> Tuple[bool, str]:
        """Resolve one conflicted path with ``working``, ``mine-full`` or ``theirs-full``."""
        if not self.is_vcs_enabled(project_root) or not relative_path:
            return False, "Conflict resolution is not available for this project."

        try:
            adapter = self._build_adapter(project_root)
        except Exception as error:  # noqa: BLE001
            return False, f"Could not initialize the VCS adapter: {error}"
        if adapter is None:
            return False, "VCS enabled but no adapter is available."

        resolver = getattr(adapter, "resolve", None)
        if not callable(resolver):
            return False, "This VCS adapter does not support conflict resolution."
        try:
            resolver(relative_path, strategy)
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to resolve the conflict: {error}"
        return True, "Conflict resolved."

    # ------------------------------------------------------------------
    # History / diff / restore
    # ------------------------------------------------------------------
    def get_file_history(
        self,
        project_root: Path,
        relative_path: str,
        limit: int = 20,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[dict]:
        """Return the most recent revisions that changed a task file."""
        if not self.is_vcs_enabled(project_root) or not relative_path:
            raise RuntimeError("Version Control is not available for this project.")
        adapter = self._build_adapter(project_root)
        if adapter is None:
            raise RuntimeError("VCS enabled but no adapter is available.")
        getter = getattr(adapter, "get_log", None)
        if not callable(getter):
            raise RuntimeError("This VCS adapter does not support history.")
        return list(getter(relative_path, limit, username, password) or [])

    def get_file_diff(
        self,
        project_root: Path,
        relative_path: str,
        revision: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> str:
        """Return the textual diff for a task file."""
        if not self.is_vcs_enabled(project_root) or not relative_path:
            raise RuntimeError("Version Control is not available for this project.")
        adapter = self._build_adapter(project_root)
        if adapter is None:
            raise RuntimeError("VCS enabled but no adapter is available.")
        getter = getattr(adapter, "get_diff", None)
        if not callable(getter):
            raise RuntimeError("This VCS adapter does not support diffs.")
        return str(getter(relative_path, revision, username, password) or "")

    def export_file_revision(
        self,
        project_root: Path,
        relative_path: str,
        revision: int,
        destination: Path,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Export a historical revision to a file without touching the workspace."""
        if not self.is_vcs_enabled(project_root) or not relative_path:
            return False, "Version Control is not available for this project."
        try:
            adapter = self._build_adapter(project_root)
        except Exception as error:  # noqa: BLE001
            return False, f"Could not initialize the VCS adapter: {error}"
        if adapter is None:
            return False, "VCS enabled but no adapter is available."
        exporter = getattr(adapter, "export_revision", None)
        if not callable(exporter):
            return False, "This VCS adapter does not support exporting revisions."
        try:
            exporter(relative_path, revision, Path(destination), username, password)
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to export the revision: {error}"
        return True, f"Revision {revision} exported to {destination}."

    # ------------------------------------------------------------------
    # Locking (svn:needs-lock workflow)
    # ------------------------------------------------------------------
    def get_task_file_lock(
        self,
        project_root: Path,
        relative_path: str,
    ) -> Optional[dict]:
        """Return the VCS lock metadata for a task file, or ``None`` when unlocked.

        Read-only counterpart of :meth:`lock_task_file`, used to render the lock
        badge on the artist task cards without acquiring anything. Lock metadata
        comes straight from the working copy (``svn info``), so no credentials
        are required.
        """
        if not self.is_vcs_enabled(project_root) or not relative_path:
            return None

        try:
            adapter = self._build_adapter(project_root)
        except Exception:  # noqa: BLE001
            return None
        if adapter is None:
            return None

        try:
            info = adapter.get_lock_info(relative_path)
        except Exception:  # noqa: BLE001
            return None
        return info or None

    def lock_task_file(
        self,
        project_root: Path,
        relative_path: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Acquire the VCS write lock for a task file before opening it.

        Locking is fail-closed: if the adapter or the lock cannot be acquired,
        the caller must not launch the DCC without a lock. The only non-fatal
        case is a lock already owned by the same user, which is reported as a
        success so a session can resume after a crash.
        """
        if not self.is_vcs_enabled() or not relative_path:
            return True, "Locking skipped (VCS disabled or no file)."

        try:
            adapter = self._build_adapter(project_root)
        except Exception as error:  # noqa: BLE001
            return False, f"Could not initialize the VCS adapter: {error}"
        if adapter is None:
            return False, "VCS enabled but no adapter is available."

        try:
            info = adapter.get_lock_info(relative_path)
        except Exception:  # noqa: BLE001
            info = None

        if info and info.get("owner"):
            owner = str(info["owner"])
            if username and owner != username:
                return False, f"File is locked by '{owner}'."
            if not self._is_workspace_file_writable(project_root, relative_path):
                return (
                    False,
                    "File is locked by you but is read-only. "
                    "Release the stale lock from the task card and try again.",
                )
            return True, f"Already locked by '{owner}'."

        try:
            adapter.lock(relative_path, username, password)
        except SvnAlreadyLockedError as error:
            owner = error.owner
            if owner and username and owner == username:
                if not self._is_workspace_file_writable(project_root, relative_path):
                    return (
                        False,
                        "File is locked by you but is read-only. "
                        "Release the stale lock from the task card and try again.",
                    )
                return True, f"Already locked by '{owner}'."
            if owner:
                return False, f"File is locked by '{owner}'."
            return False, "File is already locked."
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to lock file: {error}"
        return True, "File locked for editing."

    def unlock_task_file(
        self,
        project_root: Path,
        relative_path: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        force: bool = False,
    ) -> Tuple[bool, str]:
        """Release the task file lock after the work has been synced.

        ``force`` is used by the explicit "Release my lock" / "Break lock"
        actions when the working copy no longer holds the lock token.
        """
        if not self.is_vcs_enabled() or not relative_path:
            return True, "Unlock skipped (VCS disabled or no file)."

        try:
            adapter = self._build_adapter(project_root)
        except Exception as error:  # noqa: BLE001
            return False, f"Could not initialize the VCS adapter: {error}"
        if adapter is None:
            return False, "VCS enabled but no adapter is available."

        try:
            adapter.unlock(relative_path, username, password, force=force)
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to unlock file: {error}"
        return True, "File unlocked."

    def _is_workspace_file_writable(self, project_root: Path, relative_path: str) -> bool:
        """Check whether a task file is currently writable on disk."""
        candidate = self.workspace_root(project_root) / relative_path
        if not candidate.exists():
            return True
        return os.access(candidate, os.W_OK)
