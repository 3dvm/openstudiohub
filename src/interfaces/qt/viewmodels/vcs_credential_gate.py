# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/vcs_credential_gate.py
# Architectural role: MVVM helper / VCS credentials guard
# =========================================================================================

"""Shared guard that ensures VCS credentials exist before a VCS-backed action.

The flow is intentionally UI-agnostic: the ViewModels receive a ``prompt``
callable (implemented by the shell, which owns the modal dialog) and this module
decides *when* it has to be shown. Once collected, credentials are stored with
the exact same API used by the Session Credentials settings tab
(``CredentialVault.save_svn_credentials``), so they remain RAM-only.
"""

from typing import Callable, Optional, Tuple

VcsCredentials = Tuple[str, str]
VcsPrompt = Callable[[], Optional[VcsCredentials]]
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


def ensure_vcs_credentials(
    required: bool,
    credential_vault,
    prompt: Optional[VcsPrompt],
    report_status: ReportStatus,
) -> Optional[VcsCredentials]:
    """Return ``(username, password)`` when the action may proceed.

    * ``required=False`` -> ``("", "")`` (no VCS, nothing to collect).
    * Credentials already in the vault -> returned as-is.
    * Otherwise -> invokes ``prompt()``; on accept the pair is saved to the vault
      and returned, on cancel/empty it reports the failure and returns ``None``.
    """
    if not required:
        return ("", "")

    if credential_vault is not None:
        user, pwd = credential_vault.get_svn_credentials()
        if user and pwd:
            return (user, pwd)

    if prompt is None:
        report_status("VCS credentials are required to continue. Configure them in Settings.", "red")
        return None

    collected = prompt()
    if not collected:
        report_status("Operation cancelled: VCS credentials are required.", "red")
        return None

    user, pwd = collected
    if not (user and pwd):
        report_status("Operation cancelled: VCS credentials are required.", "red")
        return None

    if credential_vault is not None:
        credential_vault.save_svn_credentials(user, pwd, enabled=True)

    return (user, pwd)
