"""Unit tests for the safe SVN command runner."""

import pytest

from src.infrastructure.vcs.svn_errors import (
    SvnAuthError,
    SvnEncodingError,
    VcsError,
    classify_svn_error,
)
from src.infrastructure.vcs.svn_runner import SvnCommandRunner


def test_runner_returns_stdout_and_exit_code():
    runner = SvnCommandRunner("/bin/echo")

    result = runner.run(["hello"], non_interactive=False)

    assert result.ok is True
    assert result.returncode == 0
    assert "hello" in result.stdout


def test_runner_classifies_failures():
    runner = SvnCommandRunner("/bin/sh")

    with pytest.raises(SvnAuthError):
        runner.run(
            ["-c", "echo 'svn: E170001: Authorization failed' >&2; exit 1"],
            non_interactive=False,
        )


def test_runner_reports_timeouts():
    runner = SvnCommandRunner("/bin/sleep")

    with pytest.raises(VcsError) as error:
        runner.run(["2"], timeout=0.1, non_interactive=False)

    assert "timed out" in str(error.value).lower()


def test_auth_args_use_stdin_for_the_password():
    runner = SvnCommandRunner("/bin/echo")

    args, stdin_text = runner.auth_args("artist", "secret")

    assert "--password-from-stdin" in args
    assert "secret" not in args
    assert stdin_text == "secret"


def test_runner_can_skip_audit_for_expected_probes(tmp_path):
    from src.infrastructure.vcs.vcs_audit import VcsAuditLogger

    logger = VcsAuditLogger(tmp_path / "audit.jsonl")
    runner = SvnCommandRunner("/bin/sh", audit=logger)

    result = runner.run(
        ["-c", "echo 'svn: W155010: not found' >&2; exit 1"],
        non_interactive=False,
        check=False,
        audit=False,
    )

    assert result.ok is False
    assert logger.read_recent() == []


def test_encoding_errors_surface_the_specific_cause():
    error = classify_svn_error(
        "svn: E000022: Commit failed (details follow):\n"
        "svn: E000022: Can't convert string from 'UTF-8' to native encoding\n",
        1,
    )

    assert isinstance(error, SvnEncodingError)
    assert "convert string" in str(error)


def test_encoding_errors_prefer_the_conversion_line():
    error = classify_svn_error(
        "svn: E000022: Error normalizing log message to internal format\n"
        "svn: E000022: Can't convert string from native encoding to 'UTF-8':\n"
        "svn: E000022: camara\n",
        1,
    )

    assert isinstance(error, SvnEncodingError)
    assert "convert string" in str(error)


def test_runner_forces_the_configured_locale():
    runner = SvnCommandRunner("/bin/sh", locale="en_US.UTF-8")

    result = runner.run(["-c", 'printf "%s" "$LC_ALL"'], non_interactive=False)

    assert result.stdout == "en_US.UTF-8"


def test_runner_inherits_the_environment_when_no_locale_is_configured(monkeypatch):
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    runner = SvnCommandRunner("/bin/sh")

    result = runner.run(["-c", 'printf "%s" "$LC_ALL"'], non_interactive=False)

    assert result.stdout == "en_US.UTF-8"
