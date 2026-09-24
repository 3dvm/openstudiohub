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
import re
from pathlib import Path
from typing import List, Optional, Tuple

from src.domain.production.value_objects import FileChange
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
        return router.get_adapter()

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

        status = adapter.get_status()

        changes = []
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
        """Pull the latest changes from the VCS into the project workspace.

        Runs ``svn update`` (or ``git pull``) on ``<project_root>/<vfs>`` so the
        artist works against the team's latest revision. Authentication uses the
        per-server username/password only; SSH is reserved for server-side
        repository administration.
        """
        if not self.is_vcs_enabled(project_root):
            return False, "Version Control is disabled for this project."

        try:
            adapter = self._build_adapter(project_root)
        except Exception as error:  # noqa: BLE001
            return False, f"Could not initialize the VCS adapter: {error}"
        if adapter is None:
            return False, "VCS enabled but no adapter is available."

        try:
            adapter.full_pull(username, password)
        except Exception as error:  # noqa: BLE001
            return False, str(error)
        return True, "Workspace updated from the VCS."

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
    # Locking (svn:needs-lock workflow)
    # ------------------------------------------------------------------
    def lock_task_file(
        self,
        project_root: Path,
        relative_path: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Acquire the VCS write lock for a task file before opening it."""
        if not self.is_vcs_enabled() or not relative_path:
            return True, "Locking skipped (VCS disabled or no file)."

        try:
            adapter = self._build_adapter(project_root)
        except Exception as error:  # noqa: BLE001
            return True, f"Locking skipped ({error})."
        if adapter is None:
            return True, "Locking skipped (no adapter)."

        try:
            info = adapter.get_lock_info(relative_path)
        except Exception:  # noqa: BLE001
            info = None

        if info and info.get("owner"):
            if username and info["owner"] != username:
                return False, f"File is locked by '{info['owner']}'."
            return True, f"Already locked by '{info['owner']}'."

        try:
            adapter.lock(relative_path, username, password)
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to lock file: {error}"
        return True, "File locked for editing."

    def unlock_task_file(
        self,
        project_root: Path,
        relative_path: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Release the task file lock after the work has been synced."""
        if not self.is_vcs_enabled() or not relative_path:
            return True, "Unlock skipped (VCS disabled or no file)."

        try:
            adapter = self._build_adapter(project_root)
        except Exception as error:  # noqa: BLE001
            return True, f"Unlock skipped ({error})."
        if adapter is None:
            return True, "Unlock skipped (no adapter)."

        try:
            adapter.unlock(relative_path, username, password)
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to unlock file: {error}"
        return True, "File unlocked."
