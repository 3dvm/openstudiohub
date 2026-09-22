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
    def is_vcs_enabled(self) -> bool:
        """True when the project is under version control (adapter != none)."""
        adapter = (self.config_factory.get_vcs_adapter_type() or "").strip().lower()
        return adapter not in ("", "none")

    def workspace_root(self, project_root: Path) -> Path:
        return Path(project_root) / self.config_factory.get_vfs_svn_name()

    def _build_adapter(self, project_root: Path):
        vcs_type = self.config_factory.get_vcs_adapter_type()
        base_repo_url = self.config_factory.get_vcs_repository_url()
        vfs_svn = self.config_factory.get_vfs_svn_name()
        workspace_root = self.workspace_root(project_root)
        final_repo_url = f"{base_repo_url}/{Path(project_root).name}/{vfs_svn}"

        router = self.router_factory(
            vcs_type=vcs_type,
            repo_url=final_repo_url,
            workspace_dir=workspace_root,
        )
        return router.get_adapter()

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
