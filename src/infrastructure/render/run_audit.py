# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/run_audit.py
# Architectural role: Render infrastructure / local run audit trail
# =========================================================================================

"""Append-only audit trail for render runs.

The Hub already keeps a VCS audit log. Render runs need the same treatment:
when a node disappears, the operator must be able to see which stage failed,
which instance was involved and what the remote output looked like.

The summary is JSON Lines (easy to rotate and inspect); the full per-node
output lives next to it under ``render_runs/<run_id>/``. Secrets are never
written.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.infrastructure.json_state import default_state_dir


class RenderRunAuditLogger:
    """Best-effort, thread-safe audit logger for render runs."""

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        max_bytes: int = 5 * 1024 * 1024,
        backups: int = 3,
    ) -> None:
        base = default_state_dir()
        self.path = Path(path) if path is not None else base / "render_runs.jsonl"
        self.root = self.path.parent / "render_runs"
        self.max_bytes = int(max_bytes)
        self.backups = max(1, int(backups))
        self._lock = threading.Lock()

    def log(self, event: str, *, run_id: str = "", **fields) -> bool:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": str(event or ""),
            "run_id": str(run_id or ""),
        }
        for key, value in fields.items():
            if value is None:
                continue
            payload[str(key)] = value
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed()
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            return True
        except OSError:
            return False

    def node_log_path(self, run_id: str, node: int | str) -> Path:
        return self.run_dir(run_id) / f"node-{_safe_label(node)}.log"

    def blender_log_path(
        self,
        run_id: str,
        node: int | str,
        label: str = "",
    ) -> Path:
        suffix = f"-{_safe_label(label)}" if str(label or "").strip() else ""
        return self.run_dir(run_id) / f"node-{_safe_label(node)}-blender{suffix}.log"

    def node_event(self, event: str, *, run_id: str, node: int | str, **fields) -> bool:
        """Write a structured event and a human line to the node's own log."""
        ok = self.log(event, run_id=run_id, node=node, **fields)
        message = str(fields.get("message") or "").strip()
        detail = " ".join(
            f"{key}={value}"
            for key, value in fields.items()
            if key not in ("message",) and value not in (None, "")
        )
        line = f"{event}: {message}".rstrip(": ")
        if detail:
            line = f"{line} | {detail}"
        self.append_node_log(run_id, node, line)
        return ok

    def append_node_log(self, run_id: str, node: int | str, line: str) -> Path | None:
        try:
            path = self.node_log_path(run_id, node)
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            with self._lock:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(f"[{stamp}] {str(line).rstrip()}\n")
            return path
        except OSError:
            return None

    def node_summary(self, run_id: str, node: int | str, data: dict) -> Path | None:
        try:
            path = self.run_dir(run_id) / f"node-{_safe_label(node)}.json"
            with self._lock:
                path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            return path
        except (OSError, ValueError):
            return None

    def append_blender_output(self, path: Path | str, line: str) -> None:
        try:
            with self._lock:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(str(line).rstrip() + "\n")
        except OSError:
            pass

    def run_dir(self, run_id: str) -> Path:
        folder = self.root / str(run_id or "unknown")
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def write_node_log(self, run_id: str, node: int, text: str) -> Path | None:
        if not str(text or "").strip():
            return None
        try:
            path = self.run_dir(run_id) / f"node-{int(node)}.log"
            with self._lock:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(str(text).rstrip() + "\n")
            return path
        except (OSError, ValueError):
            return None

    def write_summary(self, run_id: str, data: dict) -> Path | None:
        try:
            path = self.run_dir(run_id) / "summary.json"
            with self._lock:
                path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            return path
        except (OSError, ValueError):
            return None

    def read_recent(self, limit: int = 200) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events: list[dict] = []
        for line in lines[-max(1, int(limit)):]:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    def _rotate_if_needed(self) -> None:
        try:
            if not self.path.exists() or self.path.stat().st_size < self.max_bytes:
                return
        except OSError:
            return
        for index in range(self.backups - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            destination = self.path.with_name(f"{self.path.name}.{index + 1}")
            if source.exists():
                try:
                    source.replace(destination)
                except OSError:
                    return
        try:
            self.path.replace(self.path.with_name(f"{self.path.name}.1"))
        except OSError:
            pass


def _safe_label(value) -> str:
    text = str(value or "unknown").strip().replace(" ", "-")
    return "".join(ch for ch in text if ch.isalnum() or ch in "-_.") or "unknown"
