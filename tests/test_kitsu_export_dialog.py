# =====================================================================================
# OPENSTUDIOHUB
# Module: tests/test_kitsu_export_dialog.py
# =====================================================================================

"""Headless widget tests for the Kitsu export dialog."""

from PySide6.QtWidgets import QScrollArea

from src.interfaces.qt.components.project_export_dialog import ProjectExportDialog


def test_export_dialog_is_scrollable(qapp):
    dialog = ProjectExportDialog(None, "Neon")
    assert dialog.findChild(QScrollArea) is not None


def test_export_dialog_defaults_and_options(qapp):
    dialog = ProjectExportDialog(None, "Neon")
    options = dialog.options()
    assert options["include_media"] is True
    assert options["include_shared"] is False
    assert options["embed_svn_dump"] is False
    assert options["media_cap_mb"] == 200

    dialog.chk_shared.setChecked(True)
    dialog.chk_dump.setChecked(True)
    assert dialog.options()["include_shared"] is True
    assert dialog.options()["embed_svn_dump"] is True


def test_export_dialog_estimate_table_and_finalize(qapp):
    dialog = ProjectExportDialog(None, "Neon")
    dialog.set_estimate({
        "kitsu": 1024, "media_previews": 2048, "media_attachments": 0,
        "files_pipeline": 4096, "files_shared": 0, "vcs_dump": 0, "total": 7168,
        "approximate": True,
    })
    # Products + TOTAL row.
    assert dialog.table.rowCount() >= 6
    assert dialog.table.item(0, 1) is not None

    dialog.finalize(True, "done")
    assert "done" in dialog.lbl_status.text()


def test_export_dialog_blocks_export_without_destination(qapp):
    dialog = ProjectExportDialog(None, "Neon")
    captured = {}
    dialog.start_requested.connect(lambda dest, opts: captured.update(dest=dest))
    dialog._on_export()
    assert captured == {}
    assert "destination" in dialog.lbl_status.text().lower()
