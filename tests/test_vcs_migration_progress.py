"""Unit tests for the migration progress helpers and the progress dialog."""

import io

from src.application.services.vcs_migration_service import VCSMigrationService


class _Sink:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, chunk) -> int:
        self.data.extend(chunk)
        return len(chunk)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _Proc:
    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def _service() -> VCSMigrationService:
    return VCSMigrationService(config_factory=object())


def test_stats_snapshot_uses_revisions():
    service = _service()
    stats = {"bytes": 0, "start": 0.0}

    snapshot = service._stats_snapshot(stats, {"revision": 6}, total_revisions=12, total_bytes=None)

    assert snapshot["revision"] == 6
    assert 8 <= snapshot["percent"] <= 90


def test_pump_copies_bytes_and_closes_destination():
    service = _service()
    source = io.BytesIO(b"x" * 4096)
    sink = _Sink()
    stats = {"bytes": 0, "start": 0.0}

    service._pump(source, sink, stats)

    assert stats["bytes"] == 4096
    assert bytes(sink.data) == b"x" * 4096
    assert sink.closed is True


def test_cancel_sets_flag_and_kills_processes():
    service = _service()
    proc = _Proc()
    service._procs.append(proc)

    service.cancel()

    assert service._cancel.is_set() is True
    assert proc.killed is True


def test_dialog_updates_and_finalizes(qapp):
    from src.interfaces.qt.components.migration_progress_dialog import MigrationProgressDialog

    dialog = MigrationProgressDialog(None, "Neon", {"name": "Local"}, {"name": "VPS"})
    dialog.update_detail({
        "percent": 42, "revision": 5, "total": 10, "speed": 1048576, "eta": 12, "elapsed": 3,
    })

    assert dialog.progress.value() == 42
    assert "rev 5/10" in dialog.lbl_stats.text()

    dialog.finalize(True, "all good")
    assert dialog.btn_cancel.isHidden() is True
    assert dialog.btn_close.isHidden() is False
    assert dialog.btn_close is not None
