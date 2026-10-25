"""Unit tests for the TD VCS audit widget."""

# Import the views package first: the widgets package has an eager import cycle.
import src.interfaces.qt.views  # noqa: F401

from src.infrastructure.vcs.vcs_audit import VcsAuditLogger
from src.interfaces.qt.viewmodels.vcs_audit_viewmodel import VcsAuditViewModel
from src.interfaces.qt.widgets.vcs_audit_widget import VcsAuditWidget


def _widget(tmp_path, qapp):
    logger = VcsAuditLogger(tmp_path / "vcs_audit.jsonl")
    logger.log(
        "commit",
        project="Neon",
        user="ana",
        paths=["pro/a.blend"],
        ok=True,
        duration_ms=12,
    )
    logger.log(
        "lock",
        project="Other",
        user="bo",
        paths=["pro/b.blend"],
        ok=False,
        error_code="E160039",
        message="already locked",
    )
    vm = VcsAuditViewModel(logger)
    return VcsAuditWidget(None, vm), vm


def test_widget_renders_events_newest_first(tmp_path, qapp):
    widget, _vm = _widget(tmp_path, qapp)

    assert widget.table.rowCount() == 2
    assert widget.table.item(0, 1).text() == "lock"
    assert widget.table.item(1, 1).text() == "commit"
    widget.deleteLater()


def test_widget_filters_failures(tmp_path, qapp):
    widget, _vm = _widget(tmp_path, qapp)

    widget.chk_failures.setChecked(True)

    assert widget.table.rowCount() == 1
    assert widget.table.item(0, 1).text() == "lock"
    widget.deleteLater()


def test_widget_shows_selected_event_details(tmp_path, qapp):
    widget, _vm = _widget(tmp_path, qapp)
    widget.table.selectRow(1)

    assert "commit" in widget.detail.toPlainText()
    assert "pro/a.blend" in widget.detail.toPlainText()
    widget.deleteLater()
