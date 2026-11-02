"""Tests for the Toolkit Save & Commit lock-before-save workflow."""

import types

from tests.addon_test_support import load_addon_module


def _prepare(monkeypatch, tmp_path):
    module, bpy, _calls, _timers, _config = load_addon_module(
        monkeypatch, tmp_path, "gatekeeper"
    )
    target = tmp_path / "shot.blend"
    target.write_bytes(b"blend")
    bpy.data.filepath = str(target)
    return module, bpy, target


def _set_svn_env(monkeypatch, project_root):
    monkeypatch.setenv("OPENSTUDIO_VCS_ADAPTER", "svn")
    monkeypatch.setenv("OPENSTUDIO_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("OPENSTUDIO_PRODUCTION_FOLDER", "svn")
    monkeypatch.setenv("OPENSTUDIO_SVN_USER", "artist")
    monkeypatch.setenv("OPENSTUDIO_SVN_PASSWORD", "secret-password")


def test_publish_locks_a_read_only_file_before_saving(monkeypatch, tmp_path):
    module, bpy, target = _prepare(monkeypatch, tmp_path)
    target.chmod(0o444)
    _set_svn_env(monkeypatch, tmp_path)
    events = []

    def fake_lock(path):
        events.append("lock")
        target.chmod(0o644)
        return True

    def fake_save():
        events.append("save")

    def fake_commit(message, path):
        events.append("commit")
        return True

    bpy.ops.wm.save_mainfile = fake_save
    manager = types.SimpleNamespace(lock=fake_lock, commit=fake_commit)
    monkeypatch.setattr(module.vcs_factory, "get_vcs_manager", lambda *a, **k: manager)

    operator = module.OPENSTUDIO_OT_publish_task()
    result = operator.execute(None)

    assert result == {'FINISHED'}
    assert events == ["lock", "save", "commit"]


def test_publish_aborts_before_saving_when_another_user_holds_the_lock(
    monkeypatch, tmp_path
):
    module, bpy, target = _prepare(monkeypatch, tmp_path)
    target.chmod(0o444)
    _set_svn_env(monkeypatch, tmp_path)
    events = []

    def fake_lock(path):
        raise module.VCSLockError("File is locked by 'edv'.", owner="edv")

    def fake_save():
        events.append("save")

    bpy.ops.wm.save_mainfile = fake_save
    manager = types.SimpleNamespace(lock=fake_lock, commit=lambda *a: True)
    monkeypatch.setattr(module.vcs_factory, "get_vcs_manager", lambda *a, **k: manager)

    operator = module.OPENSTUDIO_OT_publish_task()
    result = operator.execute(None)

    assert result == {'CANCELLED'}
    assert events == []
    assert any("edv" in message for _level, message in operator.reports)


def test_publish_reports_a_clear_error_when_saving_a_read_only_file(monkeypatch, tmp_path):
    module, bpy, target = _prepare(monkeypatch, tmp_path)
    target.chmod(0o444)
    monkeypatch.setenv("OPENSTUDIO_VCS_ADAPTER", "none")

    def fake_save():
        raise RuntimeError("Cannot save blend file, path is not writable")

    bpy.ops.wm.save_mainfile = fake_save

    operator = module.OPENSTUDIO_OT_publish_task()
    result = operator.execute(None)

    assert result == {'CANCELLED'}
    assert any(
        "read-only" in message.lower() for _level, message in operator.reports
    )


def test_lock_file_operator_reports_the_foreign_owner(monkeypatch, tmp_path):
    module, bpy, target = _prepare(monkeypatch, tmp_path)
    _set_svn_env(monkeypatch, tmp_path)

    def fake_lock(path):
        raise module.VCSLockError("File is locked by 'edv'.", owner="edv")

    manager = types.SimpleNamespace(lock=fake_lock)
    monkeypatch.setattr(module.vcs_factory, "get_vcs_manager", lambda *a, **k: manager)

    operator = module.OPENSTUDIO_OT_lock_file()
    result = operator.execute(None)

    assert result == {'CANCELLED'}
    assert any("edv" in message for _level, message in operator.reports)
