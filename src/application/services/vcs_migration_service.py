# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/vcs_migration_service.py
# Architectural role: Application service / local -> remote VCS migration
# =========================================================================================

"""Per-project migration of a project repository from the local Docker SVN
sandbox to a remote VPS administered over OpenSSH.

History is preserved with ``svnadmin dump`` -> ``svnadmin load`` (the repository
UUID survives, so the existing working copy can be repointed with ``svn
relocate`` instead of being re-checked out). Only the VCS is migrated here;
Kitsu migration is handled separately.
"""

import json
import shlex
import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib.parse import urlsplit

from src.domain.workspace.vcs_server_profile import (
    LOCAL_DOCKER,
    REMOTE_SSH,
    VCSServerProfile,
)
from src.infrastructure.vcs.repository_admin import (
    build_repository_admin,
    normalize_repo_name,
)
from src.infrastructure.vcs.ssh_runner import SshRunner
from src.infrastructure.vcs.svn_adapter import SVNAdapter
from src.infrastructure.vcs.vcs_router import VCSRouter

StatusCallback = Callable[[str, str], None]


class VCSMigrationService:
    def __init__(self, config_factory, credential_vault=None, status_callback: Optional[StatusCallback] = None) -> None:
        self.config_factory = config_factory
        self.credential_vault = credential_vault
        self._status = status_callback or (lambda _message, _color: None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _report(self, message: str, color: str = "yellow") -> None:
        self._status(message, color)

    def _passphrase_provider(self):
        if self.credential_vault is None:
            return None
        return self.credential_vault.get_ssh_passphrase

    def _profile(self) -> VCSServerProfile:
        getter = getattr(self.config_factory, "get_vcs_server_profile", None)
        return getter() if callable(getter) else VCSServerProfile()

    def _workspace(self, project_root: Path, vfs_svn: str) -> Path:
        return Path(project_root) / vfs_svn

    def _working_copy_url(self, workspace: Path) -> str:
        result = subprocess.run(
            ["svn", "info", "--show-item", "url"],
            cwd=str(workspace),
            check=True,
            capture_output=True,
            text=True,
        )
        return (result.stdout or "").strip()

    def _remote_base_url(self, profile: VCSServerProfile) -> str:
        return f"svn://{profile.remote.host}"

    def _update_blueprint_url(self, project_root: Path, base_url: str) -> None:
        vfs_pipeline = self.config_factory.get_vfs_pipeline_name()
        blueprint_path = Path(project_root) / vfs_pipeline / "project_init.json"
        if not blueprint_path.exists():
            return
        try:
            with open(blueprint_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            data["vcs_base_url"] = base_url
            with open(blueprint_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=4)
        except Exception as error:  # noqa: BLE001
            print(f"[VCSMigration] Failed to update blueprint vcs_base_url: {error}")

    def _remote_repo_youngest(self, runner: SshRunner, repo_path: str) -> Optional[int]:
        """Return the youngest revision on the remote repo, or None when absent."""
        quoted = shlex.quote(repo_path)
        exists = runner.run(f"test -d {quoted}", check=False)
        if exists.returncode != 0:
            return None
        result = runner.run(f"svnlook youngest {quoted}", check=True)
        try:
            return int((result.stdout or "0").strip())
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def migrate_project(
        self,
        project_root: Path,
        vcs_user: str = "",
        vcs_pwd: str = "",
        delete_old_repo: bool = False,
    ) -> Tuple[bool, str]:
        project_root = Path(project_root)
        profile = self._profile()

        if profile.mode != REMOTE_SSH:
            return False, "The active VCS server is local; configure a remote server before migrating."
        if not profile.remote.is_configured:
            return False, "Remote VCS server is not configured (missing host, SSH user or container)."

        vfs_svn = self.config_factory.get_vfs_svn_name()
        workspace = self._workspace(project_root, vfs_svn)
        if not (workspace / ".svn").exists():
            return False, f"No local working copy found at {workspace}."

        repo_name = normalize_repo_name(project_root.name)
        remote_base = self._remote_base_url(profile)
        target_url = f"{remote_base}/{repo_name}/{vfs_svn}"

        # 1. Already migrated?
        try:
            current_url = self._working_copy_url(workspace)
        except Exception as error:  # noqa: BLE001
            return False, f"Cannot read the working copy URL: {error}"

        if urlsplit(current_url).hostname == profile.remote.host:
            return True, f"'{repo_name}' already points at {remote_base}."

        # 2. Ensure the remote repository exists and is empty (dump/load target).
        runner = SshRunner(profile.remote, passphrase_provider=self._passphrase_provider())
        remote_repo_path = f"{profile.remote.repo_root.rstrip('/')}/{repo_name}"
        try:
            youngest = self._remote_repo_youngest(runner, remote_repo_path)
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to inspect the remote repository: {error}"

        if youngest:
            return False, (
                f"Remote repository '{repo_name}' already contains revision {youngest}. "
                "Delete it or migrate into a clean repository."
            )

        local_profile = VCSServerProfile(
            mode=LOCAL_DOCKER,
            local_container=profile.local_container,
            local_repo_root=profile.local_repo_root,
        )
        local_admin = build_repository_admin(local_profile)

        if youngest is None:
            self._report(f"Creating remote repository '{repo_name}'...")
            remote_admin = build_repository_admin(profile, self._passphrase_provider())
            if not remote_admin.create(repo_name, vfs_svn):
                return False, f"Failed to create the remote repository '{repo_name}'."

        # 3. Dump the local repository and stream it into the remote.
        self._report(f"Dumping local repository '{repo_name}' and loading it remotely...")
        ok, message = self._transfer_repository(
            profile, runner, repo_name, remote_repo_path
        )
        if not ok:
            return False, message

        # 4. Repoint the working copy (UUID preserved by dump/load).
        self._report("Relocating working copy to the remote server...")
        adapter = SVNAdapter(
            target_url,
            workspace,
            server_profile=profile,
            ssh_passphrase_provider=self._passphrase_provider(),
        )
        try:
            adapter.relocate(target_url, vcs_user, vcs_pwd)
        except RuntimeError as error:
            return False, f"svn relocate failed: {error}"

        self._update_blueprint_url(project_root, remote_base)

        # 5. Optional cleanup of the old local repository.
        if delete_old_repo:
            self._report(f"Removing old local repository '{repo_name}'...")
            deleted, delete_message = local_admin.destroy(repo_name, vfs_svn)
            if not deleted:
                return True, f"Migrated, but failed to delete the old repository: {delete_message}"

        return True, f"'{repo_name}' migrated to {remote_base}."

    def delete_local_repository(self, project_name: str) -> Tuple[bool, str]:
        """Destroy the local Docker repository once a migration has succeeded."""
        profile = self._profile()
        local_profile = VCSServerProfile(
            mode=LOCAL_DOCKER,
            local_container=profile.local_container,
            local_repo_root=profile.local_repo_root,
        )
        admin = build_repository_admin(local_profile)
        return admin.destroy(normalize_repo_name(project_name), self.config_factory.get_vfs_svn_name())

    # ------------------------------------------------------------------
    # Connectivity tests (Infrastructure panel)
    # ------------------------------------------------------------------
    def test_remote_connection(self) -> Tuple[bool, str]:
        """Open an SSH session and confirm the SVN admin tools are available."""
        profile = self._profile()
        if not profile.remote.is_configured:
            return False, "Remote server host or SSH user is not configured."

        runner = SshRunner(profile.remote, passphrase_provider=self._passphrase_provider())
        inner = "svnadmin --version > /dev/null && echo OPENSTUDIO_OK"
        if profile.remote.container:
            container = shlex.quote(profile.remote.container)
            command = f"docker exec {container} sh -c {shlex.quote(inner)}"
        else:
            command = inner
        try:
            result = runner.run(command, check=False)
        except Exception as error:  # noqa: BLE001
            return False, f"SSH connection failed: {error}"

        if result.returncode == 0:
            return True, f"SSH connection to {profile.remote.host} succeeded."
        stderr = result.stderr or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return False, f"SSH connection failed: {stderr.strip() or result.returncode}"

    def test_remote_svn(self) -> Tuple[bool, str]:
        """Probe the remote svnserve endpoint before provisioning."""
        profile = self._profile()
        return VCSRouter.probe_health(
            self.config_factory.get_vcs_adapter_type(),
            self.config_factory.get_vcs_repository_url(),
            server_profile=profile,
            ssh_passphrase_provider=self._passphrase_provider(),
        )

    # ------------------------------------------------------------------
    # Transfer
    # ------------------------------------------------------------------
    def _transfer_repository(
        self,
        profile: VCSServerProfile,
        runner: SshRunner,
        repo_name: str,
        remote_repo_path: str,
    ) -> Tuple[bool, str]:
        dump_cmd = [
            "docker", "exec", profile.local_container,
            "svnadmin", "dump", "--quiet",
            f"{profile.local_repo_root.rstrip('/')}/{repo_name}",
        ]
        load_cmd = f"svnadmin load --quiet {shlex.quote(remote_repo_path)}"
        if profile.remote.container:
            container = shlex.quote(profile.remote.container)
            load_cmd = f"docker exec -i {container} sh -c {shlex.quote(load_cmd)}"

        try:
            dump_proc = subprocess.Popen(
                dump_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to start the local dump: {error}"

        try:
            runner.run_stream(load_cmd, stdin=dump_proc.stdout)
        except Exception as error:  # noqa: BLE001
            dump_proc.kill()
            return False, f"Remote load failed: {error}"
        finally:
            if dump_proc.stdout:
                dump_proc.stdout.close()

        _, dump_err = dump_proc.communicate()
        if dump_proc.returncode != 0:
            return False, f"Local dump failed: {(dump_err or b'').decode('utf-8', 'replace').strip()}"
        return True, "Repository transferred."
