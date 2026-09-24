# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/vcs_adapters/svn_adapter.py
# Rol Arquitectónico: Adaptador VCS / Capa de Abstracción
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.6.0
# =========================================================================================

"""
Concrete adapter for Subversion (SVN) operations via CLI.
Implements the Sparse Checkout mechanism to orchestrate Vendor Jailing.
Anchored to English standard.

Server-side repository lifecycle (create/destroy) is delegated to a
``RepositoryAdmin`` strategy selected by the configured ``VCSServerProfile``,
so the same adapter drives both the local Docker sandbox and a remote VPS
administered over OpenSSH.
"""

import shutil
import socket
import subprocess
from typing import Callable, List, Dict, Optional, Tuple
from urllib.parse import urlsplit

from pathlib import Path
from .abstract_vcs import AbstractVCS
from .repository_admin import build_repository_admin, normalize_repo_name
from src.domain.workspace.vcs_server_profile import LOCAL_DOCKER, VCSServerProfile
from src.infrastructure.dev_defaults import DEV_SVN_USER, DEV_SVN_PASSWORD

SVN_DEFAULT_PORTS = {
    "svn": 3690,
    "svn+ssh": 22,
    "http": 80,
    "https": 443,
}

class SVNAdapter(AbstractVCS):
    """Concrete adapter for Subversion (SVN) operations via CLI."""

    def __init__(
        self,
        repo_url: str,
        workspace_dir: Path,
        server_profile: Optional[VCSServerProfile] = None,
        ssh_passphrase_provider: Optional[Callable[[], Optional[str]]] = None,
    ):
        super().__init__(repo_url, workspace_dir, server_profile)
        self._ssh_passphrase_provider = ssh_passphrase_provider
        self._admin = None

    # ------------------------------------------------------------------
    # Server-admin strategy
    # ------------------------------------------------------------------
    @property
    def admin(self):
        if self._admin is None:
            self._admin = build_repository_admin(
                self.server_profile,
                ssh_passphrase_provider=self._ssh_passphrase_provider,
            )
        return self._admin

    def check_cli(self) -> Tuple[bool, str]:
        required = ["svn"]
        if self.server_profile.is_remote:
            required.extend(["ssh", "scp"])
        missing = [tool for tool in required if shutil.which(tool) is None]
        if missing:
            return False, "Missing required command-line tools on PATH: " + ", ".join(missing) + "."
        return True, "VCS command-line tools available."

    def _build_auth_args(self, username: Optional[str], password: Optional[str]) -> List[str]:
        """Builds authentication arguments without caching them on disk."""
        args = ["--non-interactive", "--trust-server-cert"]

        # Local developer sandbox: inject the bootstrap credentials automatically.
        if self.server_profile.mode == LOCAL_DOCKER and "localhost" in self.repo_url:
            username = DEV_SVN_USER
            password = DEV_SVN_PASSWORD
            print(f"[SVNAdapter] BYPASS: Inyectando credenciales locales de SVN ({DEV_SVN_USER})...")

        if username and password:
            args.extend(["--username", username, "--password", password, "--no-auth-cache"])
        return args

    def _run_subprocess(self, cmd: List[str], cwd: Optional[Path] = None) -> str:
        """Secure wrapper to execute subprocesses and capture errors."""
        cwd_path = str(cwd) if cwd else None

        # === DEBUG MODE: Security mask to avoid printing the password in the console ===
        safe_cmd = []
        skip_next = False
        for token in cmd:
            if skip_next:
                safe_cmd.append("********")
                skip_next = False
            elif token == "--password":
                safe_cmd.append(token)
                skip_next = True
            else:
                safe_cmd.append(token)

        print(f"\n[SVN DEBUG] Executing (CWD: {cwd_path or 'Current'}):")
        print(f" -> {' '.join(safe_cmd)}")
        # ==============================================================================

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd_path,
                check=True,
                capture_output=True,
                text=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            # Captures the real stderr from SVN (e.g., Incorrect Password) to pass it to the UI/Console
            error_msg = e.stderr.strip() if e.stderr else str(e)
            print(f"[SVN FATAL ERROR] Code {e.returncode}: {error_msg}\n")
            raise RuntimeError(f"SVN Failure: {error_msg}")

    def full_pull(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        # If the folder already exists and is an SVN repo, perform an update
        if (self.workspace_dir / ".svn").exists():
            cmd = ["svn", "update"]
            cmd.extend(self._build_auth_args(username, password))
            self._run_subprocess(cmd, cwd=self.workspace_dir)
        else:
            # Otherwise, perform a full checkout
            cmd = ["svn", "checkout", self.repo_url, str(self.workspace_dir)]
            cmd.extend(self._build_auth_args(username, password))
            self._run_subprocess(cmd)
        self._assert_no_conflicts()
        return True

    def _assert_no_conflicts(self) -> None:
        """Fail loudly when the checkout/update left SVN conflicts behind.

        A common cause is a locally pre-created ``<vfs>`` folder tree shadowing
        the incoming versioned folders ("local unversioned, incoming dir add
        upon update"). Surfacing it here points the user at the recovery action
        instead of leaving a silently broken working copy.
        """
        try:
            output = self._run_subprocess(["svn", "status"], cwd=self.workspace_dir)
        except Exception:  # noqa: BLE001 - status is best-effort diagnostics
            return
        conflicts = [
            line for line in output.splitlines()
            if len(line) > 6 and "C" in line[:7]
        ]
        if conflicts:
            detail = "\n".join(conflicts[:10])
            raise RuntimeError(
                "The VCS working copy has conflicts after the update (often caused "
                "by local folders shadowing incoming versioned folders). Use "
                "'Reset VCS Working Copy' for this project and retry.\n" + detail
            )

    def sparse_pull(self, paths: List[str], username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Restrictive download (Jailing) for Vendors."""
        # 1. Empty checkout (Fetches only structure, no files)
        if not (self.workspace_dir / ".svn").exists():
            cmd_co = ["svn", "checkout", "--depth", "empty", self.repo_url, str(self.workspace_dir)]
            cmd_co.extend(self._build_auth_args(username, password))
            self._run_subprocess(cmd_co)

        # 2. Download only the approved directories in the paths list
        for path in paths:
            cmd_up = ["svn", "update", "--set-depth", "infinity", "--parents", path]
            cmd_up.extend(self._build_auth_args(username, password))
            self._run_subprocess(cmd_up, cwd=self.workspace_dir)

        return True

    def commit(self, message: str, paths: Optional[List[str]] = None, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        cmd = ["svn", "commit", "-m", message]
        if paths:
            cmd.extend(paths)
        cmd.extend(self._build_auth_args(username, password))
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def lock(self, path: str, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        cmd = ["svn", "lock", path]
        cmd.extend(self._build_auth_args(username, password))
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def unlock(self, path: str, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        cmd = ["svn", "unlock", path]
        cmd.extend(self._build_auth_args(username, password))
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def get_lock_info(self, path: str) -> Optional[Dict[str, str]]:
        """Return lock metadata for ``path`` (``svn info`` on the working copy)."""
        output = self._run_subprocess(["svn", "info", path], cwd=self.workspace_dir)
        info: Dict[str, str] = {}
        for line in output.splitlines():
            key, separator, value = line.partition(":")
            if not separator:
                continue
            key = key.strip()
            value = value.strip()
            if key == "Lock Owner":
                info["owner"] = value
            elif key == "Lock Token":
                info["token"] = value
            elif key == "Lock Comment":
                info["comment"] = value
            elif key == "Lock Created":
                info["created"] = value
        return info or None

    def revert(self, path: str) -> bool:
        cmd = ["svn", "revert", "-R", path]
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def relocate(self, new_url: str, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Repoint this working copy at ``new_url`` (repository UUID must match)."""
        cmd = ["svn", "relocate", new_url]
        cmd.extend(self._build_auth_args(username, password))
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def get_status(self, path: Optional[str] = None) -> Dict[str, str]:
        cmd = ["svn", "status"]
        if path:
            cmd.append(path)
        output = self._run_subprocess(cmd, cwd=self.workspace_dir)
        # Raw parsing to return dict: {'A': 'path/file.blend', 'M': 'path/other.blend'}
        status_dict = {}
        for line in output.splitlines():
            if len(line) > 8:
                state = line[0]
                file_path = line[8:].strip()
                status_dict[file_path] = state
        return status_dict

    def set_needs_lock(self, path: str) -> bool:
        """
        Applies the svn:needs-lock property recursively to the specified path.
        Forces the VCS to keep the file in 'Read-Only' mode until an authorized user locks it.
        """
        cmd = ["svn", "propset", "svn:needs-lock", "yes", "-R", path]
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def cleanup(self) -> bool:
        """
        Sanitizes the local internal VCS database to resolve local locks
        caused by abrupt power outages, network drops, or forced closures.
        """
        if self.workspace_dir.exists():
            cmd = ["svn", "cleanup"]
            self._run_subprocess(cmd, cwd=self.workspace_dir)
            return True
        return False

    def setup_ignore(self, patterns: List[str]) -> bool:
        """Aplica la propiedad svn:ignore sobre la raíz del workspace."""
        if not (self.workspace_dir / ".svn").exists():
            return False

        # Escribimos un archivo temporal con los patrones
        ignore_file = self.workspace_dir / ".svn_ignore_temp"
        with open(ignore_file, "w", encoding="utf-8") as f:
            f.write("\n".join(patterns) + "\n")

        # Aplicamos la propiedad de SVN leyendo el archivo
        cmd = ["svn", "propset", "svn:ignore", "-F", str(ignore_file), "."]
        self._run_subprocess(cmd, cwd=self.workspace_dir)

        # Limpieza del temporal
        ignore_file.unlink(missing_ok=True)
        return True

    def add_all(self, path: str = ".") -> bool:
        """Registra archivos forzando la recursividad, ignorando los no-versionados por regla."""
        cmd = ["svn", "add", "--force", path]
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def add(self, paths: List[str]) -> bool:
        """Registra explícitamente una selección de archivos nuevos para commit."""
        selected = [path for path in paths if path]
        if not selected:
            return True
        cmd = ["svn", "add", "--force", "--parents", *selected]
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def _server_endpoint(self) -> Tuple[str, int]:
        """Derives the (host, port) of the VCS server from the repository URL."""
        parsed = urlsplit(self.repo_url)
        scheme = (parsed.scheme or "svn").lower()
        host = parsed.hostname or "localhost"
        port = parsed.port or SVN_DEFAULT_PORTS.get(scheme, 3690)
        return host, port

    def check_server_health(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 5.0,
    ) -> Tuple[bool, str]:
        """Pre-flight probe: confirms the SVN server is reachable before writing."""
        cli_ok, cli_message = self.check_cli()
        if not cli_ok:
            return False, cli_message

        host, port = self._server_endpoint()

        if self.server_profile.mode == LOCAL_DOCKER and host in ("localhost", "127.0.0.1"):
            if not self._docker_container_running():
                return (
                    False,
                    f"Local VCS server (Docker '{self.server_profile.local_container}') is not running. "
                    f"Start it from the Infrastructure panel and retry.",
                )

        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
            return True, f"VCS server reachable at {host}:{port}."
        except OSError as error:
            return False, f"VCS server unreachable at {host}:{port}: {error}"

    def _docker_container_running(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", self.server_profile.local_container],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip().lower() == "true"
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _normalized_repo_name(repository_name: str) -> str:
        """
        Canonical repository directory name.

        Must match the first path segment of the checkout URL, which is built from
        the lowercased project folder name. Normalizing here prevents a display
        name (e.g. ``MIDEQ_promo``) from creating a server repository that the
        checkout URL (``mideq_promo``) cannot find.
        """
        return normalize_repo_name(repository_name)

    def destroy_server_repository(self, project_name: str, vfs_svn: str) -> Tuple[bool, str]:
        """Rollback of the server-side repository (local Docker or remote SSH)."""
        repo_name = self._normalized_repo_name(project_name)
        try:
            return self.admin.destroy(repo_name, vfs_svn)
        except ValueError as error:
            return False, str(error)
        except RuntimeError as error:
            return False, f"Failed to remove VCS repository: {error}"

    def create_server_repository(self, project_name: str, vfs_svn: str) -> bool:
        """Create the project repository on the configured server (Docker or VPS)."""
        repo_name = self._normalized_repo_name(project_name)
        try:
            return self.admin.create(repo_name, vfs_svn)
        except ValueError as error:
            print(f"[SVNAdapter] Invalid repository name: {error}")
            return False
        except RuntimeError as error:
            print(f"[SVNAdapter] Remote repository creation failed: {error}")
            return False
