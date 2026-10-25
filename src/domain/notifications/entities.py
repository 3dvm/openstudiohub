# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/notifications/entities.py
# Architectural role: Domain / notification value object
# =========================================================================================

"""Notification value object used by the in-app notification center."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Notification:
    id: str
    kind: str
    severity: str
    title: str
    message: str
    timestamp: str
    read: bool = False
    project: str = ""
    paths: tuple[str, ...] = field(default_factory=tuple)
    target: str = ""
    error_code: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "timestamp": self.timestamp,
            "read": self.read,
            "project": self.project,
            "paths": list(self.paths),
            "target": self.target,
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Notification":
        paths = data.get("paths") or []
        if isinstance(paths, str):
            paths = [paths]
        return cls(
            id=str(data.get("id", "")),
            kind=str(data.get("kind", "system")),
            severity=str(data.get("severity", "info")),
            title=str(data.get("title", "")),
            message=str(data.get("message", "")),
            timestamp=str(data.get("timestamp", "")),
            read=bool(data.get("read", False)),
            project=str(data.get("project", "")),
            paths=tuple(str(path) for path in paths),
            target=str(data.get("target", "")),
            error_code=str(data.get("error_code", "")),
        )

    def with_read(self, read: bool = True) -> "Notification":
        return Notification(
            id=self.id,
            kind=self.kind,
            severity=self.severity,
            title=self.title,
            message=self.message,
            timestamp=self.timestamp,
            read=read,
            project=self.project,
            paths=self.paths,
            target=self.target,
            error_code=self.error_code,
        )

    def clipboard_text(self) -> str:
        """Return a plain-text representation suitable for the clipboard."""
        lines = [f"{self.timestamp} - {self.title}".strip(" -")]
        if self.project:
            lines.append(f"Project: {self.project}")
        if self.error_code:
            lines.append(f"Error code: {self.error_code}")
        if self.paths:
            lines.append("Paths:")
            lines.extend(f"- {path}" for path in self.paths)
        if self.message:
            lines.append(f"Message: {self.message}")
        return "\n".join(lines)

    @staticmethod
    def dedupe_paths(paths: Iterable[str]) -> tuple[str, ...]:
        seen: set[str] = set()
        result: list[str] = []
        for path in paths:
            text = str(path)
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return tuple(result)
