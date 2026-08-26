# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/session_repository.py
# Architectural role: Infrastructure / File-backed SessionRepository
# =========================================================================================

"""File-backed ``SessionRepository`` (persists ~/.openstudio/session.json)."""

import json
from pathlib import Path
from typing import Optional

from src.application.ports import SessionRepository
from src.domain.identity.entities import Session

OPENSTUDIO_CONFIG_DIR = Path.home() / ".openstudio"
SESSION_FILE = OPENSTUDIO_CONFIG_DIR / "session.json"


class FileSessionRepository(SessionRepository):
    def __init__(self, session_file: Path = SESSION_FILE) -> None:
        self.session_file = session_file

    def load(self) -> Optional[Session]:
        if not self.session_file.exists():
            return None
        try:
            with open(self.session_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return Session(host=data.get("host", ""), tokens=data.get("tokens", {}))
        except Exception:  # noqa: BLE001 - corrupt session is treated as absent
            self.delete()
            return None

    def save(self, session: Session) -> None:
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.session_file, "w", encoding="utf-8") as handle:
            json.dump({"host": session.host, "tokens": session.tokens}, handle)

    def delete(self) -> None:
        if self.session_file.exists():
            self.session_file.unlink()
