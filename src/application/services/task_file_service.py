# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/task_file_service.py
# Architectural role: Application service / task <-> physical file mapping
# =========================================================================================

"""Links Kitsu tasks to their physical Blender files.

The canonical link is stored in the task's Kitsu custom data under
``data.filepath`` (relative to the VCS root, POSIX separators). This service is
entity-agnostic: assets are the first consumer, but shots/sequences/edits can
reuse it unchanged.

It also materializes missing files quickly by copying a cached empty master
(see ``EmptyMasterProvider``) instead of launching Blender per file.
"""

from pathlib import Path
from typing import Optional

from src.domain.production.entities import TASK_FILE_PATH_KEY, Task
from src.infrastructure.blender.empty_master_provider import EmptyMasterProvider
from src.infrastructure.kitsu.production_repository import KitsuProductionRepository
from src.infrastructure.kitsu_manager import KitsuManager


class TaskFileService:
    def __init__(self, config_factory, repository=None, empty_master_provider=None) -> None:
        self.config_factory = config_factory
        self.repository = repository or KitsuProductionRepository(KitsuManager())
        self.empty_master = empty_master_provider or EmptyMasterProvider(config_factory)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    def suggest_relative_path(self, task: Task) -> str:
        """Best-effort default path derived from the studio NamingPolicy."""
        try:
            return str(task.workfile_path())
        except ValueError:
            return ""

    def resolve_physical(self, project_root: Path, relative_path: str) -> Path:
        return Path(project_root) / self.config_factory.get_vfs_svn_name() / relative_path

    @staticmethod
    def validate_relative_path(relative_path: str) -> Optional[str]:
        """Return an error message, or None when the path is acceptable."""
        if not relative_path or not relative_path.strip():
            return "File path cannot be empty."
        candidate = Path(relative_path.strip())
        if candidate.is_absolute():
            return "File path must be relative to the production folder."
        if ".." in candidate.parts:
            return "File path cannot escape the production folder."
        if candidate.suffix.lower() != ".blend":
            return "Only .blend files can be linked."
        return None

    # ------------------------------------------------------------------
    # Linking
    # ------------------------------------------------------------------
    def link(self, task: Task, relative_path: str) -> bool:
        error = self.validate_relative_path(relative_path)
        if error:
            raise ValueError(error)
        data = dict(task.data)
        data[TASK_FILE_PATH_KEY] = relative_path.strip()
        if not self.repository.update_task_data(task.id, data):
            raise RuntimeError(
                f"Kitsu did not accept the file link for task '{task.id}'. "
                "If this is a permissions error, the signed-in account needs the "
                "'manager' role on this project (or be a global admin). "
                "Check the application log for the server response."
            )
        return True

    def unlink(self, task: Task) -> bool:
        data = dict(task.data)
        data.pop(TASK_FILE_PATH_KEY, None)
        if not self.repository.update_task_data(task.id, data):
            raise RuntimeError(
                f"Kitsu did not accept removing the file link for task '{task.id}'. "
                "Check the application log for the server response."
            )
        return True

    # ------------------------------------------------------------------
    # Fast file creation
    # ------------------------------------------------------------------
    def create_empty_file(self, project_root: Path, relative_path: str, status_callback=None) -> Path:
        """Copy the cached empty master to the target path (no Blender launch)."""
        error = self.validate_relative_path(relative_path)
        if error:
            raise ValueError(error)
        destination = self.resolve_physical(project_root, relative_path)
        return self.empty_master.copy_into(project_root, destination, status_callback=status_callback)

    def link_and_create_empty(self, task: Task, project_root: Path, relative_path: str, status_callback=None) -> bool:
        """Create the empty file (if needed) and persist the task link."""
        destination = self.resolve_physical(project_root, relative_path)
        if not destination.exists():
            self.create_empty_file(project_root, relative_path, status_callback=status_callback)
        return self.link(task, relative_path)
