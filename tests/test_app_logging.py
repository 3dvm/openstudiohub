"""Unit tests for the process-wide run log and crash handler."""

import faulthandler
import sys

from src.infrastructure.app_logging import configure_logging, shutdown_logging


def test_configure_logging_tees_output_and_writes_file(tmp_path):
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    try:
        path = configure_logging(tmp_path)
        assert path is not None
        assert path.exists()
        assert faulthandler.is_enabled() is True

        print("hello-from-log-test")
        sys.stdout.flush()
    finally:
        shutdown_logging()
        sys.stdout = original_stdout
        sys.stderr = original_stderr

    assert "hello-from-log-test" in path.read_text(encoding="utf-8")
