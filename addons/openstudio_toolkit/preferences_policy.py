"""Pure policy helpers for per-project Blender preference values."""

from pathlib import Path

UNDO_STEPS = 256
SAVE_VERSIONS = 0


def local_root_from_resources(blender_user_resources: str) -> Path | None:
    """Return ``<project>/<vfs_local>`` from ``BLENDER_USER_RESOURCES``."""
    value = str(blender_user_resources or "").strip()
    if not value:
        return None
    # BLENDER_USER_RESOURCES points at <vfs_local>/blender_data.
    return Path(value).resolve().parent


def temporary_directory(blender_user_resources: str) -> Path | None:
    root = local_root_from_resources(blender_user_resources)
    return (root / "blender-tmp") if root is not None else None


def vcs_is_enabled(adapter: str) -> bool:
    return str(adapter or "").strip().lower() not in ("", "none")
