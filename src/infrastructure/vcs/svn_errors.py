# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/vcs/svn_errors.py
# Architectural role: VCS infrastructure / typed Subversion errors
# =========================================================================================

"""Typed errors raised by the Subversion client layer.

The raw ``svn`` CLI reports failures through exit codes and messages that carry
stable ``E``/``W`` codes. This module centralizes the translation from that
text into exceptions the application layer can branch on without parsing
messages itself.
"""

from __future__ import annotations

import re
from typing import Iterable

_ERROR_CODE_RE = re.compile(r"\b([EW]\d{6})\b")
_PATH_RE = re.compile(r"Path '([^']+)'")
_OWNER_PATTERNS = (
    re.compile(r"already locked by user ['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"already locked by user (\S+)", re.IGNORECASE),
    re.compile(r"locked by user ['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"locked by user (\S+)", re.IGNORECASE),
)

# Codes that describe the same remediation, grouped by intent.
_AUTH_CODES = frozenset({"E170001", "E215004", "E175013", "E170013"})
_NETWORK_CODES = frozenset({"E175002", "E730054", "E210002", "E670008", "E000111"})
_WC_LOCKED_CODES = frozenset({"E155004", "E155037"})
_OUT_OF_DATE_CODES = frozenset({"E160028", "E155011", "E195020"})
_ALREADY_LOCKED_CODES = frozenset({"E160039", "W160035"})
_NEEDS_LOCK_CODES = frozenset({"E200009", "E155005"})
_CONFLICT_CODES = frozenset({"E155015", "E155024"})
_NOT_WORKING_COPY_CODES = frozenset({"E155007", "E155010", "E155021"})
_PATH_NOT_FOUND_CODES = frozenset({"E160013", "E155010", "E200009"})


class VcsError(RuntimeError):
    """Base error for every VCS operation."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        raw: str = "",
        command: Iterable[str] = (),
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.raw = raw or message
        self.command = tuple(command or ())

    def __str__(self) -> str:
        return self.message


class SvnCommandError(VcsError):
    """Generic ``svn`` failure that has no more specific classification."""


class SvnAuthError(SvnCommandError):
    """Authentication or authorization failure."""


class SvnNetworkError(SvnCommandError):
    """Transport failure (server unreachable, connection reset, ...)."""


class SvnWorkingCopyLockedError(SvnCommandError):
    """The local working copy is locked and needs ``svn cleanup``."""


class SvnOutOfDateError(SvnCommandError):
    """The commit or update target is out of date."""


class SvnNeedsLockError(SvnCommandError):
    """The file requires a lock before it can be modified."""


class SvnConflictError(SvnCommandError):
    """The operation produced or encountered a conflict."""


class SvnNotWorkingCopyError(SvnCommandError):
    """The target path is not a Subversion working copy."""


class SvnPathNotFoundError(SvnCommandError):
    """A path or repository item does not exist."""


class SvnAlreadyLockedError(SvnCommandError):
    """The path is already locked, optionally by a known user."""

    def __init__(
        self,
        message: str,
        *,
        owner: str = "",
        path: str = "",
        code: str = "",
        raw: str = "",
        command: Iterable[str] = (),
    ) -> None:
        super().__init__(message, code=code, raw=raw, command=command)
        self.owner = owner
        self.path = path


def extract_error_code(stderr: str) -> str:
    """Return the first ``E``/``W`` code found in ``stderr``, if any."""
    match = _ERROR_CODE_RE.search(stderr or "")
    return match.group(1) if match else ""


def extract_lock_owner(stderr: str) -> str:
    """Parse the lock owner from an SVN ``already locked`` message."""
    text = stderr or ""
    for pattern in _OWNER_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return ""


def extract_path(stderr: str) -> str:
    """Parse the first ``Path '...'`` fragment from an SVN message."""
    match = _PATH_RE.search(stderr or "")
    return match.group(1) if match else ""


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def classify_svn_error(
    stderr: str,
    returncode: int = 1,
    command: Iterable[str] = (),
) -> VcsError:
    """Translate an ``svn`` failure into the most specific :class:`VcsError`."""
    raw = stderr or ""
    code = extract_error_code(raw)
    message = _first_line(raw) or f"svn exited with code {returncode}."
    common = {"code": code, "raw": raw, "command": tuple(command or ())}

    # "Already locked" is often emitted as a W160035 warning followed by a
    # generic E200009 failure. Prefer the specific code wherever it appears.
    already_locked = next(
        (candidate for candidate in ("W160035", "E160039") if candidate in raw),
        "",
    )
    if already_locked:
        common["code"] = already_locked
        return SvnAlreadyLockedError(
            message,
            owner=extract_lock_owner(raw),
            path=extract_path(raw),
            **common,
        )
    if code in _AUTH_CODES:
        return SvnAuthError(message, **common)
    if code in _NETWORK_CODES:
        return SvnNetworkError(message, **common)
    if code in _WC_LOCKED_CODES:
        return SvnWorkingCopyLockedError(message, **common)
    if code in _OUT_OF_DATE_CODES:
        return SvnOutOfDateError(message, **common)
    if code in _NEEDS_LOCK_CODES:
        return SvnNeedsLockError(message, **common)
    if code in _CONFLICT_CODES:
        return SvnConflictError(message, **common)
    if code in _NOT_WORKING_COPY_CODES:
        return SvnNotWorkingCopyError(message, **common)
    if code in _PATH_NOT_FOUND_CODES:
        return SvnPathNotFoundError(message, **common)
    return SvnCommandError(message, **common)
