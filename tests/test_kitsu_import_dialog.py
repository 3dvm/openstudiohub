# =====================================================================================
# OPENSTUDIOHUB
# Module: tests/test_kitsu_import_dialog.py
# =====================================================================================

"""Headless widget tests for the Kitsu import dialog."""

from pathlib import Path

from PySide6.QtWidgets import QScrollArea

from src.application.services.kitsu_import_service import ImportPlan
from src.interfaces.qt.components.project_import_dialog import ProjectImportDialog


def _plan() -> ImportPlan:
    return ImportPlan(
        archive_path=Path("/tmp/x.oshproject"),
        manifest={"format_version": 1},
        project={"name": "Neon"},
        persons=[],
        persons_json=[
            {"id": "u1", "email": "pm@studio.com", "full_name": "PM", "role": "manager"},
            {"id": "u2", "email": "artist@studio.com", "full_name": "Artist", "role": "user"},
        ],
        counts={"tasks": 1, "assets": 2, "shots": 3, "comments": 4, "previews": 5},
        vcs={},
        inclusion={},
    )


def test_import_dialog_auto_matches_and_enables(qapp):
    dialog = ProjectImportDialog(None)
    dialog.set_vcs_servers(
        [{"id": "vps", "name": "VPS", "repository_url": "svn://vps", "adapter": "svn", "is_enabled": True}],
        default_id="vps",
    )
    targets = [
        {"id": "t1", "email": "pm@studio.com", "full_name": "PM"},
        {"id": "t2", "email": "artist@studio.com", "full_name": "Artist"},
    ]
    dialog.on_plan_ready(_plan(), targets)

    assert dialog.table.rowCount() == 2
    assert dialog.btn_import.isEnabled() is True
    mapping = dialog.person_map()
    assert mapping["u1"]["id"] == "t1"
    assert mapping["u2"]["id"] == "t2"
    assert dialog.selected_vcs_server_id() == "vps"


def test_import_dialog_blocks_until_all_mapped(qapp):
    dialog = ProjectImportDialog(None)
    dialog.on_plan_ready(_plan(), [{"id": "t1", "email": "pm@studio.com", "full_name": "PM"}])
    assert dialog.btn_import.isEnabled() is False


def test_import_dialog_is_scrollable_and_maps_topography(qapp):
    dialog = ProjectImportDialog(None)
    assert dialog.findChild(QScrollArea) is not None

    dialog.set_default_topography({
        "vfs_svn": "svn", "vfs_shared": "shared",
        "vfs_local": "local", "vfs_pipeline": "05_config_estudio", "custom_dirs": ["renders"],
    })
    dialog.on_plan_ready(_plan(), [
        {"id": "t1", "email": "pm@studio.com", "full_name": "PM"},
        {"id": "t2", "email": "artist@studio.com", "full_name": "Artist"},
    ])

    # 4 vfs rows + any custom dirs from the source.
    assert dialog.table_topo.rowCount() >= 4
    mapping = dialog.topography_mapping()
    assert mapping["vfs_pipeline"] == "05_config_estudio"
    assert dialog.options()["topography"]["vfs_pipeline"] == "05_config_estudio"


def test_import_dialog_repo_status_gates_import(qapp):
    dialog = ProjectImportDialog(None)
    targets = [
        {"id": "t1", "email": "pm@studio.com", "full_name": "PM"},
        {"id": "t2", "email": "artist@studio.com", "full_name": "Artist"},
    ]
    dialog.on_plan_ready(_plan(), targets)
    # Unprobed repo is allowed.
    assert dialog.btn_import.isEnabled() is True

    dialog.set_repo_status({"state": "missing", "repo_name": "neon", "target": "svn", "server_name": "VPS"})
    assert dialog.btn_import.isEnabled() is False

    dialog.set_repo_status({
        "state": "rename_needed", "repo_name": "neon", "source": "svn_src", "target": "svn",
    })
    assert dialog.chk_repo_rename.isChecked() is True
    assert dialog.btn_import.isEnabled() is True
    assert dialog.options()["rename_repository"] is True

    dialog.chk_repo_rename.setChecked(False)
    assert dialog.btn_import.isEnabled() is False
    assert dialog.options()["rename_repository"] is False


def test_import_dialog_shows_repo_diagnostics(qapp):
    dialog = ProjectImportDialog(None)
    dialog.on_plan_ready(_plan(), [{"id": "t1", "email": "pm@studio.com", "full_name": "PM"}])
    dialog.set_repo_status({
        "state": "missing",
        "repo_name": "neon",
        "target": "svn",
        "server_name": "Default",
        "diagnostics": {
            "effective_mode": "local_docker",
            "repository_url": "svn://academia-core",
            "repo_path": "/home/svn/neon",
            "reason": "repository directory absent",
            "log": "PROBE-DIAGNOSTIC-LINE",
        },
    })

    text = dialog.lbl_repo.text()
    assert "local_docker" in text
    assert "svn://academia-core" in text
    assert "/home/svn/neon" in text
    assert "PROBE-DIAGNOSTIC-LINE" in dialog.lbl_repo.toolTip()
    assert "PROBE-DIAGNOSTIC-LINE" in dialog.log_output.toPlainText()


def test_import_dialog_conflict_disables_import(qapp):
    dialog = ProjectImportDialog(None)
    dialog.on_plan_ready(_plan(), [
        {"id": "t1", "email": "pm@studio.com", "full_name": "PM"},
        {"id": "t2", "email": "artist@studio.com", "full_name": "Artist"},
    ])
    assert dialog.btn_import.isEnabled() is True
    dialog.set_conflict("A project named 'Neon' already exists.")
    assert dialog.btn_import.isEnabled() is False
    assert dialog.lbl_conflict.isVisible() or dialog.lbl_conflict.text()
