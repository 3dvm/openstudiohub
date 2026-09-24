# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/credential_vault.py
# Architectural role: Application / volatile (RAM-only) credential vault
# =========================================================================================

"""Volatile credential vault for Just-In-Time injection into DCC subprocesses.

This replaces the credential half of the old ``VaultManager`` (which also mixed
in software-inventory manifest CRUD). Credentials are kept strictly in RAM and
injected into the OS environment; nothing is written to disk.

VCS credentials are stored **per server** (keyed by ``VCSServer.id``) because a
studio can operate several version-control backends at once.
"""

import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from src.domain.shared_kernel.env_contract import EnvKey


@dataclass
class ServerCredentials:
    """RAM-only credentials bound to a single VCS server."""

    username: str = ""
    password: str = ""
    enabled: bool = False
    ssh_passphrase: str = ""


class CredentialVault:
    def __init__(self) -> None:
        self._kitsu_email: Optional[str] = None
        self._kitsu_password: Optional[str] = None
        self._vcs: Dict[str, ServerCredentials] = {}

    # ------------------------------------------------------------------
    # Kitsu
    # ------------------------------------------------------------------
    def save_kitsu_credentials(self, email: str, password: str) -> None:
        self._kitsu_email = email
        self._kitsu_password = password
        os.environ[EnvKey.KITSU_USER] = email
        os.environ[EnvKey.KITSU_PWD] = password

    def get_kitsu_credentials(self) -> Tuple[Optional[str], Optional[str]]:
        return self._kitsu_email, self._kitsu_password

    # ------------------------------------------------------------------
    # VCS (per server)
    # ------------------------------------------------------------------
    def _entry(self, server_id: str) -> ServerCredentials:
        return self._vcs.setdefault(server_id, ServerCredentials())

    def save_server_credentials(
        self,
        server_id: str,
        username: str,
        password: str,
        enabled: bool = True,
        ssh_passphrase: Optional[str] = None,
    ) -> None:
        entry = self._entry(server_id)
        entry.username = username or ""
        entry.password = password or ""
        entry.enabled = enabled
        if ssh_passphrase is not None:
            entry.ssh_passphrase = ssh_passphrase or ""

    def get_server_credentials(self, server_id: str) -> Tuple[Optional[str], Optional[str]]:
        entry = self._vcs.get(server_id)
        if entry is None:
            return None, None
        return entry.username or None, entry.password or None

    def has_server_credentials(self, server_id: str) -> bool:
        user, pwd = self.get_server_credentials(server_id)
        return bool(user and pwd)

    def set_server_enabled(self, server_id: str, enabled: bool) -> None:
        self._entry(server_id).enabled = enabled

    def is_server_enabled(self, server_id: str) -> bool:
        entry = self._vcs.get(server_id)
        return bool(entry and entry.enabled)

    def save_ssh_passphrase(self, server_id: str, passphrase: str) -> None:
        self._entry(server_id).ssh_passphrase = passphrase or ""

    def get_ssh_passphrase(self, server_id: str) -> Optional[str]:
        entry = self._vcs.get(server_id)
        return (entry.ssh_passphrase or None) if entry else None

    def has_ssh_passphrase(self, server_id: str) -> bool:
        return bool(self.get_ssh_passphrase(server_id))

    def clear_server(self, server_id: str) -> None:
        self._vcs.pop(server_id, None)

    def export_server_env(self, server_id: str) -> None:
        """Expose a server's credentials to the OS environment (DCC subprocesses)."""
        user, pwd = self.get_server_credentials(server_id)
        os.environ[EnvKey.SVN_USER] = user or ""
        os.environ[EnvKey.SVN_PASSWORD] = pwd or ""

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------
    def clear(self) -> None:
        self._kitsu_email = None
        self._kitsu_password = None
        self._vcs.clear()
        for key in (
            EnvKey.KITSU_USER,
            EnvKey.KITSU_PWD,
            EnvKey.SVN_USER,
            EnvKey.SVN_PASSWORD,
        ):
            os.environ.pop(key, None)
        print("[CredentialVault] Transient credentials flushed.")
