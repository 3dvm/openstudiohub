"""Unit tests for the HubProject configuration dialog."""

# Import the views package first: the widgets package has an eager circular
# import that only resolves when views is loaded beforehand.
from PySide6.QtWidgets import QDialog

import src.interfaces.qt.views  # noqa: F401
from src.interfaces.qt.components.hub_project_config_dialog import HubProjectConfigDialog

VAULT_DATA = {
    "4.2": {
        "templates": {"Main": {"version": "1.0"}},
        "addons": {
            "blender_kitsu": {
                "version": "2.0",
                "config_schema": {"version_control": {"type": "bool", "default": True}},
            }
        },
    }
}


class FakeVaultService:
    def load_inventory(self):
        return VAULT_DATA


def _config() -> dict:
    return {
        "project_name": "Neon",
        "project_id": "p1",
        "project_dir": None,
        "is_mounted": False,
        "blueprint": {
            "blender_version": "4.2",
            "template": "Main",
            "dependencies": {"addons": {"blender_kitsu": "2.0"}},
            "addon_configuration": {
                "blender_kitsu": {
                    "enabled": True,
                    "module_match": "blender_kitsu",
                    "settings": {"version_control": False},
                    "behaviors": [],
                }
            },
        },
        "servers": [],
        "bound_server_id": "",
        "splash_path": "",
        "vfs_pipeline": "pipeline",
    }


def _dialog(**overrides) -> HubProjectConfigDialog:
    config = _config()
    config.update(overrides)
    return HubProjectConfigDialog(
        None,
        config,
        on_probe=lambda server_id, name: (True, "healthy"),
        on_save=lambda payload: (True, "saved"),
        vault_service=FakeVaultService(),
    )


def test_dialog_collects_prefilled_blueprint(qapp):
    dialog = _dialog()
    payload = dialog._collect_payload()

    assert payload["blender_version"] == "4.2"
    assert payload["template"] == "Main"
    assert payload["dependencies"]["addons"]["blender_kitsu"] == "2.0"
    addon = payload["addon_configuration"]["blender_kitsu"]
    assert addon["settings"]["version_control"] is False


def test_dialog_saves_through_callback(qapp):
    captured = {}
    config = _config()
    dialog = HubProjectConfigDialog(
        None,
        config,
        on_probe=lambda server_id, name: (True, "healthy"),
        on_save=lambda payload: captured.update(payload) or (True, "saved"),
        vault_service=FakeVaultService(),
    )

    dialog._execute_save()

    assert captured["blender_version"] == "4.2"
    assert dialog.result() == QDialog.Accepted
