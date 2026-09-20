# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/sandbox/blender_locator.py
# Architectural role: Infrastructure / Blender binary locator
# =========================================================================================

"""Single Blender-binary locator (removes the copy-pasted discovery logic).

The OS detection + executable resolution was previously duplicated in
``env_launcher``, ``blender_spawners`` (x3) and ``project_card``.
"""

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
        search for the executable inside an extracted ``blender-*`` archive
        folder (used by the headless spawners).

        The previous implementation globbed recursively for ``**/blender`` and
        picked ``sorted(...)[0]``. That matched unrelated paths shipped with the
        archive (e.g. ``5.2/scripts/addons_core/io_scene_gltf2/blender`` is a
        directory that sorts before the real binary), so spawning always failed.
        """
        os_name = BlenderLocator.current_os()
        rel_exe = BlenderLocator.relative_executable(os_name)
        build_dir = Path(build_dir)

        if version:
            root = build_dir / BlenderLocator.archive_folder_name(version, os_name)
            candidate = root / rel_exe
            if not candidate.exists() and os_name == "macos":
                candidate = root / "Blender"
            if not candidate.exists():
                raise FileNotFoundError(f"Blender {version} not found in {build_dir}")
            return candidate

        # Preferred layout: <build_dir>/blender-<version>-<os>-x64/<exe>.
        candidates = [path for path in build_dir.glob(f"blender-*/{rel_exe}") if path.is_file()]
        if not candidates:
            # Fallback for non-standard layouts: match the executable suffix.
            suffix_parts = Path(rel_exe).parts
            for path in build_dir.rglob(suffix_parts[-1]):
                if not path.is_file():
                    continue
                if tuple(path.parts[-len(suffix_parts):]) == suffix_parts:
                    candidates.append(path)

        if not candidates:
            raise FileNotFoundError(f"Blender executable not found in {build_dir}")

        # Shallowest match wins (archive root over nested copies).
        candidates.sort(key=lambda path: (len(path.parts), str(path)))
        return candidates[0]
