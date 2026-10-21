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
import shlex
import subprocess
from typing import Tuple

from src.domain.workspace.vcs_server_profile import (
    LOCAL_DOCKER,
    VCSServerProfile,
)
from src.infrastructure.dev_defaults import DEV_SVN_PASSWORD, DEV_SVN_USER
from src.infrastructure.vcs.ssh_runner import SshRunner

_REPO_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

AUTO_PROPS = "*.blend = svn:needs-lock=yes\n"
GLOBAL_IGNORES = "\n".join(
    (
        "*.blend1",
        "*.blend2",
        "*.tmp",
        "*.bak",
        "*.swp",
        "*.log",
        "*.lock",
        "*.cache",
        "*.pyc",
        "__pycache__",
        ".DS_Store",
        "Thumbs.db",
    )
) + "\n"

PRE_COMMIT_HOOK = """#!/bin/sh
# OpenStudioHub repository policy.
set -u
REPOS="$1"
TXN="$2"
CHANGED="/tmp/openstudiohub-pre-commit.$$"
trap 'rm -f "$CHANGED"' EXIT

svnlook changed -t "$TXN" "$REPOS" > "$CHANGED" || exit 1

while IFS= read -r line; do
  action=$(printf '%s' "$line" | cut -c1)
  path=$(printf '%s' "$line" | cut -c5-)
  [ -n "$path" ] || continue

  case "$action" in
    A|M|R)
      case "$path" in
        *.blend1|*.blend2|*.tmp|*.bak|*.swp|*.log|*.lock|*.cache|*.pyc|*/__pycache__/*|*/.DS_Store|*/Thumbs.db|*/cache/*|*/proxy/*)
          echo "OpenStudioHub policy: '$path' is a temporary/cache file and must not be committed." >&2
          exit 1
          ;;
      esac
      case "$path" in
        *.blend)
          if ! svnlook proplist -t "$TXN" "$REPOS" "$path" | grep -q '^  svn:needs-lock$'; then
            echo "OpenStudioHub policy: '$path' must have svn:needs-lock=yes before it can be committed." >&2
            exit 1
          fi
          ;;
      esac
      ;;
  esac
done < "$CHANGED"

exit 0
"""


def parse_locks(output: str) -> list[dict]:
    """Parse the output of ``svnadmin lslocks`` into lock dictionaries."""
    locks: list[dict] = []
    lines = (output or "").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("Path:"):
            index += 1
            continue
        lock = {"path": line.split(":", 1)[1].strip()}
        index += 1
        while index < len(lines) and lines[index].strip():
            entry = lines[index]
            if entry.startswith("Comment ("):
                match = re.search(r"\((\d+) line", entry)
                count = int(match.group(1)) if match else 0
                index += 1
                comment = lines[index : index + count]
                lock["comment"] = "\n".join(comment).strip()
                index += count
                continue
            key, separator, value = entry.partition(":")
            if separator:
                key = key.strip()
                value = value.strip()
                if key == "UUID Token":
                    lock["token"] = value
                elif key == "Owner":
                    lock["owner"] = value
                elif key == "Created":
                    lock["created"] = value
                elif key == "Expires":
                    lock["expires"] = value
            index += 1
        locks.append(lock)
        index += 1
    return locks


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

    def ensure_policy(self, repo_name: str) -> Tuple[bool, str]:
        raise NotImplementedError

    def list_locks(self, repo_name: str) -> Tuple[bool, list, str]:
        raise NotImplementedError

    def break_lock(self, repo_name: str, path: str) -> Tuple[bool, str]:
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
                # Keep existing repositories under the same policy. This is
                # idempotent and repairs projects created before the hook was
                # introduced.
                self._install_hooks(repo_path)
                if initialize_topology:
                    self._apply_policy(repo_path)
                print(f"[LocalVCS] Repository '{repo_name}' already exists. Policy refreshed.")
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
                self._apply_policy(repo_path)
            self._install_hooks(repo_path)

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

    def _apply_policy(self, repo_path: str) -> None:
        """Set lock and ignore defaults on a fresh repository."""
        try:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container,
                    "svnmucc",
                    "-U",
                    f"file://{repo_path}",
                    "-m",
                    "Configure OpenStudioHub policy",
                    "propset",
                    "svn:auto-props",
                    AUTO_PROPS,
                    "/",
                    "propset",
                    "svn:global-ignores",
                    GLOBAL_IGNORES,
                    "/",
                ],
                check=True,
                capture_output=True,
            )
        except Exception as error:  # noqa: BLE001
            # The pre-commit hook still enforces the lock policy if svnmucc is
            # unavailable in the container.
            print(f"[LocalVCS] WARNING: Could not apply auto-props/ignores: {error}")

    def _install_hooks(self, repo_path: str) -> None:
        """Install the pre-commit policy hook inside the container."""
        hook_path = f"{repo_path}/hooks/pre-commit"
        command = (
            f"cat > {shlex.quote(hook_path)} && chmod +x {shlex.quote(hook_path)}"
        )
        subprocess.run(
            ["docker", "exec", "-i", self.container, "sh", "-c", command],
            input=PRE_COMMIT_HOOK.encode("utf-8"),
            check=True,
            capture_output=True,
        )

    def list_locks(self, repo_name: str) -> Tuple[bool, list, str]:
        repo_name = validate_repo_name(normalize_repo_name(repo_name))
        repo_path = self._repo_path(repo_name)
        try:
            result = subprocess.run(
                ["docker", "exec", self.container, "svnadmin", "lslocks", repo_path],
                check=True,
                capture_output=True,
                text=True,
            )
            return True, parse_locks(result.stdout), ""
        except Exception as error:  # noqa: BLE001
            return False, [], f"Failed to list locks: {error}"

    def break_lock(self, repo_name: str, path: str) -> Tuple[bool, str]:
        repo_name = validate_repo_name(normalize_repo_name(repo_name))
        repo_path = self._repo_path(repo_name)
        try:
            subprocess.run(
                ["docker", "exec", self.container, "svnadmin", "rmlocks", repo_path, path],
                check=True,
                capture_output=True,
            )
            return True, f"Lock removed from '{path}'."
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to remove the lock: {error}"

    def ensure_policy(self, repo_name: str) -> Tuple[bool, str]:
        repo_name = validate_repo_name(normalize_repo_name(repo_name))
        repo_path = self._repo_path(repo_name)
        try:
            existing = subprocess.run(
                ["docker", "exec", self.container, "test", "-d", repo_path],
                check=False,
                capture_output=True,
            )
            if existing.returncode != 0:
                return False, f"VCS repository '{repo_name}' was not found."
            self._install_hooks(repo_path)
            self._apply_policy(repo_path)
            return True, f"VCS lock policy applied to '{repo_name}'."
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to apply the VCS policy: {error}"

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
        log_path = self.runner.diagnostics.log_path
        log_hint = f" (full diagnostics: {log_path})" if log_path else ""
        raise RuntimeError(f"Remote probe failed: {stderr.strip() or result.returncode}{log_hint}")

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
            self._install_hooks(repo_path)
            if initialize_topology:
                self._apply_policy(repo_path)
            print(f"[RemoteVCS] Repository '{repo_name}' already exists. Policy refreshed.")
            return True

        quoted_path = self.runner.quote(repo_path)
        self.runner.run(self._wrap(f"svnadmin create {quoted_path}"), check=True)
        self._write_serve_conf(repo_path)

        if initialize_topology:
            self._apply_policy(repo_path)
        self._install_hooks(repo_path)

        if initialize_topology:
            quoted_vfs = self.runner.quote(f"file://{repo_path}/{vfs_svn}")
            self.runner.run(
                self._wrap(f"svn mkdir {quoted_vfs} -m 'Init Hub Topology' -q"),
                check=True,
            )

        print(f"[RemoteVCS] Repository '{repo_name}' created on {self.remote.host}.")
        return True

    def _apply_policy(self, repo_path: str) -> None:
        """Set lock and ignore defaults on a fresh repository."""
        root_url = self.runner.quote(f"file://{repo_path}")
        auto_props = self.runner.quote(AUTO_PROPS)
        ignores = self.runner.quote(GLOBAL_IGNORES)
        try:
            self.runner.run(
                self._wrap(
                    f"svnmucc -U {root_url} -m 'Configure OpenStudioHub policy' "
                    f"propset svn:auto-props {auto_props} / "
                    f"propset svn:global-ignores {ignores} /"
                ),
                check=True,
            )
        except RuntimeError as error:
            print(f"[RemoteVCS] WARNING: Could not apply auto-props/ignores: {error}")

    def _install_hooks(self, repo_path: str) -> None:
        """Install the pre-commit policy hook inside the container."""
        hook_path = self.runner.quote(f"{repo_path}/hooks/pre-commit")
        self.runner.run(
            self._wrap(f"cat > {hook_path} && chmod +x {hook_path}", interactive=True),
            input_data=PRE_COMMIT_HOOK.encode("utf-8"),
            check=True,
        )

    def list_locks(self, repo_name: str) -> Tuple[bool, list, str]:
        repo_name = validate_repo_name(normalize_repo_name(repo_name))
        repo_path = self._repo_path(repo_name)
        try:
            result = self.runner.run(
                self._wrap(f"svnadmin lslocks {self.runner.quote(repo_path)}"),
                check=True,
            )
            output = result.stdout
            if isinstance(output, bytes):
                output = output.decode("utf-8", "replace")
            return True, parse_locks(str(output or "")), ""
        except RuntimeError as error:
            return False, [], f"Failed to list locks: {error}"

    def break_lock(self, repo_name: str, path: str) -> Tuple[bool, str]:
        repo_name = validate_repo_name(normalize_repo_name(repo_name))
        repo_path = self._repo_path(repo_name)
        try:
            self.runner.run(
                self._wrap(
                    f"svnadmin rmlocks {self.runner.quote(repo_path)} "
                    f"{self.runner.quote(path)}"
                ),
                check=True,
            )
            return True, f"Lock removed from '{path}'."
        except RuntimeError as error:
            return False, f"Failed to remove the lock: {error}"

    def ensure_policy(self, repo_name: str) -> Tuple[bool, str]:
        repo_name = validate_repo_name(normalize_repo_name(repo_name))
        repo_path = self._repo_path(repo_name)
        if not self._exists(repo_path):
            return False, f"VCS repository '{repo_name}' was not found."
        try:
            self._install_hooks(repo_path)
            self._apply_policy(repo_path)
        except RuntimeError as error:
            return False, f"Failed to apply the VCS policy: {error}"
        return True, f"VCS lock policy applied to '{repo_name}'."

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
