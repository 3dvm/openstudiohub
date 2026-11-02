# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/status.py
# Architectural role: Render infrastructure / shared render status
# =========================================================================================

"""Shared render status for read-only progress in other dashboards.

The TD/PM render panel writes ``03_render/.render_status.json``; artists read it
with a timer. The file is outside SVN and contains no secrets.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

STATUS_FILENAME = ".render_status.json"


class RenderStatusStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    @classmethod
    def for_project(cls, project_root: Path | str) -> "RenderStatusStore":
        return cls(Path(project_root) / "03_render" / STATUS_FILENAME)

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def write(self, data: dict) -> None:
        payload = dict(data or {})
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass
