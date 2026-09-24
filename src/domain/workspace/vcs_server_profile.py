# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/workspace/vcs_server_profile.py
# Architectural role: Workspace value object (VCS server topology)
# =========================================================================================

"""Where the studio VCS server lives and how to administer it.

Two modes are supported:

* ``local_docker`` — the developer sandbox SVN container (``openstudio_local_svn``).
* ``remote_ssh`` — a production VPS reached over the tailnet, administered through
  OpenSSH (project repository create/delete only; the svnserve daemon is assumed
  to already be running).

Only the ``remote`` configuration is persisted in ``settings.json``; the SSH
passphrase is a RAM-only credential owned by ``CredentialVault``.
"""

from dataclasses import dataclass, field
from typing import Any, Dict

LOCAL_DOCKER = "local_docker"
REMOTE_SSH = "remote_ssh"

VALID_MODES = (LOCAL_DOCKER, REMOTE_SSH)

DEFAULT_STRICT_HOST_KEY = "accept-new"


@dataclass(frozen=True)
class RemoteSSHConfig:
    """Connection + server layout for a remote SVN server.

    ``password_db`` is the value written verbatim into each repository's
    ``conf/svnserve.conf`` as ``password-db``. When empty, the Hub derives
    ``<repo_root>/passwd`` (a studio-wide account database that is assumed to
    already exist on the server). It is a path, never a secret.

    ``container`` is the name of the Docker container that runs ``svnserve`` and
    holds ``svnadmin``/``svn``. All server administration is executed through
    ``docker exec`` inside it; it is mandatory when the mode is ``remote_ssh``.
    """

    host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_key_path: str = ""
    ssh_cert_path: str = ""
    known_hosts_path: str = ""
    container: str = ""
    container_user: str = ""
    repo_root: str = "/srv/svn"
    strict_host_key: str = DEFAULT_STRICT_HOST_KEY
    password_db: str = ""
    realm: str = "OpenStudio"

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "RemoteSSHConfig":
        data = data or {}

        port_raw = data.get("ssh_port", 22)
        try:
            ssh_port = int(port_raw)
        except (TypeError, ValueError):
            ssh_port = 22

        return cls(
            host=(data.get("host") or "").strip(),
            ssh_port=ssh_port,
            ssh_user=(data.get("ssh_user") or "").strip(),
            ssh_key_path=(data.get("ssh_key_path") or "").strip(),
            ssh_cert_path=(data.get("ssh_cert_path") or "").strip(),
            known_hosts_path=(data.get("known_hosts_path") or "").strip(),
            container=(data.get("container") or "").strip(),
            container_user=(data.get("container_user") or "").strip(),
            repo_root=(data.get("repo_root") or "/srv/svn").strip() or "/srv/svn",
            strict_host_key=(data.get("strict_host_key") or DEFAULT_STRICT_HOST_KEY).strip(),
            password_db=(data.get("password_db") or "").strip(),
            realm=(data.get("realm") or "OpenStudio").strip() or "OpenStudio",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "ssh_port": self.ssh_port,
            "ssh_user": self.ssh_user,
            "ssh_key_path": self.ssh_key_path,
            "ssh_cert_path": self.ssh_cert_path,
            "known_hosts_path": self.known_hosts_path,
            "container": self.container,
            "container_user": self.container_user,
            "repo_root": self.repo_root,
            "strict_host_key": self.strict_host_key,
            "password_db": self.password_db,
            "realm": self.realm,
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.ssh_user and self.container)

    def effective_password_db(self) -> str:
        """Explicit ``password-db`` value, or ``<repo_root>/passwd`` by default."""
        if self.password_db:
            return self.password_db
        return f"{self.repo_root.rstrip('/')}/passwd"


@dataclass(frozen=True)
class VCSServerProfile:
    """Selected VCS server mode plus its admin coordinates."""

    mode: str = LOCAL_DOCKER
    remote: RemoteSSHConfig = field(default_factory=RemoteSSHConfig)
    local_container: str = "openstudio_local_svn"
    local_repo_root: str = "/home/svn"

    @property
    def is_remote(self) -> bool:
        return self.mode == REMOTE_SSH

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "VCSServerProfile":
        data = data or {}
        mode = (data.get("mode") or LOCAL_DOCKER).strip().lower()
        if mode not in VALID_MODES:
            mode = LOCAL_DOCKER
        return cls(
            mode=mode,
            remote=RemoteSSHConfig.from_dict(data.get("remote")),
            local_container=(data.get("local_container") or "openstudio_local_svn").strip()
            or "openstudio_local_svn",
            local_repo_root=(data.get("local_repo_root") or "/home/svn").strip() or "/home/svn",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "remote": self.remote.to_dict(),
            "local_container": self.local_container,
            "local_repo_root": self.local_repo_root,
        }
