# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/credential_vault.py
# Architectural role: Application / volatile (RAM-only) credential vault
# =========================================================================================

"""Volatile credential vault for Just-In-Time injection into DCC subprocesses.

This replaces the credential half of the old ``VaultManager`` (which also mixed
in software-inventory manifest CRUD). Credentials are kept strictly in RAM and
injected into the OS environment; nothing is written to disk.
"""

import os
from typing import Optional, Tuple

from src.domain.shared_kernel.env_contract import EnvKey


class CredentialVault:
    def __init__(self) -> None:
        self._kitsu_email: Optional[str] = None
        self._kitsu_password: Optional[str] = None
        self._svn_user: Optional[str] = None
        self._svn_password: Optional[str] = None

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
    # SVN / VCS
    # ------------------------------------------------------------------
    def save_svn_credentials(self, username: str, password: str) -> None:
        self._svn_user = username
        self._svn_password = password
        os.environ[EnvKey.SVN_USER] = username
        os.environ[EnvKey.SVN_PASSWORD] = password

    def get_svn_credentials(self) -> Tuple[Optional[str], Optional[str]]:
        return self._svn_user, self._svn_password

    def has_svn_credentials(self) -> bool:
        return bool(self._svn_user and self._svn_password)

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------
    def clear(self) -> None:
        self._kitsu_email = None
        self._kitsu_password = None
        self._svn_user = None
        self._svn_password = None
        for key in (
            EnvKey.KITSU_USER,
            EnvKey.KITSU_PWD,
            EnvKey.SVN_USER,
            EnvKey.SVN_PASSWORD,
        ):
            os.environ.pop(key, None)
        print("[CredentialVault] Transient credentials flushed.")
