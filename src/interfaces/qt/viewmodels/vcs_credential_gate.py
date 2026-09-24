# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/vcs_credential_gate.py
# Architectural role: MVVM helper / VCS credentials guard
# =========================================================================================

"""Shared guard that ensures VCS credentials exist before a VCS-backed action.

Credentials are stored **per server** in the RAM-only ``CredentialVault``. The
flow is intentionally UI-agnostic: the ViewModels receive a ``prompt`` callable
(implemented by the shell, which owns the modal dialog) and this module decides
*when* it has to be shown.
"""

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

VcsCredentials = Tuple[str, str]


@dataclass
class VcsPromptResult:
    """Values collected by the credentials prompt."""

    username: str
    password: str
    ssh_passphrase: str = ""


# (server_id, server_label, needs_ssh_passphrase) -> collected values or None
VcsPrompt = Callable[[str, str, bool], Optional[VcsPromptResult]]
ReportStatus = Callable[[str, str], None]


def vcs_requires_credentials(config_factory, server=None) -> bool:
    """True when the active VCS engine needs authenticated access.

    When a resolved ``server`` is provided its adapter decides; otherwise the
    studio default server is used.
    """
    if server is not None:
        adapter = (getattr(server, "adapter", "") or "").strip().lower()
        return adapter not in ("none", "")
    if config_factory is None:
        return False
    adapter = (config_factory.get_vcs_adapter_type() or "").strip().lower()
    return adapter not in ("none", "")


def needs_ssh_passphrase(server) -> bool:
    return bool(server is not None and getattr(server, "is_remote", False))


def ensure_vcs_credentials(
    required: bool,
    server_id: str,
    server_label: str,
    needs_passphrase: bool,
    credential_vault,
    prompt: Optional[VcsPrompt],
    report_status: ReportStatus,
) -> Optional[VcsCredentials]:
    """Return ``(username, password)`` when the action may proceed.

    * ``required=False`` -> ``("", "")`` (no VCS, nothing to collect).
    * Credentials already in the vault for ``server_id`` -> returned as-is.
    * Otherwise -> invokes ``prompt(server_id, server_label, needs_passphrase)``;
      on accept the pair (and optional SSH passphrase) is saved for that server.
    """
    if not required:
        return ("", "")

    if credential_vault is not None and server_id:
        user, pwd = credential_vault.get_server_credentials(server_id)
        if user and pwd:
            return (user, pwd)

    if prompt is None:
        report_status("VCS credentials are required to continue. Configure them in Settings.", "red")
        return None

    collected = prompt(server_id, server_label, needs_passphrase)
    if not collected:
        report_status("Operation cancelled: VCS credentials are required.", "red")
        return None

    user, pwd = collected.username, collected.password
    if not (user and pwd):
        report_status("Operation cancelled: VCS credentials are required.", "red")
        return None

    if credential_vault is not None and server_id:
        credential_vault.save_server_credentials(
            server_id,
            user,
            pwd,
            enabled=True,
            ssh_passphrase=collected.ssh_passphrase or None,
        )

    return (user, pwd)
