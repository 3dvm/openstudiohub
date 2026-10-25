"""Unit tests for the safe SVN command runner."""

import pytest

from src.infrastructure.vcs.svn_errors import SvnAuthError, VcsError
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
