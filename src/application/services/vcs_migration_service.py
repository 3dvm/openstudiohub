# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/vcs_migration_service.py
# Architectural role: Application service / VCS server migration
# =========================================================================================

"""Per-project migration of a project repository between two VCS servers.

History is preserved with ``svnadmin dump`` -> ``svnadmin load`` (the repository
UUID survives, so the existing working copy can be repointed with ``svn
relocate`` instead of being re-checked out). Both endpoints may be the local
Docker sandbox or a remote VPS administered through OpenSSH; the source is the
server the project is currently bound to and the target is chosen explicitly.
"""

import json
import shlex
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib.parse import urlsplit

from src.domain.workspace.vcs_server import VCSServer
from src.domain.workspace.vcs_server_profile import LOCAL_DOCKER
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

    def _registry(self):
        getter = getattr(self.config_factory, "get_vcs_servers", None)
        return getter() if callable(getter) else None

    def _server(self, server_id: str = "") -> Optional[VCSServer]:
        if server_id:
            getter = getattr(self.config_factory, "get_server", None)
            if callable(getter):
                server = getter(server_id)
                if server is not None:
                    return server
        getter = getattr(self.config_factory, "get_default_server", None)
        return getter() if callable(getter) else None

    def _source_server(self, project_root: Path) -> Optional[VCSServer]:
        getter = getattr(self.config_factory, "get_server_for_project", None)
        if callable(getter):
            try:
                return getter(project_root)
            except Exception:  # noqa: BLE001
                return None
        return None

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

    def _repo_root(self, server: VCSServer) -> str:
        if server.profile.mode == LOCAL_DOCKER:
            return server.profile.local_repo_root.rstrip("/")
        return server.profile.remote.repo_root.rstrip("/")

    def _repo_path(self, server: VCSServer, repo_name: str) -> str:
        return f"{self._repo_root(server)}/{repo_name}"

    def _base_url(self, server: VCSServer) -> str:
        return (server.repository_url or "").rstrip("/")

    def _target_url(self, server: VCSServer, repo_name: str, vfs_svn: str) -> str:
        return f"{self._base_url(server)}/{repo_name}/{vfs_svn}"

    def _admin(self, server: VCSServer):
        return build_repository_admin(server.profile, self._passphrase_provider())

    def _update_blueprint(self, project_root: Path, server: VCSServer) -> None:
        vfs_pipeline = self.config_factory.get_vfs_pipeline_name()
        blueprint_path = Path(project_root) / vfs_pipeline / "project_init.json"
        if not blueprint_path.exists():
            return
        try:
            with open(blueprint_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            data["vcs_server_id"] = server.id
            data["vcs_base_url"] = server.repository_url
            with open(blueprint_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=4)
        except Exception as error:  # noqa: BLE001
            print(f"[VCSMigration] Failed to update blueprint VCS binding: {error}")

    # ------------------------------------------------------------------
    # Server command builders
    # ------------------------------------------------------------------
    @staticmethod
    def _remote_docker_inner(server: VCSServer, inner: str, interactive: bool = False) -> str:
        flags = "-i " if interactive else ""
        container = shlex.quote(server.profile.remote.container)
        return f"docker exec {flags}{container} sh -c {shlex.quote(inner)}"

    def _probe(self, server: VCSServer, inner: str):
        """Run a read-only server command and return the CompletedProcess."""
        if server.profile.mode == LOCAL_DOCKER:
            return subprocess.run(
                ["docker", "exec", server.profile.local_container, "sh", "-c", inner],
                capture_output=True,
                text=True,
            )
        runner = SshRunner(server.profile.remote, passphrase_provider=self._passphrase_provider())
        return runner.run(self._remote_docker_inner(server, inner), check=False)

    def _exists(self, server: VCSServer, path: str) -> bool:
        result = self._probe(server, f"test -d {shlex.quote(path)}")
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        stderr = result.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        raise RuntimeError(f"Server probe failed: {stderr.strip() or result.returncode}")

    def _youngest(self, server: VCSServer, path: str) -> Optional[int]:
        if not self._exists(server, path):
            return None
        result = self._probe(server, f"svnlook youngest {shlex.quote(path)}")
        if result.returncode != 0:
            stderr = result.stderr or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            raise RuntimeError(f"svnlook failed: {stderr.strip() or result.returncode}")
        try:
            return int((result.stdout or "0").strip())
        except (TypeError, ValueError):
            return None

    def _dump_popen(self, server: VCSServer, repo_path: str):
        inner = f"svnadmin dump --quiet {shlex.quote(repo_path)}"
        if server.profile.mode == LOCAL_DOCKER:
            proc = subprocess.Popen(
                ["docker", "exec", server.profile.local_container, "sh", "-c", inner],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return proc, (lambda: None)
        runner = SshRunner(server.profile.remote, passphrase_provider=self._passphrase_provider())
        return runner.popen(self._remote_docker_inner(server, inner), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _load_popen(self, server: VCSServer, repo_path: str, stdin):
        inner = f"svnadmin load --quiet {shlex.quote(repo_path)}"
        if server.profile.mode == LOCAL_DOCKER:
            proc = subprocess.Popen(
                ["docker", "exec", "-i", server.profile.local_container, "sh", "-c", inner],
                stdin=stdin,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            return proc, (lambda: None)
        runner = SshRunner(server.profile.remote, passphrase_provider=self._passphrase_provider())
        return runner.popen(
            self._remote_docker_inner(server, inner, interactive=True),
            stdin=stdin,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def migrate_project(
        self,
        project_root: Path,
        vcs_user: str = "",
        vcs_pwd: str = "",
        delete_old_repo: bool = False,
        target_server_id: str = "",
    ) -> Tuple[bool, str]:
        project_root = Path(project_root)
        source = self._source_server(project_root)
        target = self._server(target_server_id)

        if target is None:
            return False, "No VCS server is configured."
        if target.adapter != "svn":
            return False, "Only SVN repositories can be migrated."
        if source is not None and source.id == target.id:
            return False, "The project is already bound to the selected server."
        if source is not None and not source.is_enabled:
            return False, "The project's current VCS server is disabled."

        vfs_svn = self.config_factory.get_vfs_svn_name()
        workspace = self._workspace(project_root, vfs_svn)
        if not (workspace / ".svn").exists():
            return False, f"No local working copy found at {workspace}."

        repo_name = normalize_repo_name(project_root.name)
        target_url = self._target_url(target, repo_name, vfs_svn)

        # Already pointing at the target?
        try:
            current_url = self._working_copy_url(workspace)
        except Exception as error:  # noqa: BLE001
            return False, f"Cannot read the working copy URL: {error}"

        if target.profile.mode != LOCAL_DOCKER:
            if urlsplit(current_url).hostname == target.profile.remote.host:
                return True, f"'{repo_name}' already points at {self._base_url(target)}."

        # Ensure the target repository exists and is empty.
        target_path = self._repo_path(target, repo_name)
        try:
            youngest = self._youngest(target, target_path)
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to inspect the target repository: {error}"

        if youngest:
            return False, (
                f"Target repository '{repo_name}' already contains revision {youngest}. "
                "Delete it or migrate into a clean repository."
            )

        if youngest is None:
            self._report(f"Creating target repository '{repo_name}'...")
            if not self._admin(target).create(repo_name, vfs_svn):
                return False, f"Failed to create the target repository '{repo_name}'."

        # Stream the dump from the source into the target.
        self._report(f"Transferring repository '{repo_name}'...")
        ok, message = self._transfer(source, target, repo_name)
        if not ok:
            return False, message

        # Repoint the working copy (UUID preserved by dump/load).
        self._report("Relocating working copy to the target server...")
        adapter = SVNAdapter(
            target_url,
            workspace,
            server_profile=target.profile,
            ssh_passphrase_provider=self._passphrase_provider(),
        )
        try:
            adapter.relocate(target_url, vcs_user, vcs_pwd)
        except RuntimeError as error:
            return False, f"svn relocate failed: {error}"

        self._update_blueprint(project_root, target)

        if delete_old_repo and source is not None:
            self._report(f"Removing old repository '{repo_name}'...")
            deleted, delete_message = self._admin(source).destroy(repo_name, vfs_svn)
            if not deleted:
                return True, f"Migrated, but failed to delete the old repository: {delete_message}"

        return True, f"'{repo_name}' migrated to {self._base_url(target)}."

    def delete_repository(self, server_id: str, project_name: str) -> Tuple[bool, str]:
        """Destroy a project repository on a specific server."""
        server = self._server(server_id)
        if server is None:
            return False, "VCS server not found."
        return self._admin(server).destroy(
            normalize_repo_name(project_name), self.config_factory.get_vfs_svn_name()
        )

    def delete_local_repository(self, project_name: str) -> Tuple[bool, str]:
        """Destroy the repository on the local Docker server (legacy helper)."""
        registry = self._registry()
        server = None
        if registry is not None:
            for candidate in registry.servers:
                if candidate.profile.mode == LOCAL_DOCKER:
                    server = candidate
                    break
        if server is None:
            return False, "No local Docker VCS server is configured."
        return self._admin(server).destroy(
            normalize_repo_name(project_name), self.config_factory.get_vfs_svn_name()
        )

    # ------------------------------------------------------------------
    # Connectivity tests (Infrastructure panel)
    # ------------------------------------------------------------------
    def test_remote_connection(self, server: Optional[VCSServer] = None) -> Tuple[bool, str]:
        """Open an SSH session and confirm the SVN admin tools are available."""
        server = server or self._server()
        if server is None or server.profile.mode == LOCAL_DOCKER:
            return False, "The selected server is not a remote SSH server."
        remote = server.profile.remote
        if not remote.is_configured:
            return False, "Remote server host, SSH user or container is not configured."

        runner = SshRunner(remote, passphrase_provider=self._passphrase_provider())
        inner = "svnadmin --version > /dev/null && echo OPENSTUDIO_OK"
        try:
            result = runner.run(self._remote_docker_inner(server, inner), check=False)
        except Exception as error:  # noqa: BLE001
            return False, f"SSH connection failed: {error}"

        if result.returncode == 0:
            return True, f"SSH connection to {remote.host} succeeded."
        stderr = result.stderr or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return False, f"SSH connection failed: {stderr.strip() or result.returncode}"

    def test_remote_svn(self, server: Optional[VCSServer] = None) -> Tuple[bool, str]:
        """Probe the SVN endpoint of a server before provisioning."""
        server = server or self._server()
        if server is None:
            return False, "No VCS server is configured."
        return VCSRouter.probe_health(
            server.adapter,
            server.repository_url,
            server_profile=server.profile,
            ssh_passphrase_provider=self._passphrase_provider(),
        )

    # ------------------------------------------------------------------
    # Transfer
    # ------------------------------------------------------------------
    def _transfer(self, source: Optional[VCSServer], target: VCSServer, repo_name: str) -> Tuple[bool, str]:
        if source is None:
            return False, "Cannot determine the project's current VCS server."

        source_path = self._repo_path(source, repo_name)
        try:
            dump_proc, dump_cleanup = self._dump_popen(source, source_path)
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to start the source dump: {error}"

        try:
            load_proc, load_cleanup = self._load_popen(
                target, self._repo_path(target, repo_name), stdin=dump_proc.stdout
            )
        except Exception as error:  # noqa: BLE001
            dump_proc.kill()
            dump_cleanup()
            return False, f"Failed to start the target load: {error}"

        # Drain stderr on background threads to avoid a full-pipe deadlock.
        dump_err_chunks: list = []
        load_err_chunks: list = []
        threads = [
            threading.Thread(target=self._drain, args=(dump_proc.stderr, dump_err_chunks)),
            threading.Thread(target=self._drain, args=(load_proc.stderr, load_err_chunks)),
        ]
        for thread in threads:
            thread.start()

        try:
            dump_proc.wait()
            load_proc.wait()
        finally:
            for thread in threads:
                thread.join()
            if dump_proc.stdout:
                dump_proc.stdout.close()
            dump_cleanup()
            load_cleanup()

        if dump_proc.returncode != 0:
            return False, f"Source dump failed: {b''.join(dump_err_chunks).decode('utf-8', 'replace').strip()}"
        if load_proc.returncode != 0:
            return False, f"Target load failed: {b''.join(load_err_chunks).decode('utf-8', 'replace').strip()}"
        return True, "Repository transferred."

    @staticmethod
    def _drain(pipe, sink: list) -> None:
        if pipe is None:
            return
        try:
            sink.append(pipe.read() or b"")
        except Exception:  # noqa: BLE001
            pass

