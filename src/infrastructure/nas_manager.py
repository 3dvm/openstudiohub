# =========================================================================================
# OPENSTUDIOHUB
# Module: core/nas_manager.py
# Architectural Role: File System Manager / NAS Orchestrator
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. All rights reserved.
# License: GNU General Public License v3.0 (GPLv3)
#
# Author: Ernesto Del Valle Macuare
# File version: 1.0.0 (Genesis)
# =========================================================================================

"""
Centralized manager for read and write operations on the NAS server (Local/Network).
Isolates the UI from disk checks, directory searches,
manifest reading (Blueprints) and destructive operations.
"""

import json
import shutil
from pathlib import Path
from typing import Optional, Dict

class NasManager:
    def __init__(self, base_dir: Path = None, config_factory=None):
        """
        Initializes the manager with the root path of the local or network storage (NAS).

        When a ``config_factory`` is provided the base directory is resolved
        dynamically on every access, so it always reflects the latest workspace
        root (e.g. after a studio seed is imported). Otherwise the given
        ``base_dir`` is used as a fixed snapshot (backwards compatibility).
        """
        self._base_dir_snapshot = Path(base_dir) if base_dir else None
        self._config_factory = config_factory

    @property
    def base_dir(self) -> Optional[Path]:
        if self._config_factory is not None:
            return self._config_factory.get_workspace_root()
        return self._base_dir_snapshot

    def is_connected(self) -> bool:
        """Verifies if the root path is configured and accessible."""
        return self.base_dir is not None and self.base_dir.exists()

    def resolve_project_dir(self, project_name: str, project_code: str = "") -> Optional[Path]:
        """
        Attempts to resolve the project's physical path using its name or code.
        """

        print(f"[NasManager] resolve_project_dir base_dir={self.base_dir} project_name='{project_name}' code='{project_code}'")


        if not self.is_connected():
            return None

        # 1. Search for exact match (Raw name)
        target_dir = self.base_dir / project_name
        if target_dir.exists():
            return target_dir

        # 2. Search for normalized version (Dashes instead of spaces, lowercase)
        clean_name = project_name.strip().lower().replace(" ", "-") if project_name else "unknown"
        target_dir_clean = self.base_dir / clean_name
        if target_dir_clean.exists():
            return target_dir_clean

        # 3. Fallback to Kitsu short code
        if project_code:
            target_dir_code = self.base_dir / project_code
            if target_dir_code.exists():
                return target_dir_code

        return None

    def get_project_blueprint(self, project_dir: Path) -> Dict:
        """
        Dynamically searches for the project_init.json file within the project
        folder (regardless of the internal VFS name) and returns its metadata.
        """
        if not project_dir or not project_dir.exists():
            return {}

        try:
            # Search one level deep using glob
            meta_files = list(project_dir.glob("*/project_init.json"))

            print(f"[NasManager] Blueprint candidates for {project_dir}: {meta_files}")

            if meta_files:
                with open(meta_files[0], "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"[NasManager] Error reading blueprint at {project_dir}: {e}")

        return {}

    def get_project_blueprint_path(self, project_dir: Path) -> Optional[Path]:
        """Return the path to ``project_init.json``, or ``None`` when absent."""
        if not project_dir or not project_dir.exists():
            return None

        meta_files = list(project_dir.glob("*/project_init.json"))
        return meta_files[0] if meta_files else None

    def load_project_blueprint(self, project_dir: Path) -> tuple[str, Optional[Dict]]:
        """
        Load the blueprint distinguishing its three possible states:

        * ``"missing"`` — the ``project_init.json`` file does not exist.
        * ``"invalid"`` — the file exists but is not valid JSON.
        * ``"ok"`` — the file exists and parses as JSON (schema still unvalidated).

        Returns ``(status, data)`` where ``data`` is ``None`` unless status is ``"ok"``.
        """
        path = self.get_project_blueprint_path(project_dir)
        if path is None:
            return "missing", None

        print(f"[NasManager] Blueprint candidate for {project_dir}: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                return "ok", json.load(f)
        except Exception as e:
            print(f"[NasManager] Error reading blueprint at {path}: {e}")
            return "invalid", None

    def delete_project_folder(self, project_dir: Path) -> bool:
        """
        Recursively destroys the project directory on the local disk/NAS.
        """
        if not project_dir or not project_dir.exists():
            return False

        try:
            shutil.rmtree(project_dir, ignore_errors=True)
            print(f"[NasManager] Local directory successfully destroyed: {project_dir}")
            return True
        except Exception as e:
            print(f"[NasManager] Error destroying directory {project_dir}: {e}")
            return False
