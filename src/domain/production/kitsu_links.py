# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/production/kitsu_links.py
# Architectural role: Production domain helpers (Kitsu web links)
# =========================================================================================

"""Build Kitsu web-app URLs from production data.

The Kitsu task page route is ``/productions/{project}/{type}/tasks/{task}``
where ``type`` is the plural of the task's entity type (``shots``,
``sequences``, ``assets``, ``edits``). Building it from ``entity_type_name``
avoids hard-coding ``shots`` for every task.
"""

from typing import Dict

_ENTITY_SEGMENTS: Dict[str, str] = {
    "shot": "shots",
    "sequence": "sequences",
    "asset": "assets",
    "edit": "edits",
    "scene": "scenes",
}


def kitsu_base_url(api_url: str) -> str:
    """Return the Kitsu web root from the configured API URL."""
    base = (api_url or "").strip().rstrip("/")
    if base.endswith("/api"):
        base = base[:-4]
    return base.rstrip("/")


def task_kitsu_path(task: dict) -> str:
    """Relative Kitsu web path for a task (empty when IDs are missing)."""
    task = task or {}
    project_id = str(
        task.get("project_id") or (task.get("project") or {}).get("id") or ""
    )
    task_id = str(task.get("id") or "")
    if not project_id or not task_id:
        return ""

    entity_type = str(
        task.get("entity_type_name") or task.get("entity_type") or "Asset"
    ).strip().lower()
    if entity_type == "episode" and task.get("episode_id"):
        return (
            f"/productions/{project_id}/episodes/{task['episode_id']}"
            f"/tasks/{task_id}"
        )
    segment = _ENTITY_SEGMENTS.get(entity_type, "assets")
    return f"/productions/{project_id}/{segment}/tasks/{task_id}"


def task_kitsu_url(api_url: str, task: dict) -> str:
    """Absolute Kitsu web URL for a task (empty when it cannot be built)."""
    base = kitsu_base_url(api_url)
    path = task_kitsu_path(task)
    if not base or not path:
        return ""
    return f"{base}{path}"
