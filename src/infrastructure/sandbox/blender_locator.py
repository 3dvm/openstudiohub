# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/sandbox/blender_locator.py
# Architectural role: Infrastructure / Blender binary locator
# =========================================================================================

"""Single Blender-binary locator (removes the copy-pasted discovery logic).

The OS detection + executable resolution was previously duplicated in
``env_launcher``, ``blender_spawners`` (x3) and ``project_card``.
"""

import glob
import platform
from pathlib import Path
from typing import Optional


class BlenderLocator:
    @staticmethod
    def current_os() -> str:
        system = platform.system().lower()
        if system == "windows":
            return "windows"
        if system == "darwin":
            return "macos"
        return "linux"

    @staticmethod
    def relative_executable(os_name: Optional[str] = None) -> str:
        os_name = os_name or BlenderLocator.current_os()
        if os_name == "windows":
            return "blender.exe"
        if os_name == "macos":
            return "Blender.app/Contents/MacOS/Blender"
        return "blender"

    @staticmethod
    def archive_folder_name(version: str, os_name: Optional[str] = None) -> str:
        os_name = os_name or BlenderLocator.current_os()
        return f"blender-{version}-{os_name}-x64"

    @staticmethod
    def resolve(build_dir: Path, version: Optional[str] = None) -> Path:
        """Resolve the Blender executable under a ``blender-build`` directory.

        If ``version`` is given, resolve the exact extracted folder; otherwise
        glob for the first matching executable (used by the headless spawners).
        """
        os_name = BlenderLocator.current_os()
        rel_exe = BlenderLocator.relative_executable(os_name)

        if version:
            candidate = build_dir / BlenderLocator.archive_folder_name(version, os_name) / rel_exe
            if not candidate.exists() and os_name == "macos":
                candidate = build_dir / BlenderLocator.archive_folder_name(version, os_name) / "Blender"
            if not candidate.exists():
                raise FileNotFoundError(f"Blender {version} not found in {build_dir}")
            return candidate

        pattern = f"**/{rel_exe}"
        candidates = glob.glob(str(build_dir / pattern), recursive=True)
        if not candidates:
            raise FileNotFoundError(f"Blender executable not found in {build_dir}")
        return Path(sorted(candidates)[0])
