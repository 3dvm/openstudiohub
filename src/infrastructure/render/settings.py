# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/settings.py
# Architectural role: Render infrastructure / shared project render settings
# =========================================================================================

"""Persist the render panel settings inside the project's pipeline folder."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from src.domain.render.models import RenderSettings

SETTINGS_FILENAME = "render_settings.json"


class RenderSettingsStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> RenderSettings:
        try:
            if not self.path.exists():
                return RenderSettings()
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return RenderSettings()
        return RenderSettings.from_dict(data if isinstance(data, dict) else {})

    def save(self, settings: RenderSettings) -> None:
        payload = json.dumps(settings.to_dict(), indent=2, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(payload + "\n", encoding="utf-8")
            temporary.replace(self.path)
