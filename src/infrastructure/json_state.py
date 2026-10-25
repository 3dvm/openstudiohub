# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/json_state.py
# Architectural role: Infrastructure / small atomic JSON state files
# =========================================================================================

"""Helpers for the small per-user JSON state files stored under ``~/.openstudio``."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict


def default_state_dir() -> Path:
    """Directory for user-local UI/read state (overridable for tests)."""
    override = os.environ.get("OPENSTUDIO_STATE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".openstudio" / "state"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Write ``data`` to ``path`` atomically (temp file + ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
