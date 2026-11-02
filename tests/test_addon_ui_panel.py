"""Tests for the collapsible sections of the Toolkit viewport panel."""

from tests.addon_test_support import RecordingLayout, load_addon_module

SECTIONS = {
    "openstudio_file_status",
    "openstudio_production_context",
    "openstudio_scene_actions",
    "openstudio_project_preferences",
}

ACTION_OPERATORS = [
    "openstudio.audit_task",
    "openstudio.fix_textures",
    "openstudio.purge_orphans",
    "openstudio.lock_file",
    "openstudio.publish_task",
]

PREFERENCE_OPERATORS = [
    "openstudio.save_preferences",
    "openstudio.reload_preferences",
    "openstudio.restore_preferences",
    "openstudio.import_preferences",
    "openstudio.export_preferences",
]


def _draw_panel(monkeypatch, tmp_path, layout):
    module, *_ = load_addon_module(monkeypatch, tmp_path, "ui_panel")
    panel = module.OPENSTUDIO_PT_kitsu_panel()
    panel.layout = layout
    panel.draw(None)
    return layout


def test_panel_sections_are_collapsible(monkeypatch, tmp_path):
    layout = _draw_panel(monkeypatch, tmp_path, RecordingLayout())

    assert set(layout.sections) == SECTIONS
    assert layout.sections["openstudio_scene_actions"] is not None
    assert layout.sections["openstudio_project_preferences"] is None


def test_actions_live_inside_the_actions_section(monkeypatch, tmp_path):
    layout = _draw_panel(monkeypatch, tmp_path, RecordingLayout())

    assert layout.sections["openstudio_scene_actions"].operators == ACTION_OPERATORS


def test_expanding_preferences_shows_its_operators(monkeypatch, tmp_path):
    layout = _draw_panel(
        monkeypatch,
        tmp_path,
        RecordingLayout(opened={"openstudio_project_preferences"}),
    )

    preferences = layout.sections["openstudio_project_preferences"]
    assert preferences is not None
    assert preferences.operators == PREFERENCE_OPERATORS


def test_all_sections_collapsed_draws_without_errors(monkeypatch, tmp_path):
    layout = _draw_panel(monkeypatch, tmp_path, RecordingLayout(collapsed=SECTIONS))

    assert all(body is None for body in layout.sections.values())
