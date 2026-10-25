# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/vcs/vcs_audit.py
# Architectural role: VCS infrastructure / operation audit trail
# =========================================================================================

"""Append-only audit trail for version-control operations.

The log is JSON Lines so it can be inspected with standard tools and consumed
later by a diagnostics view. Secrets are never written: passwords travel over
stdin and any defensive ``--password`` token is redacted.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from src.infrastructure.json_state import default_state_dir

_PASSWORD_FLAGS = {"--password", "--passphrase"}
_SECRET_VALUE_RE = re.compile(r"(--(?:password|passphrase)[= ])(\S+)", re.IGNORECASE)


class VcsAuditLogger:
    """Best-effort, thread-safe JSON Lines audit logger."""

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        max_bytes: int = 5 * 1024 * 1024,
        backups: int = 3,
    ) -> None:
        self.path = Path(path) if path is not None else default_state_dir() / "vcs_audit.jsonl"
        self.max_bytes = int(max_bytes)
        self.backups = max(1, int(backups))
        self._lock = threading.Lock()

    def log(
        self,
        operation: str,
        *,
        project: str = "",
        server: str = "",
        user: str = "",
        paths: Iterable[str] = (),
        cwd: str = "",
        ok: bool = True,
        returncode: int = 0,
        error_code: str = "",
        revision: str = "",
        duration_ms: int = 0,
        message: str = "",
        command: Iterable[str] = (),
    ) -> bool:
        """Append one audit event. Returns ``False`` when logging is unavailable."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": str(operation or ""),
            "project": str(project or ""),
            "server": str(server or ""),
            "user": str(user or ""),
            "paths": [str(path) for path in paths or ()],
            "cwd": str(cwd or ""),
            "ok": bool(ok),
            "returncode": int(returncode or 0),
            "error_code": str(error_code or ""),
            "revision": str(revision or ""),
            "duration_ms": int(duration_ms or 0),
            "message": self._redact_message(str(message or ""))[:2000],
            "command": list(self.redact_command(tuple(str(part) for part in command or ()))),
        }
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed()
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            return True
        except OSError:
            return False

    def read_recent(self, limit: int = 200) -> list[dict]:
        """Return the most recent audit events (best effort)."""
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events: list[dict] = []
        for line in lines[-max(1, int(limit)) :]:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    @staticmethod
    def redact_command(command: Iterable[str]) -> tuple[str, ...]:
        """Mask values that follow a secret-bearing option."""
        redacted: list[str] = []
        hide_next = False
        for token in command or ():
            if hide_next:
                redacted.append("***")
                hide_next = False
                continue
            redacted.append(str(token))
            if str(token) in _PASSWORD_FLAGS:
                hide_next = True
        return tuple(redacted)

    @staticmethod
    def _redact_message(message: str) -> str:
        return _SECRET_VALUE_RE.sub(r"\1***", message or "")

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
