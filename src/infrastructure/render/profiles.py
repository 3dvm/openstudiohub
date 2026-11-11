# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/profiles.py
# Architectural role: Render infrastructure / measured render profiles
# =========================================================================================

"""Persist per-shot, per-GPU render measurements.

A profile is the measured seconds-per-frame for one blend hash, quality target
and GPU profile. The store is a small JSON file inside the project's pipeline
folder so every workstation shares the same calibration.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROFILES_FILENAME = "render_profiles.json"


class RenderProfileStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = self._read()

    def _read(self) -> dict:
        try:
            if not self.path.exists():
                return {"shots": {}}
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"shots": {}}
        if not isinstance(data, dict):
            return {"shots": {}}
        data.setdefault("shots", {})
        return data

    @property
    def shots(self) -> dict:
        return self._data.setdefault("shots", {})

    def entry(
        self,
        relative_path: str,
        gpu_profile: str,
        quality_key: str,
        *,
        blend_hash: str = "",
    ) -> dict | None:
        """Return the stored measurement entry, including its metadata."""
        with self._lock:
            entry = self.shots.get(relative_path) or {}
            if blend_hash and entry.get("blend_hash") and entry["blend_hash"] != blend_hash:
                return None
            profile = (entry.get("profiles") or {}).get(f"{gpu_profile}|{quality_key}")
        if not isinstance(profile, dict):
            return None
        try:
            seconds = float(profile.get("seconds"))
        except (TypeError, ValueError):
            return None
        if seconds <= 0:
            return None
        return {
            "seconds": seconds,
            "gpu": str(profile.get("gpu") or gpu_profile),
            "measured_at": str(profile.get("measured_at") or ""),
            "gpu_profile": gpu_profile,
        }

    def get(
        self,
        relative_path: str,
        gpu_profile: str,
        quality_key: str,
        *,
        blend_hash: str = "",
    ) -> float | None:
        entry = self.entry(
            relative_path,
            gpu_profile,
            quality_key,
            blend_hash=blend_hash,
        )
        return float(entry["seconds"]) if entry is not None else None

    def set(
        self,
        relative_path: str,
        gpu_profile: str,
        quality_key: str,
        seconds: float,
        *,
        blend_hash: str = "",
        gpu_label: str = "",
    ) -> None:
        if seconds <= 0:
            return
        with self._lock:
            entry = self.shots.setdefault(relative_path, {})
            if blend_hash:
                entry["blend_hash"] = blend_hash
            entry.setdefault("profiles", {})[f"{gpu_profile}|{quality_key}"] = {
                "seconds": round(float(seconds), 3),
                "gpu": gpu_label or gpu_profile,
                "measured_at": datetime.now(timezone.utc).isoformat(),
            }

    def save(self) -> None:
        with self._lock:
            payload = json.dumps(self._data, indent=2, ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))
