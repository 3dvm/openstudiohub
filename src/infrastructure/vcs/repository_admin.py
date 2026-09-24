# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/vcs/repository_admin.py
# Architectural role: Infrastructure / server-side repository lifecycle
# =========================================================================================

"""Server-side project repository lifecycle (create / destroy).

Two strategies are provided:

* :class:`LocalDockerRepositoryAdmin` — the developer ``openstudio_local_svn``
  container (unchanged behaviour, lifted out of the SVN adapter).
* :class:`RemoteSSHRepositoryAdmin` — a production VPS administered through
  OpenSSH. Only per-project repositories are managed; the ``svnserve`` daemon is
  assumed to already be running on the server.

The SVN *client* adapter delegates to one of these based on the configured
:class:`VCSServerProfile`, so local and remote share a single interface.
"""

import re
import subprocess
from typing import Tuple

from src.domain.workspace.vcs_server_profile import (
    LOCAL_DOCKER,
    VCSServerProfile,
)
from src.infrastructure.dev_defaults import DEV_SVN_PASSWORD, DEV_SVN_USER
from src.infrastructure.vcs.ssh_runner import SshRunner

_REPO_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def normalize_repo_name(project_name: str) -> str:
    """Canonical repository directory name (must match the checkout URL segment)."""
    return (project_name or "").strip().lower().replace(" ", "-")


def validate_repo_name(repo_name: str) -> str:
    """Reject names that could escape or inject into the (remote) shell."""
    if not repo_name or not _REPO_NAME_RE.match(repo_name):
        raise ValueError(
            f"Invalid repository name '{repo_name}'. Use lowercase letters, digits, "
            "dots, dashes and underscores (must start alphanumeric)."
        )
    return repo_name


class RepositoryAdmin:
    """Interface implemented by the local and remote lifecycle strategies."""

    def create(self, repo_name: str, vfs_svn: str, initialize_topology: bool = True) -> bool:
        raise NotImplementedError

    def destroy(self, repo_name: str, vfs_svn: str) -> Tuple[bool, str]:
        raise NotImplementedError


class LocalDockerRepositoryAdmin(RepositoryAdmin):
    """Manages repositories inside the developer SVN Docker container."""

    def __init__(
        self,
        container: str = "openstudio_local_svn",
        repo_root: str = "/home/svn",
    ) -> None:
        self.container = container
        self.repo_root = repo_root

    def _repo_path(self, repo_name: str) -> str:
        return f"{self.repo_root}/{repo_name}"

    def create(self, repo_name: str, vfs_svn: str, initialize_topology: bool = True) -> bool:
        repo_name = validate_repo_name(normalize_repo_name(repo_name))
        repo_path = self._repo_path(repo_name)

        try:
            existing = subprocess.run(
                ["docker", "exec", self.container, "test", "-d", repo_path],
                check=False,
                capture_output=True,
            )
            if existing.returncode == 0:
                print(f"[LocalVCS] Repository '{repo_name}' already exists. Skipping creation.")
                return True

            subprocess.run(
                ["docker", "exec", self.container, "svnadmin", "create", repo_path],
                check=True,
                capture_output=True,
            )

            conf_cmd = (
                f"echo '[general]' > {repo_path}/conf/svnserve.conf && "
                f"echo 'anon-access = none' >> {repo_path}/conf/svnserve.conf && "
                f"echo 'auth-access = write' >> {repo_path}/conf/svnserve.conf && "
                f"echo 'password-db = passwd' >> {repo_path}/conf/svnserve.conf"
            )
            subprocess.run(
                ["docker", "exec", self.container, "sh", "-c", conf_cmd],
                check=True,
                capture_output=True,
            )

            pwd_cmd = (
                f"echo '[users]' > {repo_path}/conf/passwd && "
                f"echo '{DEV_SVN_USER} = {DEV_SVN_PASSWORD}' >> {repo_path}/conf/passwd"
            )
            subprocess.run(
                ["docker", "exec", self.container, "sh", "-c", pwd_cmd],
                check=True,
                capture_output=True,
            )

            if initialize_topology:
                mkdir_cmd = f"svn mkdir file://{repo_path}/{vfs_svn} -m 'Init Hub Topology'"
                subprocess.run(
                    ["docker", "exec", self.container, "sh", "-c", mkdir_cmd],
                    check=True,
                    capture_output=True,
                )

            print(f"[LocalVCS] Repository '{repo_name}' created successfully.")
            return True
        except Exception as error:  # noqa: BLE001
            print(f"[LocalVCS] WARNING: Failed to configure SVN Docker: {error}")
            return False

    def destroy(self, repo_name: str, vfs_svn: str) -> Tuple[bool, str]:
        repo_name = validate_repo_name(normalize_repo_name(repo_name))
        repo_path = self._repo_path(repo_name)
        try:
            subprocess.run(
                ["docker", "exec", self.container, "rm", "-rf", repo_path],
                check=True,
                capture_output=True,
            )
            print(f"[LocalVCS] Repository '{repo_name}' removed from Docker.")
            return True, f"VCS repository '{repo_name}' removed."
        except Exception as error:  # noqa: BLE001
            print(f"[LocalVCS] WARNING: Failed to remove SVN repository '{repo_name}': {error}")
            return False, f"Failed to remove VCS repository: {error}"


class RemoteSSHRepositoryAdmin(RepositoryAdmin):
    """Manages per-project repositories on a remote VPS through OpenSSH.

    All commands are executed inside the configured Docker container with
    ``docker exec`` (the container holds ``svnadmin``/``svn`` and the repository
    root). ``docker exec -i`` is used whenever stdin must be forwarded (writing
    ``svnserve.conf``).
    """

    def __init__(self, profile: VCSServerProfile, runner: SshRunner) -> None:
        self.profile = profile
        self.remote = profile.remote
        self.runner = runner

    def _wrap(self, command: str, interactive: bool = False) -> str:
        """Wrap a server command so it runs inside the SVN Docker container."""
        if not self.remote.container:
            raise RuntimeError(
                "Remote VCS container is not configured. Set the Docker container "
                "name in the Infrastructure panel."
            )
        flags = "-i " if interactive else ""
        user = ""
        if self.remote.container_user:
            user = f"-u {self.runner.quote(self.remote.container_user)} "
        container = self.runner.quote(self.remote.container)
        return f"docker exec {flags}{user}{container} sh -c {self.runner.quote(command)}"

    def _repo_path(self, repo_name: str) -> str:
        root = self.remote.repo_root.rstrip("/")
        return f"{root}/{repo_name}"

    def _exists(self, path: str) -> bool:
        quoted = self.runner.quote(path)
        result = self.runner.run(self._wrap(f"test -d {quoted}"), check=False)
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        stderr = result.stderr or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        raise RuntimeError(f"Remote probe failed: {stderr.strip() or result.returncode}")

    def _write_serve_conf(self, repo_path: str) -> None:
        """Point the repository at the studio-wide svnserve account database."""
        conf_body = (
            "[general]\n"
            "anon-access = none\n"
            "auth-access = write\n"
            f"password-db = {self.remote.effective_password_db()}\n"
            f"realm = {self.remote.realm}\n"
        )
        conf_path = self.runner.quote(f"{repo_path}/conf/svnserve.conf")
        self.runner.run(
            self._wrap(f"cat > {conf_path}", interactive=True),
            input_data=conf_body.encode("utf-8"),
            check=True,
        )

    def create(self, repo_name: str, vfs_svn: str, initialize_topology: bool = True) -> bool:
        repo_name = validate_repo_name(normalize_repo_name(repo_name))
        repo_path = self._repo_path(repo_name)

        if self._exists(repo_path):
            print(f"[RemoteVCS] Repository '{repo_name}' already exists. Skipping creation.")
            return True

        quoted_path = self.runner.quote(repo_path)
        self.runner.run(self._wrap(f"svnadmin create {quoted_path}"), check=True)
        self._write_serve_conf(repo_path)

        if initialize_topology:
            quoted_vfs = self.runner.quote(f"file://{repo_path}/{vfs_svn}")
            self.runner.run(
                self._wrap(f"svn mkdir {quoted_vfs} -m 'Init Hub Topology' -q"),
                check=True,
            )

        print(f"[RemoteVCS] Repository '{repo_name}' created on {self.remote.host}.")
        return True

    def destroy(self, repo_name: str, vfs_svn: str) -> Tuple[bool, str]:
        repo_name = validate_repo_name(normalize_repo_name(repo_name))
        repo_path = self._repo_path(repo_name)

        if not self._exists(repo_path):
            return True, f"VCS repository '{repo_name}' is already absent."

        quoted_path = self.runner.quote(repo_path)
        try:
            self.runner.run(self._wrap(f"rm -rf {quoted_path}"), check=True)
        except RuntimeError as error:
            return False, f"Failed to remove remote VCS repository: {error}"
        return True, f"VCS repository '{repo_name}' removed from {self.remote.host}."


def build_repository_admin(
    profile: VCSServerProfile,
    ssh_passphrase_provider=None,
) -> RepositoryAdmin:
    """Factory selecting the lifecycle strategy for the configured server mode."""
    if profile.mode == LOCAL_DOCKER:
        return LocalDockerRepositoryAdmin(
            container=profile.local_container,
            repo_root=profile.local_repo_root,
        )
    runner = SshRunner(profile.remote, passphrase_provider=ssh_passphrase_provider)
    return RemoteSSHRepositoryAdmin(profile, runner)
