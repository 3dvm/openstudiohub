# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/vcs/svn_client.py
# Architectural role: VCS infrastructure / client discovery and provisioning
# =========================================================================================

"""Locate and validate the ``svn`` command-line client.

The Hub requires Subversion 1.14 or newer. This module owns the search order
(configured path, bundled sidecar, ``PATH``), the version gate and the manual
provisioning message used by the initial setup wizard.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

MINIMUM_SVN_VERSION = (1, 14)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")

MANUAL_INSTALL_MESSAGE = (
    "Subversion 1.14 or newer is required. Install it manually and run the "
    "Initial Configuration again."
)


@dataclass(frozen=True)
class SvnClientStatus:
    """Result of probing the local Subversion client."""

    found: bool
    path: str = ""
    version: tuple[int, ...] = ()
    version_text: str = ""
    meets_minimum: bool = False
    message: str = ""

    @property
    def version_label(self) -> str:
        return self.version_text or "unknown"


def parse_version(text: str) -> tuple[int, ...]:
    """Parse ``1.14.5`` (or ``svn, version 1.14.5``) into a tuple."""
    match = _VERSION_RE.search(text or "")
    if not match:
        return ()
    parts = [int(match.group(1)), int(match.group(2))]
    if match.group(3) is not None:
        parts.append(int(match.group(3)))
    return tuple(parts)


def platform_key() -> str:
    """Return the platform folder used by a bundled SVN client."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def _svn_executable_name() -> str:
    return "svn.exe" if os.name == "nt" else "svn"


def bundled_candidates(app_root: Optional[Path] = None) -> list[Path]:
    """Return candidate paths for a Hub-managed SVN client."""
    root = Path(app_root) if app_root is not None else Path(__file__).resolve().parents[3]
    tools = root / "tools" / "svn"
    candidates = [
        tools / platform_key() / _svn_executable_name(),
        tools / platform_key() / "bin" / _svn_executable_name(),
    ]
    return candidates


def detect_svn_client(
    configured_path: str = "",
    *,
    minimum: Iterable[int] = MINIMUM_SVN_VERSION,
    timeout: float = 5.0,
    app_root: Optional[Path] = None,
) -> SvnClientStatus:
    """Find ``svn`` and verify that it meets the minimum version."""
    minimum_tuple = tuple(int(part) for part in minimum)
    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    candidates.extend(bundled_candidates(app_root))

    found_on_path = shutil.which("svn")
    if found_on_path:
        candidates.append(Path(found_on_path))

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen or not candidate.exists():
            continue
        seen.add(key)
        status = _probe(candidate, minimum_tuple, timeout)
        if status.found:
            return status

    return SvnClientStatus(
        found=False,
        meets_minimum=False,
        message=MANUAL_INSTALL_MESSAGE,
    )


def _probe(path: Path, minimum: tuple[int, ...], timeout: float) -> SvnClientStatus:
    try:
        result = subprocess.run(
            [str(path), "--version", "--quiet"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return SvnClientStatus(
            found=False,
            path=str(path),
            message=MANUAL_INSTALL_MESSAGE,
        )

    if result.returncode != 0:
        return SvnClientStatus(
            found=False,
            path=str(path),
            message=MANUAL_INSTALL_MESSAGE,
        )

    version_text = (result.stdout or "").strip().splitlines()[0] if result.stdout else ""
    version = parse_version(version_text)
    meets_minimum = bool(version) and version >= minimum
    if meets_minimum:
        message = f"Subversion {version_text} found at {path}."
    else:
        message = (
            f"Subversion {version_text or 'unknown'} at {path} is older than "
            f"{'.'.join(str(part) for part in minimum)}."
        )
    return SvnClientStatus(
        found=True,
        path=str(path),
        version=version,
        version_text=version_text,
        meets_minimum=meets_minimum,
        message=message,
    )


class SvnClientProvisioner:
    """Provisioning strategies offered by the initial setup wizard.

    The manual strategy is always available. The bundled strategy is reserved
    for a future signed manifest; until then it reports that automatic
    provisioning is not available.
    """

    def manual_message(self) -> str:
        return MANUAL_INSTALL_MESSAGE

    def download_available(self) -> bool:
        return False

    def download_and_install(
        self,
        *,
        destination_root: Optional[Path] = None,
        progress=None,
    ) -> tuple[bool, str]:
        return False, MANUAL_INSTALL_MESSAGE
