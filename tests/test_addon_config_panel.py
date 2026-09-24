"""Unit tests for the schema-driven AddonConfigPanel."""

# Import the views package first: the widgets package has an eager circular
# import that only resolves when views is loaded beforehand.
import src.interfaces.qt.views  # noqa: F401
from src.interfaces.qt.widgets.addon_config_panel import AddonConfigPanel

SCHEMA = {
    "enabled": {"type": "bool", "default": True},
    "count": {"type": "int", "default": 1},
    "name": {"type": "str", "default": "default"},
}


def test_values_returns_schema_defaults(qapp):
    panel = AddonConfigPanel(SCHEMA, {"name": "preset"})
    assert panel.values() == {"enabled": True, "count": 1, "name": "preset"}


def test_set_values_overrides_existing_settings(qapp):
    panel = AddonConfigPanel(SCHEMA, {"name": "preset"})
    panel.set_values({"enabled": False, "count": 7, "name": "project"})
    assert panel.values() == {"enabled": False, "count": 7, "name": "project"}


def test_set_values_ignores_absent_fields(qapp):
    panel = AddonConfigPanel(SCHEMA, {"name": "preset"})
    panel.set_values({"count": 3})
    values = panel.values()
    assert values["count"] == 3
    assert values["name"] == "preset"
