# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/blender/empty_master_provider.py
# Architectural role: Infrastructure / cached empty .blend master
# =========================================================================================

"""Provides a cached, empty ``.blend`` master for fast task-file creation.

Creating an empty file from Blender's factory startup once and copying it is
orders of magnitude faster than launching Blender per file. The master lives in
the project's ``vfs_pipeline`` folder (already ignored by VCS) and is generated
on first use with the project's isolated Blender binary.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from src.infrastructure.sandbox.blender_locator import BlenderLocator

StatusCallback = Callable[[str, str], None]


class EmptyMasterProvider:
    MASTER_NAME = "empty_master.blend"

    def __init__(self, config_factory) -> None:
        self.config_factory = config_factory

    def master_path(self, project_root: Path) -> Path:
        return Path(project_root) / self.config_factory.get_vfs_pipeline_name() / self.MASTER_NAME

    def ensure(self, project_root: Path, status_callback: Optional[StatusCallback] = None) -> Path:
        """Return the cached empty master, generating it once when missing."""
        master = self.master_path(project_root)
        if master.exists():
            return master

        build_dir = Path(project_root) / self.config_factory.get_vfs_local_name() / "blender-build"
        blender_bin = BlenderLocator.resolve(build_dir)

        master.parent.mkdir(parents=True, exist_ok=True)
        if status_callback:
            status_callback("Forging empty master .blend (one-time)...", "yellow")

        script = (
            "import bpy; "
            "bpy.ops.wm.read_factory_settings(use_empty=True); "
            f"bpy.ops.wm.save_as_mainfile(filepath={str(master)!r})"
        )
        result = subprocess.run(
            [str(blender_bin), "--background", "--factory-startup", "--python-expr", script],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not master.exists():
            raise RuntimeError(
                f"Failed to generate empty master: {result.stdout[-500:]}{result.stderr[-500:]}"
            )
        return master

    def copy_into(self, project_root: Path, destination: Path, status_callback: Optional[StatusCallback] = None) -> Path:
        """Materialize the empty master at ``destination`` (creating parents)."""
        master = self.ensure(project_root, status_callback=status_callback)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(master, destination)
        return destination
