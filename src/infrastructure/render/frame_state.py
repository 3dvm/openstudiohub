# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/frame_state.py
# Architectural role: Render infrastructure / per-shot frame approvals
# =========================================================================================

"""Persist which rendered frames are approved and must not be overwritten."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

STATE_FILENAME = ".frame_state.json"


class RenderFrameStateStore:
    """Small sidecar next to a shot's rendered frames."""

    def __init__(self, shot_dir: Path | str) -> None:
        self.shot_dir = Path(shot_dir)
        self.path = self.shot_dir / STATE_FILENAME
        self._lock = threading.Lock()

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def approved_frames(self) -> set[int]:
        approved = self.read().get("approved")
        if not isinstance(approved, dict):
            return set()
        frames: set[int] = set()
        for key in approved:
            try:
                frames.add(int(key))
            except (TypeError, ValueError):
                continue
        return frames

    def is_approved(self, frame: int) -> bool:
        return int(frame) in self.approved_frames()

    def approve(self, frame: int, user: str = "") -> None:
        self._update(frame, approved=True, user=user)

    def unapprove(self, frame: int) -> None:
        self._update(frame, approved=False, user="")

    def set_approved(self, frames, approved: bool, user: str = "") -> None:
        """Approve or unlock several frames with a single atomic write."""
        frames = {int(frame) for frame in frames or ()}
        if not frames:
            return
        with self._lock:
            data = self.read()
            entries = data.get("approved")
            if not isinstance(entries, dict):
                entries = {}
            for frame in frames:
                if approved:
                    entries[str(frame)] = {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "by": str(user or ""),
                    }
                else:
                    entries.pop(str(frame), None)
            data["approved"] = entries
            self.shot_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)

    def _update(self, frame: int, *, approved: bool, user: str) -> None:
        frame = int(frame)
        with self._lock:
            data = self.read()
            entries = data.get("approved")
            if not isinstance(entries, dict):
                entries = {}
            if approved:
                entries[str(frame)] = {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "by": str(user or ""),
                }
            else:
                entries.pop(str(frame), None)
            data["approved"] = entries
            self.shot_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
