# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/vcs/ssh_runner.py
# Architectural role: Infrastructure / non-interactive OpenSSH command runner
# =========================================================================================

"""Non-interactive OpenSSH runner used for server-side provisioning.

We deliberately shell out to the system ``ssh``/``scp`` binaries instead of using
a Python SSH library so that OpenSSH certificates, the agent and
``known_hosts`` continue to work exactly as the studio configured them.

The SSH passphrase (when the private key is encrypted) is supplied through
``SSH_ASKPASS`` with ``SSH_ASKPASS_REQUIRE=force``. A throwaway helper script
that simply echoes an environment variable is generated per call and removed
afterwards, so the secret never touches disk.

Every invocation is traced (console + ``~/.openstudio/logs/ssh_<server>.log``)
so connection failures such as ``Permission denied (publickey)`` can be
diagnosed from the exact argv, the pre-flight state of the key/cert and the
full ``ssh`` stderr. The passphrase is never written to argv or logs; only the
boolean "passphrase present" is recorded.
"""

import base64
import contextlib
import os
import re
import shlex
import struct
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.domain.workspace.vcs_server_profile import RemoteSSHConfig

PassphraseProvider = Callable[[], Optional[str]]

ASKPASS_ENV_VAR = "OPENSTUDIO_SSH_ASKPASS"
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_LOG_DIR_ENV = "OPENSTUDIO_LOG_DIR"

# Flags whose following token is a secret and must never be echoed.
_SECRET_FLAGS = {"--password", "--passphrase", "--with-password"}


def resolve_log_dir() -> Path:
    """Directory where SSH diagnostics are written.

    ``OPENSTUDIO_LOG_DIR`` overrides the default (used by tests to stay
    hermetic); otherwise logs land in ``~/.openstudio/logs``.
    """
    override = os.environ.get(DEFAULT_LOG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".openstudio" / "logs"


def redact_args(args: List[str]) -> List[str]:
    """Mask any secret flag values in an argument list.

    SSH argv carries no secrets (the passphrase travels via ``SSH_ASKPASS``),
    but this guards against accidental leakage if a caller extends the list.
    """
    redacted: List[str] = []
    hide_next = False
    for token in args:
        if hide_next:
            redacted.append("********")
            hide_next = False
            continue
        redacted.append(token)
        if token in _SECRET_FLAGS:
            hide_next = True
    return redacted


def private_key_is_encrypted(path: str | Path) -> Optional[bool]:
    """Best-effort detection of an encrypted private key.

    Returns ``True``/``False`` when the key can be classified, or ``None`` when
    the file is unreadable or the format is not recognised. Never requires the
    passphrase and never mutates the key.
    """
    try:
        data = Path(path).expanduser().read_bytes()
    except OSError:
        return None

    head = data[:200]
    if b"ENCRYPTED" in head or b"DEK-Info:" in head:
        return True

    if b"-----BEGIN OPENSSH PRIVATE KEY-----" in data:
        try:
            text = data.decode("ascii", "ignore")
            body = text.split("-----BEGIN OPENSSH PRIVATE KEY-----", 1)[1]
            body = body.split("-----END", 1)[0]
            raw = base64.b64decode(re.sub(r"\s+", "", body))
            magic = b"openssh-key-v1\x00"
            index = raw.index(magic) + len(magic)
            (length,) = struct.unpack(">I", raw[index:index + 4])
            cipher = raw[index + 4:index + 4 + length].decode("ascii", "replace")
            return cipher != "none"
        except (ValueError, IndexError, struct.error):
            return None

    if b"PRIVATE KEY-----" in data:
        # Legacy PEM (RSA/DSA/EC) without Proc-Type means it is not encrypted.
        return False
    return None


def _key_permissions_warning(path: Path) -> Optional[str]:
    """Warn when a private key is group/world accessible (ssh will refuse it)."""
    if os.name == "nt":
        return None
    try:
        mode = path.stat().st_mode
    except OSError as error:
        return f"cannot stat key file: {error}"
    if mode & 0o077:
        return "permissions are too open (expected 600); ssh may refuse the key"
    return None


class SshDiagnostics:
    """Always-on tracer for a single :class:`SshRunner`.

    Records to the console and appends to ``ssh_<server>.log`` so repeated
    attempts against the same server stay together for diagnosis.
    """

    def __init__(self, label: str, log_dir: Optional[Path] = None) -> None:
        self.label = label or "ssh"
        self._log_dir = Path(log_dir).expanduser() if log_dir is not None else None
        self.log_path: Optional[Path] = None
        self.lines: List[str] = []
        self._opened = False
        self._failed = False

    def _directory(self) -> Path:
        return self._log_dir if self._log_dir is not None else resolve_log_dir()

    def _open(self) -> None:
        if self._opened:
            return
        self._opened = True
        try:
            directory = self._directory()
            directory.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", self.label) or "ssh"
            self.log_path = directory / f"ssh_{safe}.log"
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(
                    f"\n{'=' * 70}\nSSH session {stamp} :: {self.label}\n{'=' * 70}\n"
                )
        except OSError:
            self.log_path = None
            self._failed = True

    def record(self, message: str) -> None:
        self._open()
        self.lines.append(message)
        print(f"[SshRunner] {message}")
        if self.log_path is not None:
            try:
                with open(self.log_path, "a", encoding="utf-8") as handle:
                    handle.write(message + "\n")
            except OSError:
                pass


class SshRunner:
    """Builds and executes non-interactive SSH commands for a remote server."""

    def __init__(
        self,
        remote: RemoteSSHConfig,
        passphrase_provider: Optional[PassphraseProvider] = None,
        verbose: bool = False,
        log_dir: Optional[Path] = None,
        server_label: str = "",
    ) -> None:
        self.remote = remote
        self._passphrase_provider = passphrase_provider
        self.verbose = verbose
        self.diagnostics = SshDiagnostics(server_label or remote.host or "ssh", log_dir=log_dir)
        self._preflight_done = False
        self._key_encrypted: Optional[bool] = None

    # ------------------------------------------------------------------
    # Argument construction
    # ------------------------------------------------------------------
    def _passphrase(self) -> Optional[str]:
        if self._passphrase_provider is None:
            return None
        value = self._passphrase_provider()
        return value or None

    def _options(self, has_passphrase: bool) -> List[str]:
        remote = self.remote
        options = [
            "-o", f"ConnectTimeout={DEFAULT_CONNECT_TIMEOUT}",
            "-o", f"StrictHostKeyChecking={remote.strict_host_key or 'accept-new'}",
            "-o", "PreferredAuthentications=publickey",
        ]

        if has_passphrase:
            options += ["-o", "NumberOfPasswordPrompts=1"]
        else:
            options += ["-o", "BatchMode=yes"]

        if remote.ssh_key_path:
            options += ["-o", "IdentitiesOnly=yes", "-i", remote.ssh_key_path]
        if remote.ssh_cert_path:
            options += ["-o", f"CertificateFile={remote.ssh_cert_path}"]
        if remote.known_hosts_path:
            options += ["-o", f"UserKnownHostsFile={remote.known_hosts_path}"]

        return options

    def base_args(self, has_passphrase: bool = False) -> List[str]:
        target = f"{self.remote.ssh_user}@{self.remote.host}"
        args = ["ssh", "-p", str(self.remote.ssh_port)]
        if self.verbose:
            args.append("-v")
        args += self._options(has_passphrase)
        args += [target]
        return args

    def masked_args(self, has_passphrase: bool, remote_command: str = "") -> str:
        """Human-readable, secret-free rendering of the effective command."""
        args = self.base_args(has_passphrase=has_passphrase)
        if remote_command:
            args.append(remote_command)
        return " ".join(redact_args(args))

    def describe(self) -> str:
        remote = self.remote
        return (
            f"target={remote.ssh_user}@{remote.host} port={remote.ssh_port} "
            f"key={remote.ssh_key_path or '-'} cert={remote.ssh_cert_path or '-'} "
            f"known_hosts={remote.known_hosts_path or '-'} "
            f"container={remote.container or '-'} "
            f"strict_host_key={remote.strict_host_key} verbose={self.verbose}"
        )

    # ------------------------------------------------------------------
    # Pre-flight diagnostics
    # ------------------------------------------------------------------
    def _fingerprint(self, pubkey_path: Path) -> str:
        try:
            result = subprocess.run(
                ["ssh-keygen", "-lf", str(pubkey_path)],
                capture_output=True,
                text=True,
            )
        except OSError:
            return ""
        return (result.stdout or "").strip()

    def _run_preflight(self) -> None:
        if self._preflight_done:
            return
        self._preflight_done = True

        remote = self.remote
        self.diagnostics.record(f"invocation: {self.describe()}")

        if not remote.ssh_key_path:
            self.diagnostics.record("preflight: no explicit private key configured")
        else:
            key = Path(remote.ssh_key_path).expanduser()
            if not key.exists():
                self.diagnostics.record(f"preflight: private key NOT FOUND at {key}")
            else:
                self._key_encrypted = private_key_is_encrypted(key)
                state = {True: "encrypted", False: "unencrypted", None: "unknown"}[self._key_encrypted]
                warning = _key_permissions_warning(key)
                suffix = f", {warning}" if warning else ""
                self.diagnostics.record(f"preflight: private key {key} present ({state}){suffix}")
                pubkey = key.with_name(key.name + ".pub")
                if pubkey.exists():
                    self.diagnostics.record(
                        f"preflight: public key {pubkey} -> {self._fingerprint(pubkey) or 'fingerprint unavailable'}"
                    )

        if remote.ssh_cert_path:
            cert = Path(remote.ssh_cert_path).expanduser()
            self.diagnostics.record(
                f"preflight: certificate {'present' if cert.exists() else 'MISSING'} at {cert}"
            )
        if remote.known_hosts_path:
            known = Path(remote.known_hosts_path).expanduser()
            self.diagnostics.record(
                f"preflight: known_hosts {'present' if known.exists() else 'MISSING'} at {known}"
            )

    @staticmethod
    def _as_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", "replace")
        return str(value)

    def _record_completed(self, returncode, stdout, stderr) -> None:
        self.diagnostics.record(f"exit code: {returncode}")
        stdout_text = self._as_text(stdout).strip()
        stderr_text = self._as_text(stderr).strip()
        if stdout_text:
            self.diagnostics.record(f"stdout:\n{stdout_text}")
        if stderr_text:
            self.diagnostics.record(f"stderr:\n{stderr_text}")

    def _begin(self, remote_command: str) -> tuple[List[str], Optional[str]]:
        """Run pre-flight, resolve the passphrase and log the effective argv."""
        self._run_preflight()
        passphrase = self._passphrase()
        has_passphrase = bool(passphrase)
        self.diagnostics.record(f"passphrase present: {has_passphrase}")
        if self._key_encrypted and not has_passphrase:
            self.diagnostics.record(
                "hint: private key is encrypted but no passphrase was provided"
            )
        args = self.base_args(has_passphrase=has_passphrase)
        args.append(remote_command)
        self.diagnostics.record(f"argv: {self.masked_args(has_passphrase, remote_command)}")
        return args, passphrase

    # ------------------------------------------------------------------
    # Askpass helper
    # ------------------------------------------------------------------
    @staticmethod
    @contextlib.contextmanager
    def _askpass_environment(passphrase: str):
        if os.name == "nt":
            raise RuntimeError(
                "SSH passphrase automation is not supported on Windows OpenSSH. "
                "Use an ssh-agent or an unencrypted key for infrastructure tasks."
            )

        workdir = tempfile.mkdtemp(prefix="openstudio_askpass_")
        helper = os.path.join(workdir, "askpass.sh")
        with open(helper, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nprintf '%%s\\n' \"$%s\"\n" % (ASKPASS_ENV_VAR))
        os.chmod(helper, 0o700)

        env: Dict[str, str] = {
            "SSH_ASKPASS": helper,
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": os.environ.get("DISPLAY", "openstudio-hub"),
            ASKPASS_ENV_VAR: passphrase,
        }
        try:
            yield env
        finally:
            with contextlib.suppress(OSError):
                os.remove(helper)
            with contextlib.suppress(OSError):
                os.rmdir(workdir)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run(
        self,
        remote_command: str,
        input_data: Optional[bytes] = None,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess:
        if not self.remote.is_configured:
            raise RuntimeError(
                "Remote VCS server is not configured (missing host or SSH user)."
            )

        args, passphrase = self._begin(remote_command)

        env = dict(os.environ)
        context = (
            self._askpass_environment(passphrase)
            if passphrase
            else contextlib.nullcontext({})
        )
        with context as extra_env:
            env.update(extra_env)
            try:
                result = subprocess.run(
                    args,
                    input=input_data,
                    check=check,
                    capture_output=capture,
                    text=input_data is None,
                    env=env,
                )
            except subprocess.CalledProcessError as error:
                self._record_completed(error.returncode, error.stdout, error.stderr)
                raise
        self._record_completed(result.returncode, result.stdout, result.stderr)
        return result

    def run_capture(self, remote_command: str) -> str:
        """Run a command and return its stdout, raising on failure."""
        result = self.run(remote_command, check=True, capture=True)
        return result.stdout or ""

    def popen(
        self,
        remote_command: str,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ):
        """Start a command and return ``(process, cleanup)``.

        The caller MUST invoke ``cleanup()`` after the process exits so the
        temporary askpass helper (when a passphrase is used) is removed.
        """
        if not self.remote.is_configured:
            raise RuntimeError(
                "Remote VCS server is not configured (missing host or SSH user)."
            )

        args, passphrase = self._begin(remote_command)

        env = dict(os.environ)
        cleanup = lambda: None
        if passphrase:
            context = self._askpass_environment(passphrase)
            env.update(context.__enter__())

            def cleanup():
                context.__exit__(None, None, None)

        process = subprocess.Popen(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=env,
        )
        return process, cleanup

    def run_stream(self, remote_command: str, stdin) -> bytes:
        """Run a command feeding ``stdin`` (a binary stream), returning stdout."""
        if not self.remote.is_configured:
            raise RuntimeError(
                "Remote VCS server is not configured (missing host or SSH user)."
            )

        args, passphrase = self._begin(remote_command)

        env = dict(os.environ)
        context = (
            self._askpass_environment(passphrase)
            if passphrase
            else contextlib.nullcontext({})
        )
        with context as extra_env:
            env.update(extra_env)
            process = subprocess.Popen(
                args,
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            stdout, stderr = process.communicate()

        self._record_completed(process.returncode, stdout, stderr)
        if process.returncode != 0:
            raise RuntimeError(
                self._as_text(stderr).strip()
                or f"Remote command failed (exit {process.returncode})."
            )
        return stdout or b""

    @classmethod
    def quote(cls, value: str) -> str:
        """Shell-quote a value destined for the remote (POSIX) shell."""
        return shlex.quote(value)
