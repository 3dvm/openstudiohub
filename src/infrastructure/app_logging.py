"""Process-wide log capture for the desktop application.

The Hub historically wrote diagnostics with ``print()`` only, so a native crash
left nothing behind. This module mirrors stdout/stderr to a per-run file and
arms :mod:`faulthandler` against that same file so a SIGSEGV produces a native
Python traceback.
"""

from __future__ import annotations

import faulthandler
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

LOG_DIR_ENV = "OPENSTUDIO_LOG_DIR"
_KEEP_LOGS = 20

_original_stdout = None
_original_stderr = None
_log_stream = None
_log_path: Optional[Path] = None


def resolve_log_dir(log_dir: Optional[Path] = None) -> Path:
    if log_dir is not None:
        return Path(log_dir)
    override = os.environ.get(LOG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".openstudio" / "logs"


class _TeeStream:
    """Write to the original console stream and to the run log file."""

    def __init__(self, original, log_stream) -> None:
        self._original = original
        self._log = log_stream

    def write(self, text: str) -> int:
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:  # noqa: BLE001 - console streams can disappear
                pass
        if self._log is not None:
            try:
                self._log.write(text)
                self._log.flush()
            except Exception:  # noqa: BLE001 - logging must never crash the app
                pass
        return len(text)

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:  # noqa: BLE001
                pass
        if self._log is not None:
            try:
                self._log.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self) -> bool:
        if self._original is None:
            return False
        try:
            return bool(self._original.isatty())
        except Exception:  # noqa: BLE001
            return False

    def fileno(self) -> int:
        if self._original is None:
            raise OSError("stream has no file descriptor")
        return self._original.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._original, "encoding", "utf-8") or "utf-8"


def configure_logging(log_dir: Optional[Path] = None) -> Optional[Path]:
    """Mirror console output to a run log and enable ``faulthandler``.

    Returns the log path, or ``None`` when the log directory is not writable.
    """
    global _original_stdout, _original_stderr, _log_stream, _log_path

    if _log_stream is not None:
        return _log_path

    directory = resolve_log_dir(log_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = directory / f"hub_{stamp}.log"
        stream = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return None

    _original_stdout = sys.stdout
    _original_stderr = sys.stderr
    _log_stream = stream
    _log_path = path

    faulthandler.enable(file=stream, all_threads=True)
    sys.stdout = _TeeStream(_original_stdout, stream)
    sys.stderr = _TeeStream(_original_stderr, stream)

    _prune_old_logs(directory)
    return path


def shutdown_logging() -> None:
    """Restore the original streams and close the run log."""
    global _original_stdout, _original_stderr, _log_stream, _log_path

    faulthandler.disable()
    if _original_stdout is not None:
        sys.stdout = _original_stdout
    if _original_stderr is not None:
        sys.stderr = _original_stderr
    if _log_stream is not None:
        try:
            _log_stream.flush()
            _log_stream.close()
        except Exception:  # noqa: BLE001
            pass

    _original_stdout = None
    _original_stderr = None
    _log_stream = None
    _log_path = None


def _prune_old_logs(directory: Path) -> None:
    try:
        logs = sorted(
            directory.glob("hub_*.log"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in logs[_KEEP_LOGS:]:
        try:
            stale.unlink()
        except OSError:
            continue
