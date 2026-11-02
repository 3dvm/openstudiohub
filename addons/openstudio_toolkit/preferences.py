"""Per-project Blender preference import, export, persistence and diagnostics."""

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import bpy
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .preferences_policy import (
    SAVE_VERSIONS,
    UNDO_STEPS,
    local_root_from_resources,
    mismatched_preferences,
    temporary_directory,
    vcs_is_enabled,
)

_MISMATCH_STATE = {"checked": False, "keys": [], "saved": {}, "current": {}}
_RELOADED_FLAG = "openstudio_preferences_reloaded"
_RELOAD_TIMER_INTERVAL = 0.1
_RELOAD_RUNNING = False


def userpref_path() -> Path:
    return Path(bpy.utils.user_resource("CONFIG")) / "userpref.blend"


def _local_root() -> Path | None:
    return local_root_from_resources(os.environ.get("BLENDER_USER_RESOURCES", ""))


def _preferences_dir() -> Path | None:
    root = _local_root()
    return (root / "blender_prefs") if root is not None else None


def _project_snapshot_path() -> Path | None:
    folder = _preferences_dir()
    return (folder / "project_userpref.blend") if folder is not None else None


def _saved_report_path() -> Path | None:
    folder = _preferences_dir()
    return (folder / "saved_preferences.json") if folder is not None else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _keyconfig_preferences():
    wm = bpy.context.window_manager
    for keyconfig in (wm.keyconfigs.user, wm.keyconfigs.active):
        preferences = getattr(keyconfig, "preferences", None)
        if preferences is not None and hasattr(preferences, "select_mouse"):
            return preferences
    return None


def _cycles_device_type():
    for key, addon in bpy.context.preferences.addons.items():
        if "cycles" not in key:
            continue
        preferences = getattr(addon, "preferences", None)
        return getattr(preferences, "compute_device_type", None)
    return None


def capture_preferences() -> dict:
    prefs = bpy.context.preferences
    keyconfig_prefs = _keyconfig_preferences()
    try:
        active_keyconfig = bpy.context.window_manager.keyconfigs.active.name
    except Exception:  # noqa: BLE001
        active_keyconfig = ""
    return {
        "select_mouse": getattr(keyconfig_prefs, "select_mouse", None),
        "active_keyconfig": active_keyconfig,
        "cycles_device_type": _cycles_device_type(),
        "temporary_directory": prefs.filepaths.temporary_directory,
        "undo_steps": prefs.edit.undo_steps,
        "save_version": prefs.filepaths.save_version,
    }


def apply_project_preferences() -> None:
    """Apply project-specific File Paths, Save & Load and Undo settings."""
    prefs = bpy.context.preferences

    temp_dir = temporary_directory(os.environ.get("BLENDER_USER_RESOURCES", ""))
    if temp_dir is not None:
        temp_dir.mkdir(parents=True, exist_ok=True)
        prefs.filepaths.temporary_directory = str(temp_dir)

    try:
        prefs.edit.undo_steps = UNDO_STEPS
    except Exception as error:  # noqa: BLE001
        print(f"[OPENSTUDIO PREFERENCES] Could not set undo steps: {error}")

    if vcs_is_enabled(os.environ.get("OPENSTUDIO_VCS_ADAPTER", "")):
        try:
            prefs.filepaths.save_version = SAVE_VERSIONS
        except Exception as error:  # noqa: BLE001
            print(f"[OPENSTUDIO PREFERENCES] Could not set save versions: {error}")


def _kitsu_password_slot():
    try:
        for key, addon in bpy.context.preferences.addons.items():
            if "blender_kitsu" in key:
                return getattr(addon, "preferences", None)
    except Exception:  # noqa: BLE001
        return None
    return None


def save_userpref_safely() -> None:
    """Save preferences without persisting the transient Kitsu password."""
    kitsu_prefs = _kitsu_password_slot()
    password = getattr(kitsu_prefs, "passwd", "") if kitsu_prefs is not None else ""
    try:
        if kitsu_prefs is not None and hasattr(kitsu_prefs, "passwd"):
            kitsu_prefs.passwd = ""
        bpy.ops.wm.save_userpref()
    finally:
        if kitsu_prefs is not None and hasattr(kitsu_prefs, "passwd"):
            kitsu_prefs.passwd = password


def save_preferences_snapshot() -> None:
    """Record the saved values and copy userpref.blend beside the project."""
    folder = _preferences_dir()
    snapshot = _project_snapshot_path()
    report = _saved_report_path()
    source = userpref_path()
    if folder is None or snapshot is None or report is None or not source.is_file():
        return
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, snapshot)
    report.write_text(
        json.dumps(
            {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "userpref": str(source),
                "sha256": _sha256(source),
                "values": {
                    key: value
                    for key, value in capture_preferences().items()
                    if value is not None
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def load_saved_report() -> dict:
    report = _saved_report_path()
    if report is None or not report.exists():
        return {}
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def restore_saved_preferences() -> bool:
    """Copy the project snapshot over userpref.blend; the reload itself is deferred."""
    snapshot = _project_snapshot_path()
    if snapshot is None or not snapshot.is_file():
        return False
    destination = userpref_path()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot, destination)
    except OSError as error:
        print(f"[OPENSTUDIO PREFERENCES] Restore failed: {error}")
        return False
    return True


def reload_preferences() -> bool:
    """Check that a preferences file exists; the reload itself is deferred."""
    if not userpref_path().is_file():
        print("[OPENSTUDIO PREFERENCES] No saved preferences were found to reload.")
        return False
    return True


def _apply_reloaded_preferences() -> None:
    """Reload preferences after the invoking operator has finished.

    ``wm.read_userpref`` disables and re-enables every add-on, which unregisters
    this add-on (and the operator that called it) while ``execute`` is still on
    the stack. That leaves ``self`` as a dangling RNA pointer and crashes Blender
    on the next ``self.report``. Running it from a timer keeps the operator
    untouched until it has returned.
    """
    global _RELOAD_RUNNING
    _RELOAD_RUNNING = True
    try:
        bpy.ops.wm.read_userpref()
        apply_project_preferences()
        save_userpref_safely()
        save_preferences_snapshot()
        bpy.app.driver_namespace[_RELOADED_FLAG] = True
        _MISMATCH_STATE["checked"] = True
    except Exception as error:  # noqa: BLE001
        print(f"[OPENSTUDIO PREFERENCES] Deferred preferences reload failed: {error}")
    finally:
        _RELOAD_RUNNING = False
    return None


def schedule_preferences_reload() -> bool:
    """Queue a preferences reload for the next event loop tick."""
    if bpy.app.timers.is_registered(_apply_reloaded_preferences):
        return False
    bpy.app.timers.register(
        _apply_reloaded_preferences, first_interval=_RELOAD_TIMER_INTERVAL
    )
    return True


def _check_saved_preferences():
    if bpy.app.driver_namespace.pop(_RELOADED_FLAG, False):
        _MISMATCH_STATE["checked"] = True
        return None
    if _MISMATCH_STATE["checked"]:
        return None
    _MISMATCH_STATE["checked"] = True
    report = load_saved_report()
    saved = report.get("values") if isinstance(report.get("values"), dict) else {}
    if not saved:
        return None
    current = capture_preferences()
    keys = mismatched_preferences(saved, current)
    if not keys:
        return None
    _MISMATCH_STATE.update({"keys": keys, "saved": saved, "current": current})
    print(
        "[OPENSTUDIO PREFERENCES] Saved preferences were not loaded: "
        + ", ".join(keys)
    )
    try:
        bpy.ops.openstudio.preferences_mismatch('INVOKE_DEFAULT')
    except Exception as error:  # noqa: BLE001
        print(f"[OPENSTUDIO PREFERENCES] Could not open the restore dialog: {error}")
    return None


class OPENSTUDIO_OT_save_preferences(bpy.types.Operator):
    bl_idname = "openstudio.save_preferences"
    bl_label = "Save Project Preferences"
    bl_description = "Apply project file paths and save Blender preferences in this project sandbox"
    bl_options = {'REGISTER'}

    def execute(self, context):
        apply_project_preferences()
        save_userpref_safely()
        save_preferences_snapshot()
        self.report({'INFO'}, f"Preferences saved to {userpref_path()}.")
        return {'FINISHED'}


class OPENSTUDIO_OT_reload_preferences(bpy.types.Operator):
    bl_idname = "openstudio.reload_preferences"
    bl_label = "Reload Project Preferences"
    bl_description = "Reload Blender preferences from this project's sandbox"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if not reload_preferences():
            self.report({'ERROR'}, "Could not reload project preferences.")
            return {'CANCELLED'}
        schedule_preferences_reload()
        self.report({'INFO'}, "Reloading project preferences…")
        return {'FINISHED'}


class OPENSTUDIO_OT_restore_preferences(bpy.types.Operator):
    bl_idname = "openstudio.restore_preferences"
    bl_label = "Restore Saved Preferences"
    bl_description = "Restore the last preferences saved for this project"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if not restore_saved_preferences():
            self.report({'ERROR'}, "No saved project preferences are available.")
            return {'CANCELLED'}
        schedule_preferences_reload()
        self.report({'INFO'}, "Restoring saved project preferences…")
        return {'FINISHED'}


class OPENSTUDIO_OT_preferences_mismatch(bpy.types.Operator):
    bl_idname = "openstudio.preferences_mismatch"
    bl_label = "Saved Preferences Were Not Loaded"
    bl_description = "The current session does not match the preferences saved for this project"
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        layout.label(text="The saved project preferences differ from this session.")
        for key in _MISMATCH_STATE["keys"]:
            saved = _MISMATCH_STATE["saved"].get(key)
            current = _MISMATCH_STATE["current"].get(key)
            layout.label(text=f"{key}: saved={saved!r}  loaded={current!r}")
        layout.label(text="OK restores the saved preferences. Cancel keeps this session.")

    def execute(self, context):
        if not restore_saved_preferences():
            self.report({'ERROR'}, "No saved project preferences are available.")
            return {'CANCELLED'}
        schedule_preferences_reload()
        self.report({'INFO'}, "Restoring saved project preferences…")
        return {'FINISHED'}


class OPENSTUDIO_OT_export_preferences(bpy.types.Operator, ExportHelper):
    bl_idname = "openstudio.export_preferences"
    bl_label = "Export Blender Preferences"
    bl_description = "Save a copy of this project's Blender preferences"
    filename_ext = ".blend"
    filter_glob: bpy.props.StringProperty(default="*.blend", options={'HIDDEN'})

    def execute(self, context):
        apply_project_preferences()
        save_userpref_safely()
        source = userpref_path()
        if not source.is_file():
            self.report({'ERROR'}, "No saved Blender preferences were found.")
            return {'CANCELLED'}
        try:
            destination = Path(self.filepath)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as error:
            self.report({'ERROR'}, f"Could not export preferences: {error}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Preferences exported to {destination}.")
        return {'FINISHED'}


class OPENSTUDIO_OT_import_preferences(bpy.types.Operator, ImportHelper):
    bl_idname = "openstudio.import_preferences"
    bl_label = "Import Blender Preferences"
    bl_description = "Replace this project's Blender preferences with a saved userpref file"
    filename_ext = ".blend"
    filter_glob: bpy.props.StringProperty(default="*.blend", options={'HIDDEN'})

    def execute(self, context):
        source = Path(self.filepath)
        if not source.is_file():
            self.report({'ERROR'}, "Select a valid userpref.blend file.")
            return {'CANCELLED'}
        destination = userpref_path()
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as error:
            self.report({'ERROR'}, f"Could not import preferences: {error}")
            return {'CANCELLED'}
        schedule_preferences_reload()
        self.report({'INFO'}, f"Preferences imported from {source}. Reloading…")
        return {'FINISHED'}


classes = (
    OPENSTUDIO_OT_save_preferences,
    OPENSTUDIO_OT_reload_preferences,
    OPENSTUDIO_OT_restore_preferences,
    OPENSTUDIO_OT_preferences_mismatch,
    OPENSTUDIO_OT_export_preferences,
    OPENSTUDIO_OT_import_preferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.timers.is_registered(_check_saved_preferences):
        bpy.app.timers.register(_check_saved_preferences, first_interval=1.5)


def unregister():
    if bpy.app.timers.is_registered(_check_saved_preferences):
        bpy.app.timers.unregister(_check_saved_preferences)
    if (
        not _RELOAD_RUNNING
        and bpy.app.timers.is_registered(_apply_reloaded_preferences)
    ):
        bpy.app.timers.unregister(_apply_reloaded_preferences)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
