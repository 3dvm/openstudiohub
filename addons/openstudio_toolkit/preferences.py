"""Per-project Blender preference import, export and persistence."""

import os
import shutil
from pathlib import Path

import bpy
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .preferences_policy import (
    SAVE_VERSIONS,
    UNDO_STEPS,
    temporary_directory,
    vcs_is_enabled,
)


def userpref_path() -> Path:
    config_dir = Path(bpy.utils.user_resource("CONFIG"))
    return config_dir / "userpref.blend"


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


class OPENSTUDIO_OT_save_preferences(bpy.types.Operator):
    bl_idname = "openstudio.save_preferences"
    bl_label = "Save Project Preferences"
    bl_description = "Apply project file paths and save Blender preferences in this project sandbox"
    bl_options = {'REGISTER'}

    def execute(self, context):
        apply_project_preferences()
        save_userpref_safely()
        self.report({'INFO'}, f"Preferences saved to {userpref_path()}.")
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
            bpy.ops.wm.read_userpref()
            apply_project_preferences()
            save_userpref_safely()
        except Exception as error:  # noqa: BLE001
            self.report({'ERROR'}, f"Could not import preferences: {error}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Preferences imported from {source}.")
        return {'FINISHED'}


classes = (
    OPENSTUDIO_OT_save_preferences,
    OPENSTUDIO_OT_export_preferences,
    OPENSTUDIO_OT_import_preferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
