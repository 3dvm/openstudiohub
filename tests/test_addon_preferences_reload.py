"""Regression tests for the deferred Blender preferences reload.

``bpy.ops.wm.read_userpref`` runs ``addon_utils.disable_all()``, which unregisters
the add-on while an operator may still be executing. That left the operator's
``self`` dangling and crashed Blender on the next ``self.report``.
"""

from pathlib import Path

import pytest

from tests.addon_test_support import load_addon_module


def _load(monkeypatch, tmp_path):
    monkeypatch.delenv("BLENDER_USER_RESOURCES", raising=False)
    monkeypatch.delenv("OPENSTUDIO_VCS_ADAPTER", raising=False)
    return load_addon_module(monkeypatch, tmp_path, "preferences")


def _userpref(config_dir: Path) -> Path:
    return config_dir / "userpref.blend"


def _snapshot(monkeypatch, tmp_path) -> Path:
    resources = tmp_path / "06_conf_LOCAL" / "blender_data"
    monkeypatch.setenv("BLENDER_USER_RESOURCES", str(resources))
    snapshot = tmp_path / "06_conf_LOCAL" / "blender_prefs" / "project_userpref.blend"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(b"project snapshot")
    return snapshot


def test_import_execute_defers_the_reload(monkeypatch, tmp_path):
    module, bpy, calls, timers, config_dir = _load(monkeypatch, tmp_path)
    applied = []
    monkeypatch.setattr(module, "apply_project_preferences", lambda: applied.append("apply"))
    monkeypatch.setattr(module, "save_userpref_safely", lambda: applied.append("save"))
    monkeypatch.setattr(module, "save_preferences_snapshot", lambda: applied.append("snapshot"))

    source = tmp_path / "imported_userpref.blend"
    source.write_bytes(b"imported preferences")
    operator = module.OPENSTUDIO_OT_import_preferences()
    operator.filepath = str(source)

    assert operator.execute(None) == {'FINISHED'}
    assert calls["read_userpref"] == 0
    assert applied == []
    assert _userpref(config_dir).read_bytes() == b"imported preferences"
    assert timers.is_registered(module._apply_reloaded_preferences)
    assert operator.reports[-1][0] == {'INFO'}

    assert timers.run(module._apply_reloaded_preferences) is None
    assert calls["read_userpref"] == 1
    assert applied == ["apply", "save", "snapshot"]


@pytest.mark.parametrize(
    "operator_name",
    [
        "OPENSTUDIO_OT_reload_preferences",
        "OPENSTUDIO_OT_restore_preferences",
        "OPENSTUDIO_OT_preferences_mismatch",
    ],
)
def test_preferences_operators_never_reload_synchronously(monkeypatch, tmp_path, operator_name):
    module, bpy, calls, timers, config_dir = _load(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True, exist_ok=True)
    _userpref(config_dir).write_bytes(b"previous preferences")
    if operator_name != "OPENSTUDIO_OT_reload_preferences":
        _snapshot(monkeypatch, tmp_path)

    operator = getattr(module, operator_name)()
    assert operator.execute(None) == {'FINISHED'}
    assert calls["read_userpref"] == 0
    assert timers.is_registered(module._apply_reloaded_preferences)


def test_reload_without_userpref_cancels_without_scheduling(monkeypatch, tmp_path):
    module, bpy, calls, timers, config_dir = _load(monkeypatch, tmp_path)

    operator = module.OPENSTUDIO_OT_reload_preferences()
    assert operator.execute(None) == {'CANCELLED'}
    assert not timers.is_registered(module._apply_reloaded_preferences)


def test_restore_without_snapshot_cancels_without_scheduling(monkeypatch, tmp_path):
    module, bpy, calls, timers, config_dir = _load(monkeypatch, tmp_path)

    operator = module.OPENSTUDIO_OT_restore_preferences()
    assert operator.execute(None) == {'CANCELLED'}
    assert not timers.is_registered(module._apply_reloaded_preferences)


def test_import_without_source_cancels_without_scheduling(monkeypatch, tmp_path):
    module, bpy, calls, timers, config_dir = _load(monkeypatch, tmp_path)

    operator = module.OPENSTUDIO_OT_import_preferences()
    operator.filepath = str(tmp_path / "missing_userpref.blend")
    assert operator.execute(None) == {'CANCELLED'}
    assert not timers.is_registered(module._apply_reloaded_preferences)


def test_scheduling_twice_queues_a_single_reload(monkeypatch, tmp_path):
    module, bpy, calls, timers, config_dir = _load(monkeypatch, tmp_path)

    assert module.schedule_preferences_reload() is True
    assert module.schedule_preferences_reload() is False
    assert list(timers.callbacks) == [module._apply_reloaded_preferences]


def test_unregister_drops_a_pending_reload(monkeypatch, tmp_path):
    module, bpy, calls, timers, config_dir = _load(monkeypatch, tmp_path)

    module.schedule_preferences_reload()
    module.unregister()
    assert not timers.is_registered(module._apply_reloaded_preferences)


def test_deferred_reload_suppresses_the_next_mismatch_check(monkeypatch, tmp_path):
    module, bpy, calls, timers, config_dir = _load(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "apply_project_preferences", lambda: None)
    monkeypatch.setattr(module, "save_userpref_safely", lambda: None)
    monkeypatch.setattr(module, "save_preferences_snapshot", lambda: None)

    timers.register(module._apply_reloaded_preferences, first_interval=0.1)
    timers.run(module._apply_reloaded_preferences)
    assert bpy.app.driver_namespace[module._RELOADED_FLAG] is True

    module._check_saved_preferences()
    assert bpy.app.driver_namespace.get(module._RELOADED_FLAG) is None
