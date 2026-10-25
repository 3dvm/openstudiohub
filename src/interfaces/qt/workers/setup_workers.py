# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/setup_workers.py
# Architectural role: UI workers / initial setup probes
# =========================================================================================

"""Background probes used by the initial setup wizard."""

from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker
from src.infrastructure.vcs.svn_client import detect_svn_client


class DetectSvnClientWorker(ManagedWorker):
    """Detect the local ``svn`` client without blocking the UI thread."""

    finished_check = Signal(object)  # SvnClientStatus

    def __init__(self, configured_path: str = "") -> None:
        super().__init__()
        self.configured_path = configured_path

    def run(self) -> None:
        status = detect_svn_client(self.configured_path)
        self.finished_check.emit(status)
