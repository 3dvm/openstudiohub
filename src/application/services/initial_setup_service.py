# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/initial_setup_service.py
# Architectural role: Application service / machine initial setup
# =========================================================================================

"""Verify and apply the machine-local configuration required by the Hub.

The initial setup wizard covers three machine-specific requirements:

* a Studio Seed (studio/Kitsu/VCS settings),
* a Subversion client that satisfies the minimum version,
* the local projects folder for this machine.

The service is deliberately UI-free so the startup check and the wizard share
exactly the same rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.infrastructure.vcs.svn_client import (
    MANUAL_INSTALL_MESSAGE,
    SvnClientStatus,
    detect_svn_client,
)


@dataclass(frozen=True)
class InitialSetupStatus:
    """Snapshot of the machine-local setup state."""

    has_studio_seed: bool
    has_projects_root: bool
    svn_required: bool
    svn: SvnClientStatus
    needs_setup: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SeedPreview:
    """Validated Studio Seed payload plus the fields shown by the wizard."""

    payload: dict
    studio_name: str
    kitsu_url: str
    vcs_servers: int
    topography: dict
    svn_required: bool


class InitialSetupService:
    def __init__(self, config_factory, svn_detector=detect_svn_client) -> None:
        self.config_factory = config_factory
        self._svn_detector = svn_detector

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def status(self) -> InitialSetupStatus:
        has_seed = self._has_studio_seed()
        has_projects_root = self._has_projects_root()
        svn_required = self._svn_required_for_config()
        configured_svn = self._configured_svn_path()
        svn_status = self._svn_detector(configured_svn) if svn_required else SvnClientStatus(
            found=True,
            message="Subversion is not required by the current configuration.",
        )

        reasons: list[str] = []
        if not has_seed:
            reasons.append("The Studio Seed is not configured.")
        if not has_projects_root:
            reasons.append("The projects folder is not configured for this machine.")
        if svn_required and not svn_status.meets_minimum:
            reasons.append(svn_status.message or MANUAL_INSTALL_MESSAGE)

        return InitialSetupStatus(
            has_studio_seed=has_seed,
            has_projects_root=has_projects_root,
            svn_required=svn_required,
            svn=svn_status,
            needs_setup=bool(reasons),
            reasons=tuple(reasons),
        )

    def _has_studio_seed(self) -> bool:
        try:
            return bool((self.config_factory.get_kitsu_api_url() or "").strip())
        except Exception:  # noqa: BLE001
            return False

    def _has_projects_root(self) -> bool:
        getter = getattr(self.config_factory, "has_local_workspace_root", None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:  # noqa: BLE001
                return False
        return False

    def _configured_svn_path(self) -> str:
        getter = getattr(self.config_factory, "get_svn_cli_path", None)
        if callable(getter):
            try:
                return str(getter() or "")
            except Exception:  # noqa: BLE001
                return ""
        return ""

    def _svn_required_for_config(self) -> bool:
        registry = self._registry()
        if registry is not None and getattr(registry, "servers", None):
            return any(
                bool(getattr(server, "is_enabled", False))
                and str(getattr(server, "adapter", "")).lower() == "svn"
                for server in registry.servers
            )
        raw = self._raw_vcs_config()
        return str(raw.get("active_adapter") or "none").lower() == "svn"

    def _registry(self):
        getter = getattr(self.config_factory, "get_vcs_servers", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:  # noqa: BLE001
            return None

    def _raw_vcs_config(self) -> dict:
        getter = getattr(self.config_factory, "get_raw_config", None)
        if not callable(getter):
            return {}
        try:
            return (getter() or {}).get("vcs_engine", {}) or {}
        except Exception:  # noqa: BLE001
            return {}

    # ------------------------------------------------------------------
    # Seed preview
    # ------------------------------------------------------------------
    def read_seed(self, seed_path: Path) -> tuple[bool, Optional[SeedPreview], str]:
        reader = getattr(self.config_factory, "read_seed_payload", None)
        if not callable(reader):
            return False, None, "Studio Seed validation is not available."
        ok, payload, error = reader(seed_path)
        if not ok or payload is None:
            return False, None, error or "The Studio Seed could not be read."

        vcs = payload.get("vcs_engine") or {}
        servers = vcs.get("servers") or []
        svn_required = self.svn_required_for_payload(payload)
        preview = SeedPreview(
            payload=payload,
            studio_name=str((payload.get("studio_profile") or {}).get("name") or ""),
            kitsu_url=str((payload.get("kitsu_production") or {}).get("api_url") or ""),
            vcs_servers=len(servers),
            topography=dict(payload.get("project_topography") or {}),
            svn_required=svn_required,
        )
        return True, preview, ""

    @staticmethod
    def svn_required_for_payload(payload: dict) -> bool:
        vcs = (payload or {}).get("vcs_engine") or {}
        servers = vcs.get("servers") or []
        if servers:
            return any(
                str((server or {}).get("adapter") or "svn").lower() == "svn"
                for server in servers
            )
        return str(vcs.get("active_adapter") or "none").lower() == "svn"

    # ------------------------------------------------------------------
    # Projects folder
    # ------------------------------------------------------------------
    @staticmethod
    def validate_projects_dir(path: Path) -> tuple[bool, str]:
        """Check that ``path`` is a writable directory (creating it is optional)."""
        try:
            candidate = Path(path).expanduser()
        except Exception:  # noqa: BLE001
            return False, "Select a valid projects folder."
        if not str(candidate).strip():
            return False, "Select the projects folder for this machine."
        if not candidate.exists():
            return False, "The selected projects folder does not exist."
        if not candidate.is_dir():
            return False, "The selected path is not a folder."
        if not _is_writable(candidate):
            return False, "The selected projects folder is not writable."
        return True, ""

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    def apply_existing(
        self,
        projects_dir: Path,
        svn_cli_path: str = "",
    ) -> tuple[bool, str]:
        """Repair the machine-local paths when the seed is already applied."""
        valid, message = self.validate_projects_dir(projects_dir)
        if not valid:
            return False, message

        status = self.status()
        if status.svn_required:
            svn_status = self._svn_detector(str(svn_cli_path or ""))
            if not svn_status.meets_minimum:
                return False, svn_status.message or MANUAL_INSTALL_MESSAGE
            svn_cli_path = svn_status.path

        applier = getattr(self.config_factory, "apply_local_paths", None)
        if not callable(applier):
            return False, "Initial setup is not available."
        if not applier(Path(projects_dir), str(svn_cli_path or "")):
            return False, "The initial configuration could not be saved."
        return True, "Initial configuration applied successfully."

    def apply(
        self,
        seed_path: Path,
        projects_dir: Path,
        svn_cli_path: str = "",
    ) -> tuple[bool, str]:
        valid, message = self.validate_projects_dir(projects_dir)
        if not valid:
            return False, message

        ok, preview, error = self.read_seed(seed_path)
        if not ok or preview is None:
            return False, error or "The Studio Seed could not be read."

        if preview.svn_required:
            status = self._svn_detector(str(svn_cli_path or ""))
            if not status.meets_minimum:
                return False, status.message or MANUAL_INSTALL_MESSAGE
            svn_cli_path = status.path

        applier = getattr(self.config_factory, "apply_initial_setup", None)
        if not callable(applier):
            return False, "Initial setup is not available."
        ok, message = applier(seed_path, Path(projects_dir), str(svn_cli_path or ""))
        if not ok:
            return False, message or "The initial configuration could not be saved."
        return True, "Initial configuration applied successfully."


def _is_writable(path: Path) -> bool:
    probe = path / ".openstudio_write_test"
    try:
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False
