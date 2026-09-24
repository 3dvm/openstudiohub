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
"""

import contextlib
import os
import shlex
import subprocess
import tempfile
from typing import Callable, Dict, List, Optional

from src.domain.workspace.vcs_server_profile import RemoteSSHConfig

PassphraseProvider = Callable[[], Optional[str]]

ASKPASS_ENV_VAR = "OPENSTUDIO_SSH_ASKPASS"
DEFAULT_CONNECT_TIMEOUT = 10


class SshRunner:
    """Builds and executes non-interactive SSH commands for a remote server."""

    def __init__(
        self,
        remote: RemoteSSHConfig,
        passphrase_provider: Optional[PassphraseProvider] = None,
    ) -> None:
        self.remote = remote
        self._passphrase_provider = passphrase_provider

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
        args += self._options(has_passphrase)
        args += [target]
        return args

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

        passphrase = self._passphrase()
        args = self.base_args(has_passphrase=bool(passphrase))
        args.append(remote_command)

        env = dict(os.environ)
        context = (
            self._askpass_environment(passphrase)
            if passphrase
            else contextlib.nullcontext({})
        )
        with context as extra_env:
            env.update(extra_env)
            return subprocess.run(
                args,
                input=input_data,
                check=check,
                capture_output=capture,
                text=input_data is None,
                env=env,
            )

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

        passphrase = self._passphrase()
        args = self.base_args(has_passphrase=bool(passphrase))
        args.append(remote_command)

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

        passphrase = self._passphrase()
        args = self.base_args(has_passphrase=bool(passphrase))
        args.append(remote_command)

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

        if process.returncode != 0:
            raise RuntimeError(
                (stderr or b"").decode("utf-8", "replace").strip()
                or f"Remote command failed (exit {process.returncode})."
            )
        return stdout or b""

    @classmethod
    def quote(cls, value: str) -> str:
        """Shell-quote a value destined for the remote (POSIX) shell."""
        return shlex.quote(value)
