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
from dataclasses import replace
from typing import Callable, List, Dict, Optional, Tuple
from urllib.parse import urlsplit

from pathlib import Path
from .abstract_vcs import AbstractVCS
from .repository_admin import build_repository_admin, normalize_repo_name
from .svn_client import detect_svn_client
from .svn_errors import VcsError, classify_svn_error
from .svn_runner import SvnCommandRunner
from .vcs_audit import VcsAuditLogger
from .svn_xml import SvnStatusEntry, parse_log_xml, parse_status_xml
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
        self._local_ignores: List[str] = []
        self._svn_path = shutil.which("svn") or "svn"
        self._audit = VcsAuditLogger()
        self._runner = SvnCommandRunner(
            self._svn_path,
            audit=self._audit,
            project=self._project_label(),
            server=self._server_host(),
        )

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

    def _project_label(self) -> str:
        try:
            return Path(self.workspace_dir).resolve().parent.name
        except Exception:  # noqa: BLE001
            return ""

    def _server_host(self) -> str:
        try:
            return urlsplit(self.repo_url).hostname or ""
        except Exception:  # noqa: BLE001
            return ""

    def _audit_admin(
        self,
        operation: str,
        project_name: str,
        ok: bool,
        message: str,
        *,
        paths: Tuple[str, ...] = (),
    ) -> None:
        self._audit.log(
            operation,
            project=project_name,
            server=self._server_host(),
            paths=paths,
            ok=ok,
            message="" if ok else message,
        )

    def set_local_ignores(self, patterns: List[str]) -> None:
        """Apply project-local ignore patterns to every svn invocation."""
        self._local_ignores = [str(pattern).strip() for pattern in patterns or [] if str(pattern).strip()]

    def check_cli(self) -> Tuple[bool, str]:
        svn_status = detect_svn_client()
        if not svn_status.found:
            return False, svn_status.message
        if not svn_status.meets_minimum:
            return False, svn_status.message

        required: List[str] = []
        if self.server_profile.is_remote:
            required.extend(["ssh", "scp"])
        missing = [tool for tool in required if shutil.which(tool) is None]
        if missing:
            return False, "Missing required command-line tools on PATH: " + ", ".join(missing) + "."
        return True, "VCS command-line tools available."

    def _build_auth_args(self, username: Optional[str], password: Optional[str]) -> List[str]:
        """Build authentication arguments without caching them on disk."""
        args = ["--non-interactive", *self._tls_args()]

        # Local developer sandbox: inject the bootstrap credentials automatically.
        if self.server_profile.mode == LOCAL_DOCKER and "localhost" in self.repo_url:
            username = DEV_SVN_USER
            password = DEV_SVN_PASSWORD
            print(f"[SVNAdapter] BYPASS: Inyectando credenciales locales de SVN ({DEV_SVN_USER})...")

        if username and password:
            args.extend(["--username", username, "--password", password, "--no-auth-cache"])
        return args

    def _tls_args(self) -> List[str]:
        """Return TLS options for HTTPS URLs, failing closed on bad CA paths."""
        scheme = (urlsplit(self.repo_url).scheme or "").lower()
        if scheme not in ("https", "http"):
            return []

        profile = self.server_profile
        args: List[str] = []
        ca_file = str(getattr(profile, "ca_file", "") or "").strip()
        if ca_file:
            ca_path = Path(ca_file).expanduser()
            if not ca_path.exists():
                raise VcsError(f"The configured TLS CA file does not exist: {ca_path}")
            args.extend(
                [
                    "--config-option",
                    f"servers:global:ssl-authority-files={ca_path}",
                ]
            )
        if not bool(getattr(profile, "trust_default_ca", True)):
            args.extend(["--config-option", "servers:global:ssl-trust-default-ca=no"])
        failures = str(
            getattr(profile, "trust_server_cert_failures", "") or ""
        ).strip()
        if failures:
            args.extend(["--trust-server-cert-failures", failures])
        return args

    def _run_subprocess(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
        return_stderr: bool = False,
    ) -> str | Tuple[str, str]:
        """Run svn through the shared runner with timeout and typed errors."""
        args = list(cmd)
        if args and args[0] in ("svn", self._svn_path):
            args = args[1:]
        if self._local_ignores:
            args.extend(
                [
                    "--config-option",
                    "config:miscellany:global-ignores=" + " ".join(self._local_ignores),
                ]
            )
        args, stdin_text = self._password_from_stdin(args)
        result = self._runner.run(
            args,
            cwd=cwd,
            stdin_text=stdin_text,
            check=True,
            non_interactive=False,
        )
        if return_stderr:
            return result.stdout, result.stderr
        return result.stdout

    @staticmethod
    def _password_from_stdin(args: List[str]) -> Tuple[List[str], Optional[str]]:
        """Move ``--password VALUE`` to ``--password-from-stdin``."""
        if "--password" not in args:
            return args, None
        index = args.index("--password")
        password = args[index + 1] if index + 1 < len(args) else ""
        del args[index : index + 2]
        args.append("--password-from-stdin")
        return args, password + "\n"

    def cancel(self) -> None:
        """Cancel the running SVN process, if any."""
        self._runner.cancel()

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
        problems = [
            line for line in output.splitlines()
            if len(line) > 6 and any(marker in line[:7] for marker in ("C", "~", "B"))
        ]
        if problems:
            detail = "\n".join(problems[:10])
            raise RuntimeError(
                "The VCS working copy has unresolved conflicts or obstructed paths "
                "after the update. Resolve them (or ignore/move the untracked files) "
                "and retry. As a last resort, use 'Reset VCS Working Copy'.\n" + detail
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
        _stdout, stderr = self._run_subprocess(
            cmd, cwd=self.workspace_dir, return_stderr=True
        )
        # Some SVN versions report an already-held lock as a warning with a
        # zero exit code. Surface it as a typed error so the caller can offer
        # the stale-lock recovery action.
        if "W160035" in stderr or "E160039" in stderr:
            raise classify_svn_error(stderr, 1, cmd)
        return True

    def unlock(
        self,
        path: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        force: bool = False,
    ) -> bool:
        cmd = ["svn", "unlock", path]
        if force:
            cmd.append("--force")
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

    def resolve(self, path: str, accept: str = "working") -> bool:
        """Resolve a conflict, keeping the working copy or choosing one side."""
        allowed = {"working", "base", "mine-full", "theirs-full"}
        strategy = accept if accept in allowed else "working"
        cmd = ["svn", "resolve", f"--accept={strategy}", path]
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

    def get_status_entries(self, path: Optional[str] = None) -> List[SvnStatusEntry]:
        """Return structured ``svn status --xml`` entries for the workspace."""
        cmd = ["svn", "status", "--xml"]
        if path:
            cmd.append(path)
        output = self._run_subprocess(cmd, cwd=self.workspace_dir)
        entries = parse_status_xml(output)
        return [
            replace(entry, path=self._relative_status_path(entry.path))
            for entry in entries
        ]

    def _relative_status_path(self, path: str) -> str:
        try:
            return (
                Path(path)
                .resolve()
                .relative_to(Path(self.workspace_dir).resolve())
                .as_posix()
            )
        except Exception:  # noqa: BLE001 - keep the raw path for diagnostics
            return str(path).replace("\\", "/")

    def get_log(
        self,
        path: Optional[str] = None,
        limit: int = 20,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[dict]:
        """Return the most recent revisions that changed ``path``."""
        cmd = ["svn", "log", "--xml", "-l", str(max(1, int(limit)))]
        if path:
            cmd.append(path)
        cmd.extend(self._build_auth_args(username, password))
        output = self._run_subprocess(cmd, cwd=self.workspace_dir)
        return parse_log_xml(output)

    def get_diff(
        self,
        path: str,
        revision: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> str:
        """Return a textual diff for the working copy or a single revision."""
        cmd = ["svn", "diff"]
        if revision is not None:
            cmd.extend(["-c", str(revision)])
        cmd.append(path)
        cmd.extend(self._build_auth_args(username, password))
        return self._run_subprocess(cmd, cwd=self.workspace_dir)

    def export_revision(
        self,
        path: str,
        revision: int,
        destination: Path,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> bool:
        """Export one revision without modifying the working copy."""
        destination = Path(destination)
        args = ["cat", "-r", str(revision), path]
        args.extend(self._build_auth_args(username, password))
        args, stdin_text = self._password_from_stdin(args)
        self._runner.run_to_file(
            args,
            destination,
            cwd=self.workspace_dir,
            stdin_text=stdin_text,
        )
        return True

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
            ok, message = self.admin.destroy(repo_name, vfs_svn)
        except ValueError as error:
            self._audit_admin("repository.destroy", repo_name, False, str(error))
            return False, str(error)
        except RuntimeError as error:
            message = f"Failed to remove VCS repository: {error}"
            self._audit_admin("repository.destroy", repo_name, False, message)
            return False, message
        self._audit_admin("repository.destroy", repo_name, ok, message)
        return ok, message

    def ensure_server_policy(self, project_name: str) -> Tuple[bool, str]:
        """Install or refresh the server-side lock policy for this project."""
        repo_name = self._normalized_repo_name(project_name)
        try:
            ok, message = self.admin.ensure_policy(repo_name)
        except ValueError as error:
            self._audit_admin("repository.policy", repo_name, False, str(error))
            return False, str(error)
        except RuntimeError as error:
            message = f"Failed to apply the VCS policy: {error}"
            self._audit_admin("repository.policy", repo_name, False, message)
            return False, message
        self._audit_admin("repository.policy", repo_name, ok, message)
        return ok, message

    def list_server_locks(self, project_name: str) -> Tuple[bool, list, str]:
        """List repository locks for a project."""
        repo_name = self._normalized_repo_name(project_name)
        try:
            ok, locks, message = self.admin.list_locks(repo_name)
        except ValueError as error:
            self._audit_admin("locks.list", repo_name, False, str(error))
            return False, [], str(error)
        except RuntimeError as error:
            message = f"Failed to list locks: {error}"
            self._audit_admin("locks.list", repo_name, False, message)
            return False, [], message
        self._audit_admin(
            "locks.list",
            repo_name,
            ok,
            message,
            paths=tuple(str(lock.get("path", "")) for lock in locks or ()),
        )
        return ok, locks, message

    def break_server_lock(self, project_name: str, path: str) -> Tuple[bool, str]:
        """Remove a lock with server-side administrator privileges."""
        repo_name = self._normalized_repo_name(project_name)
        try:
            ok, message = self.admin.break_lock(repo_name, path)
        except ValueError as error:
            self._audit_admin("locks.break", repo_name, False, str(error), paths=(path,))
            return False, str(error)
        except RuntimeError as error:
            message = f"Failed to remove the lock: {error}"
            self._audit_admin("locks.break", repo_name, False, message, paths=(path,))
            return False, message
        self._audit_admin("locks.break", repo_name, ok, message, paths=(path,))
        return ok, message

    def create_server_repository(self, project_name: str, vfs_svn: str) -> bool:
        """Create the project repository on the configured server (Docker or VPS)."""
        repo_name = self._normalized_repo_name(project_name)
        try:
            ok = self.admin.create(repo_name, vfs_svn)
        except ValueError as error:
            self._audit_admin("repository.create", repo_name, False, str(error))
            print(f"[SVNAdapter] Invalid repository name: {error}")
            return False
        except RuntimeError as error:
            self._audit_admin("repository.create", repo_name, False, str(error))
            print(f"[SVNAdapter] Remote repository creation failed: {error}")
            return False
        self._audit_admin(
            "repository.create",
            repo_name,
            bool(ok),
            "" if ok else "Repository creation failed.",
        )
        return ok
