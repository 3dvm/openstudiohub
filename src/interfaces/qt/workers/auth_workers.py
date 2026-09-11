# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/workers/auth_workers.py
# Architectural role: Thin QThread adapters for authentication use cases
# =========================================================================================

"""Authentication workers.

They only invoke ``AuthService`` and re-emit the result as Qt signals so the
LoginViewModel never blocks the GUI thread.
"""

from PySide6.QtCore import QThread, Signal

from src.application.services.auth_service import AuthService


class LoginWorker(QThread):
    """Asynchronously performs the login use case."""

    success = Signal()
    error = Signal(str)

    def __init__(self, auth_service: AuthService, email: str, password: str, host: str) -> None:
        super().__init__()
        self.auth_service = auth_service
        self.email = email
        self.password = password
        self.host = host

    def run(self) -> None:
        ok, message = self.auth_service.login(self.email, self.password, self.host)
        if ok:
            self.success.emit()
        else:
            self.error.emit(message)
