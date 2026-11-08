# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/comments.py
# Architectural role: Render infrastructure / local shot and frame comments
# =========================================================================================

"""Local comments attached to a shot or one of its rendered frames."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

COMMENTS_FILENAME = ".render_comments.json"


class RenderCommentStore:
    def __init__(self, shot_dir: Path | str) -> None:
        self.path = Path(shot_dir) / COMMENTS_FILENAME
        self._lock = threading.Lock()

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"shot": [], "frames": {}}
        if not isinstance(data, dict):
            return {"shot": [], "frames": {}}
        data.setdefault("shot", [])
        data.setdefault("frames", {})
        if not isinstance(data["shot"], list):
            data["shot"] = []
        if not isinstance(data["frames"], dict):
            data["frames"] = {}
        return data

    def add(self, text: str, *, frame: int | None = None, author: str = "") -> dict:
        text = str(text or "").strip()
        if not text:
            return self.read()
        entry = {
            "id": uuid.uuid4().hex,
            "author": str(author or ""),
            "text": text,
            "created": datetime.now(timezone.utc).isoformat(),
            "resolved": False,
        }
        with self._lock:
            data = self.read()
            if frame is None:
                data["shot"].append(entry)
            else:
                key = str(int(frame))
                data["frames"].setdefault(key, []).append(entry)
            self._write(data)
        return data

    def set_resolved(self, comment_id: str, resolved: bool) -> dict:
        with self._lock:
            data = self.read()
            for entry in self._iter_comments(data):
                if str(entry.get("id")) == str(comment_id):
                    entry["resolved"] = bool(resolved)
                    break
            self._write(data)
        return data

    def delete(self, comment_id: str) -> dict:
        with self._lock:
            data = self.read()
            data["shot"] = [
                entry for entry in data["shot"]
                if str(entry.get("id")) != str(comment_id)
            ]
            for key, entries in list(data["frames"].items()):
                data["frames"][key] = [
                    entry for entry in entries
                    if str(entry.get("id")) != str(comment_id)
                ]
                if not data["frames"][key]:
                    data["frames"].pop(key, None)
            self._write(data)
        return data

    @staticmethod
    def _iter_comments(data: dict):
        yield from data.get("shot", [])
        for entries in data.get("frames", {}).values():
            if isinstance(entries, list):
                yield from entries

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
