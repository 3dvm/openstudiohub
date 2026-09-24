"""Unit tests for the VCS migration target chooser."""

from src.interfaces.qt.components.vcs_migration_dialog import MigrationServerDialog


def test_dialog_lists_only_provided_targets(qapp):
    source = {"id": "local", "name": "Local", "repository_url": "svn://localhost"}
    targets = [{"id": "vps", "name": "VPS", "repository_url": "svn://vps"}]

    dialog = MigrationServerDialog(None, "Neon", source, targets, "vps")

    assert dialog.selected_target_id() == "vps"
    assert dialog.combo_target.count() == 1
    assert "VPS" in dialog.combo_target.itemText(0)
    assert "svn://vps" in dialog.combo_target.itemText(0)
    assert dialog.btn_migrate.isEnabled() is True


def test_dialog_without_targets_disables_migrate(qapp):
    source = {"id": "local", "name": "Local", "repository_url": "svn://localhost"}

    dialog = MigrationServerDialog(None, "Neon", source, [], "")

    assert dialog.combo_target.count() == 0
    assert dialog.btn_migrate.isEnabled() is False
