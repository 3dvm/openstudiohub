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

import collections
import json
import re
import shlex
import subprocess
import threading
import time
from datetime import datetime
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

STALL_SECONDS = 30.0
PUMP_CHUNK = 1 << 16


class VCSMigrationService:
    def __init__(
        self,
        config_factory,
        credential_vault=None,
        status_callback: Optional[StatusCallback] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        event_sink=None,
    ) -> None:
        self.config_factory = config_factory
        self.credential_vault = credential_vault
        self._status = status_callback or (lambda _message, _color: None)
        self._progress_cb = progress_callback or (lambda _percent: None)
        self._event_sink = event_sink  # thread-safe queue.Queue, drained by the UI thread
        self._cancel = threading.Event()
        self._procs: list = []
        self._log_lines: list = []

    # ------------------------------------------------------------------
    # Event / log plumbing
    # ------------------------------------------------------------------
    def _emit(self, kind: str, payload=None) -> None:
        """Push a structured event to the UI queue (never touches Qt directly)."""
        if self._event_sink is not None:
            try:
                self._event_sink.put((kind, payload))
            except Exception:  # noqa: BLE001
                pass

    def _log(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{stamp}] {line}"
        self._log_lines.append(entry)
        print(f"[VCSMigration] {line}")
        self._emit("log", entry)

    def cancel(self) -> None:
        """Request cancellation and terminate the running subprocesses."""
        self._cancel.set()
        for proc in list(self._procs):
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def _reset(self) -> None:
        self._cancel.clear()
        self._procs = []
        self._log_lines = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _report(self, message: str, color: str = "yellow") -> None:
        self._emit("phase", message)
        self._status(message, color)

    def _progress(self, percent: int) -> None:
        self._progress_cb(percent)

    def _passphrase_provider(self, server: Optional[VCSServer] = None):
        if self.credential_vault is None:
            return None
        server_id = server.id if server is not None else ""
        return lambda: self.credential_vault.get_ssh_passphrase(server_id)

    def _registry(self):
        getter = getattr(self.config_factory, "get_vcs_servers", None)
        return getter() if callable(getter) else None

    def _server(self, server_id: str = "") -> Optional[VCSServer]:
        if server_id:
            getter = getattr(self.config_factory, "get_server", None)
            return getter(server_id) if callable(getter) else None
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

    def _repo_size_bytes(self, server: VCSServer, path: str) -> Optional[int]:
        """Best-effort source repository size (for byte-based ETA)."""
        try:
            result = self._probe(server, f"du -sb {shlex.quote(path)}")
        except Exception:  # noqa: BLE001
            return None
        if getattr(result, "returncode", 1) != 0:
            return None
        try:
            return int((result.stdout or "0").split()[0])
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _tail_text(tail, limit: int = 8) -> str:
        if not tail:
            return ""
        return "\n".join(list(tail)[-limit:])

    def _stats_snapshot(self, stats: dict, load_progress: dict, total_revisions, total_bytes) -> dict:
        elapsed = max(time.monotonic() - stats["start"], 0.0001)
        transferred = stats["bytes"]
        speed = transferred / elapsed
        revision = load_progress.get("revision", 0)

        if total_bytes:
            ratio = min(transferred / total_bytes, 1.0)
            eta = (total_bytes - transferred) / speed if speed > 0 else None
        elif total_revisions and revision:
            ratio = min(revision / total_revisions, 1.0)
            per_rev = elapsed / revision
            eta = per_rev * max(total_revisions - revision, 0)
        else:
            ratio = 0.0
            eta = None

        return {
            "percent": min(90, 8 + int(82 * ratio)),
            "bytes": transferred,
            "speed": speed,
            "eta": eta,
            "revision": revision,
            "total": total_revisions,
            "elapsed": elapsed,
        }

    def _write_diagnostic_log(self, repo_name: str, source, target, success: bool, message: str) -> Optional[Path]:
        try:
            log_dir = Path.home() / ".openstudio" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = log_dir / f"vcs_migration_{repo_name}_{stamp}.log"
            header = (
                f"VCS migration diagnostics\n"
                f"repository: {repo_name}\n"
                f"source: {source.name if source else '?'} ({source.repository_url if source else ''})\n"
                f"target: {target.name if target else '?'} ({target.repository_url if target else ''})\n"
                f"result: {'SUCCESS' if success else 'FAILURE'} - {message}\n"
                f"{'-' * 60}\n"
            )
            log_path.write_text(header + "\n".join(self._log_lines) + "\n", encoding="utf-8")
            return log_path
        except Exception as error:  # noqa: BLE001
            print(f"[VCSMigration] Failed to write diagnostic log: {error}")
            return None

    def _admin(self, server: VCSServer):
        return build_repository_admin(server.profile, self._passphrase_provider(server))

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
        runner = SshRunner(server.profile.remote, passphrase_provider=self._passphrase_provider(server))
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

    def _uuid(self, server: VCSServer, path: str) -> Optional[str]:
        """Repository UUID (used to confirm a target already holds this repo)."""
        result = self._probe(server, f"svnlook uuid {shlex.quote(path)}")
        if getattr(result, "returncode", 1) != 0:
            return None
        return (result.stdout or "").strip() or None

    def _repo_top_level_dirs(self, server: VCSServer, repo_path: str) -> list:
        """Return the repository's top-level folder names (empty when unreadable)."""
        url = f"file://{repo_path}"
        result = self._probe(server, f"svn ls {shlex.quote(url)}")
        if getattr(result, "returncode", 1) != 0:
            return []
        stdout = result.stdout or ""
        if isinstance(stdout, (bytes, bytearray)):
            stdout = stdout.decode("utf-8", "replace")
        return [line.strip().rstrip("/") for line in stdout.splitlines() if line.strip()]

    def probe_repository_topography(
        self,
        server: Optional[VCSServer],
        project_name: str,
        vfs_svn: str = "",
    ) -> Tuple[bool, str]:
        """Confirm ``server`` hosts the project repository with the expected topography.

        Checks, in order: the SVN endpoint is reachable, the repository exists
        and is a valid SVN repository, and it exposes the expected ``vfs_svn``
        root folder. Never raises: returns ``(ok, human_readable_message)``.
        """
        if server is None:
            return False, "Select a VCS server to validate."
        if not getattr(server, "is_enabled", False):
            return True, "Version Control is disabled (NAS only)."

        vfs_svn = vfs_svn or self.config_factory.get_vfs_svn_name()
        online, message = self.test_remote_svn(server)
        if not online:
            return False, message

        repo_name = normalize_repo_name(project_name)
        repo_path = self._repo_path(server, repo_name)
        try:
            youngest = self._youngest(server, repo_path)
        except Exception as error:  # noqa: BLE001
            return False, f"Could not inspect '{repo_name}' on '{server.name}': {error}"
        if youngest is None:
            return False, f"Repository '{repo_name}' was not found on '{server.name}'."

        dirs = self._repo_top_level_dirs(server, repo_path)
        if vfs_svn and vfs_svn not in dirs:
            found = ", ".join(dirs) or "none"
            return False, (
                f"Repository '{repo_name}' exists on '{server.name}' but has no "
                f"'{vfs_svn}' folder (found: {found})."
            )
        return True, (
            f"Repository '{repo_name}' on '{server.name}' is healthy "
            f"(revision {youngest})."
        )

    def _dump_popen(self, server: VCSServer, repo_path: str):
        inner = f"svnadmin dump --quiet {shlex.quote(repo_path)}"
        if server.profile.mode == LOCAL_DOCKER:
            proc = subprocess.Popen(
                ["docker", "exec", server.profile.local_container, "sh", "-c", inner],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return proc, (lambda: None)
        runner = SshRunner(server.profile.remote, passphrase_provider=self._passphrase_provider(server))
        return runner.popen(self._remote_docker_inner(server, inner), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _load_popen(self, server: VCSServer, repo_path: str):
        # No --quiet: `svnadmin load` prints "Committed revision N" to stdout,
        # which we parse to drive the progress bar. stdin is fed by the pump.
        inner = f"svnadmin load {shlex.quote(repo_path)}"
        if server.profile.mode == LOCAL_DOCKER:
            proc = subprocess.Popen(
                ["docker", "exec", "-i", server.profile.local_container, "sh", "-c", inner],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return proc, (lambda: None)
        runner = SshRunner(server.profile.remote, passphrase_provider=self._passphrase_provider(server))
        return runner.popen(
            self._remote_docker_inner(server, inner, interactive=True),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
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
        self._reset()
        project_root = Path(project_root)
        source = self._source_server(project_root)
        target = self._server(target_server_id)
        repo_name = normalize_repo_name(project_root.name)

        def finish(ok: bool, message: str) -> Tuple[bool, str]:
            log_path = self._write_diagnostic_log(repo_name, source, target, ok, message)
            if log_path is not None:
                self._emit("log_path", str(log_path))
            return ok, message

        if source is None:
            return finish(False, "Could not resolve the project's current VCS server.")
        if target is None:
            return finish(False, "The selected target VCS server was not found.")
        if source.adapter != "svn" or target.adapter != "svn":
            return finish(False, "Only SVN repositories can be migrated.")
        if source.id == target.id:
            return finish(False, "The project is already bound to the selected server.")
        if not source.is_enabled:
            return finish(False, "The project's current VCS server is disabled.")

        vfs_svn = self.config_factory.get_vfs_svn_name()
        workspace = self._workspace(project_root, vfs_svn)
        if not (workspace / ".svn").exists():
            return finish(False, f"No local working copy found at {workspace}.")

        target_url = self._target_url(target, repo_name, vfs_svn)
        self._log(f"Migrating '{repo_name}' from '{source.name}' to '{target.name}'.")
        self._log(f"Source server: {source.repository_url} (mode={source.profile.mode})")
        self._log(f"Target server: {target.repository_url} (mode={target.profile.mode})")

        # Already pointing at the target?
        try:
            current_url = self._working_copy_url(workspace)
        except Exception as error:  # noqa: BLE001
            return finish(False, f"Cannot read the working copy URL: {error}")

        if target.profile.mode != LOCAL_DOCKER:
            if urlsplit(current_url).hostname == target.profile.remote.host:
                return finish(True, f"'{repo_name}' already points at {self._base_url(target)}.")

        # Source revision count (also verifies the source repo exists).
        source_path = self._repo_path(source, repo_name)
        try:
            source_youngest = self._youngest(source, source_path)
        except Exception as error:  # noqa: BLE001
            return finish(False, f"Failed to inspect the source repository: {error}")
        if source_youngest is None:
            return finish(False, f"Source repository '{repo_name}' was not found on '{source.name}'.")
        self._log(f"Source repository has {source_youngest} revision(s).")

        total_bytes = self._repo_size_bytes(source, source_path)
        if total_bytes:
            self._log(f"Source repository size (approx): {total_bytes} bytes.")

        self._report(f"Preparing migration of '{repo_name}' from '{source.name}' to '{target.name}'...")
        self._progress(2)

        # Ensure the target repository exists and is empty (or already holds this
        # same repository, so a retry after a later-step failure can resume).
        target_path = self._repo_path(target, repo_name)
        try:
            youngest = self._youngest(target, target_path)
        except Exception as error:  # noqa: BLE001
            return finish(False, f"Failed to inspect the target repository: {error}")

        already_loaded = False
        if youngest == source_youngest and youngest:
            source_uuid = self._uuid(source, source_path)
            target_uuid = self._uuid(target, target_path)
            if source_uuid and source_uuid == target_uuid:
                already_loaded = True
                self._report("Target already holds this repository; skipping transfer.")
                self._log(f"Target already has {youngest} revision(s) with a matching UUID; skipping transfer.")
            else:
                return finish(False, (
                    f"Target repository '{repo_name}' already contains {youngest} revision(s) "
                    "but does not match the source. Delete it or migrate into a clean repository."
                ))
        elif youngest:
            return finish(False, (
                f"Target repository '{repo_name}' already contains revision {youngest}. "
                "Delete it or migrate into a clean repository."
            ))

        if not already_loaded:
            if youngest is None:
                self._report(f"Creating target repository '{repo_name}'...")
                self._log("Creating the target repository (empty; the dump restores the topology).")
                # Empty target: the dump already carries revision 1 (including topology).
                if not self._admin(target).create(repo_name, vfs_svn, initialize_topology=False):
                    return finish(False, f"Failed to create the target repository '{repo_name}'.")
            self._progress(6)

        if self._cancel.is_set():
            return finish(False, "Migration cancelled by the user.")

        if not already_loaded:
            # Stream the dump from the source into the target.
            self._report(
                f"Transferring {source_youngest} revision(s) from '{source.name}' to '{target.name}'..."
            )
            ok, message = self._transfer(
                source, target, repo_name, total_revisions=source_youngest, total_bytes=total_bytes
            )
            if not ok:
                return finish(False, message)
        self._progress(90)

        # Verify the target now holds the same revisions.
        try:
            target_youngest = self._youngest(target, target_path)
        except Exception as error:  # noqa: BLE001
            return finish(False, f"Verification failed: could not read the target repository: {error}")
        if target_youngest != source_youngest:
            return finish(False, (
                f"Verification failed: target has {target_youngest} revision(s), "
                f"expected {source_youngest}."
            ))
        self._log(f"Verified target now has {target_youngest} revision(s).")

        # Repoint the working copy (UUID preserved by dump/load).
        self._report("Relocating working copy to the target server...")
        self._progress(94)
        adapter = SVNAdapter(
            target_url,
            workspace,
            server_profile=target.profile,
            ssh_passphrase_provider=self._passphrase_provider(target),
        )
        try:
            adapter.relocate(target_url, vcs_user, vcs_pwd)
        except RuntimeError as error:
            return finish(False, f"svn relocate failed: {error}")

        # Verify the working copy now points at the target.
        try:
            new_url = self._working_copy_url(workspace)
        except Exception as error:  # noqa: BLE001
            return finish(False, f"Verification failed: cannot read the working copy URL: {error}")
        if new_url.rstrip("/") != target_url.rstrip("/"):
            return finish(False, (
                f"Verification failed: working copy points at '{new_url}', expected '{target_url}'."
            ))

        self._update_blueprint(project_root, target)
        self._progress(100)
        self._log("Working copy repointed and blueprint updated.")

        if delete_old_repo and source is not None:
            self._report(f"Removing old repository '{repo_name}'...")
            self._log("Deleting the old source repository.")
            deleted, delete_message = self._admin(source).destroy(repo_name, vfs_svn)
            if not deleted:
                return finish(True, (
                    f"Migrated {source_youngest} revision(s), but failed to delete the old "
                    f"repository: {delete_message}"
                ))

        return finish(True, (
            f"'{repo_name}' migrated to '{target.name}' ({self._base_url(target)}) — "
            f"{source_youngest} revision(s) verified."
        ))

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

        runner = SshRunner(remote, passphrase_provider=self._passphrase_provider(server))
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
            ssh_passphrase_provider=self._passphrase_provider(server),
        )

    # ------------------------------------------------------------------
    # Transfer
    # ------------------------------------------------------------------
    def _transfer(
        self,
        source: Optional[VCSServer],
        target: VCSServer,
        repo_name: str,
        total_revisions: Optional[int] = None,
        total_bytes: Optional[int] = None,
    ) -> Tuple[bool, str]:
        if source is None:
            return False, "Cannot determine the project's current VCS server."

        source_path = self._repo_path(source, repo_name)
        target_path = self._repo_path(target, repo_name)

        try:
            dump_proc, dump_cleanup = self._dump_popen(source, source_path)
        except Exception as error:  # noqa: BLE001
            return False, f"Failed to start the source dump: {error}"
        self._procs.append(dump_proc)

        try:
            load_proc, load_cleanup = self._load_popen(target, target_path)
        except Exception as error:  # noqa: BLE001
            dump_proc.kill()
            dump_cleanup()
            return False, f"Failed to start the target load: {error}"
        self._procs.append(load_proc)

        stats = {"bytes": 0, "start": time.monotonic()}
        load_progress: dict = {"revision": 0}
        dump_tail: collections.deque = collections.deque(maxlen=200)
        load_tail: collections.deque = collections.deque(maxlen=200)
        load_out_tail: collections.deque = collections.deque(maxlen=200)

        threads = [
            threading.Thread(
                target=self._pump,
                args=(dump_proc.stdout, load_proc.stdin, stats),
                daemon=True,
            ),
            threading.Thread(
                target=self._drain_lines,
                args=(load_proc.stdout, load_out_tail, load_progress, total_revisions, stats, total_bytes),
                daemon=True,
            ),
            threading.Thread(target=self._drain_tail, args=(dump_proc.stderr, dump_tail), daemon=True),
            threading.Thread(target=self._drain_tail, args=(load_proc.stderr, load_tail), daemon=True),
        ]
        for thread in threads:
            thread.start()

        last_bytes = 0
        last_change = time.monotonic()
        stalled = False
        while dump_proc.poll() is None or load_proc.poll() is None:
            if self._cancel.is_set():
                dump_proc.kill()
                load_proc.kill()
                break
            time.sleep(0.25)
            now = time.monotonic()
            if stats["bytes"] != last_bytes:
                last_bytes = stats["bytes"]
                last_change = now
                stalled = False
            elif not stalled and (now - last_change) > STALL_SECONDS:
                stalled = True
                self._log(f"WARNING: no data received for {int(STALL_SECONDS)}s; the transfer appears stalled.")
                self._emit("stalled", None)
            self._emit("stats", self._stats_snapshot(stats, load_progress, total_revisions, total_bytes))

        for thread in threads:
            thread.join(timeout=3)

        # Close the pipes so the peer processes can terminate.
        for proc in (dump_proc, load_proc):
            for stream in (proc.stdin, proc.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:  # noqa: BLE001
                    pass
        dump_cleanup()
        load_cleanup()
        self._procs = [p for p in self._procs if p not in (dump_proc, load_proc)]

        if self._cancel.is_set():
            return False, "Migration cancelled by the user."

        self._log(
            f"Transfer finished: dump_rc={dump_proc.returncode}, load_rc={load_proc.returncode}, "
            f"bytes={stats['bytes']}."
        )
        if dump_proc.returncode != 0:
            return False, f"Source dump failed: {self._tail_text(dump_tail)}"
        if load_proc.returncode != 0:
            return False, f"Target load failed: {self._tail_text(load_tail)}"
        return True, "Repository transferred."

    def _pump(self, src, dst, stats: dict) -> None:
        """Copy the dump stream from the source into the target load's stdin."""
        if src is None or dst is None:
            return
        try:
            while not self._cancel.is_set():
                chunk = src.read(PUMP_CHUNK)
                if not chunk:
                    break
                stats["bytes"] += len(chunk)
                try:
                    dst.write(chunk)
                    dst.flush()
                except (BrokenPipeError, ValueError, OSError):
                    break
        except Exception as error:  # noqa: BLE001
            self._log(f"Pump error: {error}")
        finally:
            try:
                dst.close()
            except Exception:  # noqa: BLE001
                pass

    def _drain_lines(self, pipe, tail, load_progress, total_revisions, stats, total_bytes) -> None:
        if pipe is None:
            return
        try:
            for raw in iter(pipe.readline, b""):
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                tail.append(line)
                match = re.search(r"Committed revision (\d+)", line)
                if match:
                    revision = int(match.group(1))
                    load_progress["revision"] = revision
                    self._log(f"Committed revision {revision}" + (f"/{total_revisions}" if total_revisions else ""))
                    self._emit("stats", self._stats_snapshot(stats, load_progress, total_revisions, total_bytes))
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _drain_tail(pipe, tail) -> None:
        if pipe is None:
            return
        try:
            for raw in iter(pipe.readline, b""):
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    tail.append(line)
        except Exception:  # noqa: BLE001
            pass



