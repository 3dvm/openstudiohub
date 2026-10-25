# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/vcs/svn_runner.py
# Architectural role: VCS infrastructure / safe svn CLI execution
# =========================================================================================

"""Centralized, safe execution of the ``svn`` command-line client.

Every VCS operation should go through :class:`SvnCommandRunner` so timeouts,
cancellation, credential handling, output decoding and error classification are
consistent across the application.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from src.infrastructure.vcs.svn_errors import VcsError, classify_svn_error, extract_error_code
from src.infrastructure.vcs.vcs_audit import VcsAuditLogger

LOGGER = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 300.0
_LOCAL_TIMEOUT = 60.0
_PASSWORD_FLAG = "--password"
_PASSWORD_STDIN_FLAG = "--password-from-stdin"
_MASK = "********"


@dataclass(frozen=True)
class SvnResult:
    """Outcome of one ``svn`` invocation."""

    ok: bool
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    command: tuple[str, ...] = field(default_factory=tuple)

    def has_code(self, *codes: str) -> bool:
        text = f"{self.stdout}\n{self.stderr}"
        return any(code in text for code in codes)


_VALUE_OPTIONS = {
    "-m",
    "--message",
    "-r",
    "--revision",
    "-c",
    "--change",
    "-l",
    "--limit",
    "--username",
    "--password",
    "--config-option",
    "--depth",
    "--set-depth",
    "--accept",
    "--trust-server-cert-failures",
    "--changelist",
    "--cl",
    "-F",
    "--file",
    "--targets",
    "--with-revprop",
}
_REVISION_PATTERNS = (
    re.compile(r"Committed revision (\d+)"),
    re.compile(r"Updated to revision (\d+)"),
    re.compile(r"At revision (\d+)"),
    re.compile(r"revision (\d+)"),
)


def _operation(raw_args: Sequence[str]) -> str:
    return raw_args[0] if raw_args and not raw_args[0].startswith("-") else ""


def _option_value(raw_args: Sequence[str], option: str) -> str:
    for index, token in enumerate(raw_args):
        if token == option and index + 1 < len(raw_args):
            return raw_args[index + 1]
        if token.startswith(option + "="):
            return token.split("=", 1)[1]
    return ""


def _extract_paths(raw_args: Sequence[str]) -> tuple[str, ...]:
    paths: list[str] = []
    skip_next = False
    after_separator = False
    for index, token in enumerate(raw_args):
        if after_separator:
            paths.append(token)
            continue
        if token == "--":
            after_separator = True
            continue
        if index == 0 and not token.startswith("-"):
            continue
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            if "=" not in token and token in _VALUE_OPTIONS:
                skip_next = True
            continue
        paths.append(token)
    return tuple(paths)


def _extract_revision(stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}"
    for pattern in _REVISION_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


class SvnCommandRunner:
    """Runs ``svn`` without a shell, with timeout and cancellation."""

    def __init__(
        self,
        svn_path: str = "svn",
        *,
        default_timeout: float = _DEFAULT_TIMEOUT,
        local_timeout: float = _LOCAL_TIMEOUT,
        audit: Optional[VcsAuditLogger] = None,
        project: str = "",
        server: str = "",
    ) -> None:
        self.svn_path = str(svn_path or "svn")
        self.default_timeout = float(default_timeout)
        self.local_timeout = float(local_timeout)
        self.audit = audit
        self.project = str(project or "")
        self.server = str(server or "")
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        """Request cancellation and terminate the running process tree."""
        self._cancelled.set()
        with self._lock:
            process = self._process
        if process is not None:
            self._terminate(process)

    def reset(self) -> None:
        """Clear the cancellation flag before a new operation."""
        self._cancelled.clear()

    def auth_args(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        *,
        password_from_stdin: bool = True,
    ) -> tuple[list[str], Optional[str]]:
        """Build non-interactive authentication arguments.

        ``--password-from-stdin`` keeps the password out of the process list and
        logs. Callers must pass the returned ``stdin_text`` to :meth:`run`.
        """
        args: list[str] = []
        stdin_text: Optional[str] = None
        if username:
            args.extend(["--username", username])
        if password:
            if password_from_stdin:
                args.append(_PASSWORD_STDIN_FLAG)
                stdin_text = password
            else:
                args.extend([_PASSWORD_FLAG, password])
        args.extend(["--no-auth-cache"])
        return args, stdin_text

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Optional[Path | str] = None,
        timeout: Optional[float] = None,
        stdin_text: Optional[str] = None,
        check: bool = True,
        non_interactive: bool = True,
        extra_env: Optional[dict[str, str]] = None,
    ) -> SvnResult:
        """Run ``svn`` with ``args`` and return its decoded result.

        Raises a typed :class:`VcsError` when ``check`` is true and the command
        exits non-zero.
        """
        self.reset()
        raw_args = [str(arg) for arg in args]
        command = [self.svn_path, *raw_args]
        if (
            non_interactive
            and raw_args
            and not raw_args[0].startswith("--")
            and not _has_flag(command, "--non-interactive")
        ):
            command = [self.svn_path, raw_args[0], "--non-interactive", *raw_args[1:]]

        effective_timeout = timeout
        if effective_timeout is None:
            effective_timeout = self.default_timeout

        env = os.environ.copy()
        env.setdefault("LC_ALL", "C")
        env.setdefault("LANG", "C")
        if extra_env:
            env.update({str(key): str(value) for key, value in extra_env.items()})

        LOGGER.debug("Running svn command: %s", _masked_command(command))
        started = time.monotonic()
        popen_kwargs: dict = {
            "cwd": str(cwd) if cwd is not None else None,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            popen_kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(command, **popen_kwargs)
        except FileNotFoundError as error:
            self._audit_failure(raw_args, str(error), cwd, returncode=-1)
            raise VcsError(
                f"The '{self.svn_path}' command was not found.",
                command=tuple(command),
            ) from error
        except OSError as error:
            self._audit_failure(raw_args, str(error), cwd, returncode=-1)
            raise VcsError(
                f"Could not start the Subversion client: {error}",
                command=tuple(command),
            ) from error

        with self._lock:
            self._process = process

        try:
            stdout_bytes, stderr_bytes = process.communicate(
                input=(stdin_text.encode("utf-8") if stdin_text is not None else None),
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired:
            self._terminate(process)
            stdout_bytes, stderr_bytes = process.communicate()
            duration = time.monotonic() - started
            message = f"Subversion command timed out after {effective_timeout:.0f} seconds."
            self._audit_failure(raw_args, message, cwd, returncode=-1)
            raise VcsError(
                message,
                raw=_decode(stderr_bytes),
                command=tuple(command),
            )
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None

        duration = time.monotonic() - started
        stdout = _decode(stdout_bytes)
        stderr = _decode(stderr_bytes)
        result = SvnResult(
            ok=process.returncode == 0,
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
            duration=duration,
            command=tuple(command),
        )
        LOGGER.debug(
            "svn exit=%s duration=%.3fs stderr=%s",
            result.returncode,
            result.duration,
            stderr.strip()[:400],
        )

        self._audit_result(raw_args, result, cwd)
        if check and not result.ok:
            raise classify_svn_error(stderr, result.returncode, command)
        return result

    def run_to_file(
        self,
        args: Sequence[str],
        destination: Path | str,
        *,
        cwd: Optional[Path | str] = None,
        timeout: Optional[float] = None,
        stdin_text: Optional[str] = None,
        check: bool = True,
        non_interactive: bool = True,
    ) -> SvnResult:
        """Run ``svn`` writing stdout to a binary file (for ``svn cat``)."""
        self.reset()
        raw_args = [str(arg) for arg in args]
        command = [self.svn_path, *raw_args]
        if (
            non_interactive
            and raw_args
            and not raw_args[0].startswith("--")
            and not _has_flag(command, "--non-interactive")
        ):
            command = [self.svn_path, raw_args[0], "--non-interactive", *raw_args[1:]]

        effective_timeout = timeout if timeout is not None else self.default_timeout
        env = os.environ.copy()
        env.setdefault("LC_ALL", "C")
        env.setdefault("LANG", "C")
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        LOGGER.debug("Running svn command: %s", _masked_command(command))
        started = time.monotonic()
        try:
            with open(destination_path, "wb") as handle:
                process = subprocess.run(
                    command,
                    cwd=str(cwd) if cwd is not None else None,
                    input=(stdin_text.encode("utf-8") if stdin_text is not None else None),
                    stdout=handle,
                    stderr=subprocess.PIPE,
                    timeout=effective_timeout,
                    env=env,
                    check=False,
                )
        except subprocess.TimeoutExpired as error:
            try:
                destination_path.unlink(missing_ok=True)
            except OSError:
                pass
            message = f"Subversion command timed out after {effective_timeout:.0f} seconds."
            self._audit_failure(raw_args, message, cwd, returncode=-1)
            raise VcsError(
                message,
                command=tuple(command),
            ) from error

        duration = time.monotonic() - started
        stderr = _decode(process.stderr)
        result = SvnResult(
            ok=process.returncode == 0,
            returncode=process.returncode,
            stdout="",
            stderr=stderr,
            duration=duration,
            command=tuple(command),
        )
        self._audit_result(raw_args, result, cwd)
        if not result.ok:
            try:
                destination_path.unlink(missing_ok=True)
            except OSError:
                pass
            if check:
                raise classify_svn_error(stderr, result.returncode, command)
        return result

    def run_xml(
        self,
        args: Sequence[str],
        *,
        cwd: Optional[Path | str] = None,
        timeout: Optional[float] = None,
        check: bool = True,
    ) -> tuple[SvnResult, str]:
        """Run a command that supports ``--xml`` and return the XML payload."""
        command = [str(arg) for arg in args]
        if "--xml" not in command:
            if command and not command[0].startswith("--"):
                command = [command[0], "--xml", *command[1:]]
            else:
                command.append("--xml")
        result = self.run(command, cwd=cwd, timeout=timeout, check=check)
        return result, result.stdout

    def _audit_failure(
        self,
        raw_args: Sequence[str],
        message: str,
        cwd: Optional[Path | str],
        *,
        returncode: int = 0,
    ) -> None:
        if self.audit is None:
            return
        self.audit.log(
            _operation(raw_args),
            project=self.project,
            server=self.server,
            user=_option_value(raw_args, "--username"),
            paths=_extract_paths(raw_args),
            cwd=str(cwd or ""),
            ok=False,
            returncode=returncode,
            message=message,
            command=raw_args,
        )

    def _audit_result(
        self,
        raw_args: Sequence[str],
        result: SvnResult,
        cwd: Optional[Path | str],
    ) -> None:
        if self.audit is None:
            return
        self.audit.log(
            _operation(raw_args),
            project=self.project,
            server=self.server,
            user=_option_value(raw_args, "--username"),
            paths=_extract_paths(raw_args),
            cwd=str(cwd or ""),
            ok=result.ok,
            returncode=result.returncode,
            error_code=extract_error_code(result.stderr),
            revision=_extract_revision(result.stdout, result.stderr),
            duration_ms=int(result.duration * 1000),
            message="" if result.ok else _first_line(result.stderr),
            command=raw_args,
        )

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001 - cancellation is best effort
            try:
                process.kill()
            except Exception:  # noqa: BLE001
                pass


def _has_flag(command: Iterable[str], flag: str) -> bool:
    return any(str(part) == flag for part in command)


def _decode(value: Optional[bytes]) -> str:
    if not value:
        return ""
    return value.decode("utf-8", "replace")


def _masked_command(command: Sequence[str]) -> str:
    masked: list[str] = []
    skip_next = False
    for token in command:
        if skip_next:
            masked.append(_MASK)
            skip_next = False
            continue
        masked.append(token)
        if token == _PASSWORD_FLAG:
            skip_next = True
    return " ".join(masked)
