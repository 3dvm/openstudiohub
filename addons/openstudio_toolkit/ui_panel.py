import bpy
import os


def _collapsible(layout, idname, label, icon, default_closed=False):
    """Draw a collapsible section header and return its body (None when closed)."""
    header, body = layout.panel(idname, default_closed=default_closed)
    header.label(text=label, icon=icon)
    return body


# =========================================================================================
# GRAPHICAL INTERFACE: VIEWPORT PANEL
# =========================================================================================

class OPENSTUDIO_PT_kitsu_panel(bpy.types.Panel):
    """Unified panel for the OpenStudio publishing context."""
    bl_label = "OpenStudio: Task Tools"
    bl_idname = "OPENSTUDIO_PT_kitsu_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "OpenStudio"

    def draw(self, context):
        layout = self.layout

        # 1. Read context injected by the Hub's EnvLauncher
        entity_type = os.environ.get("OPENSTUDIO_KITSU_ENTITY_TYPE", "SHOT").upper()
        entity_name = os.environ.get("OPENSTUDIO_KITSU_ENTITY_NAME", "Unknown")
        task_type = os.environ.get("OPENSTUDIO_KITSU_TASK_TYPE_NAME", "Task")

        # 2. Read local file information
        filepath = bpy.data.filepath
        filename = bpy.path.basename(filepath) if filepath else "Unsaved File"

        # --- SECTION: FILE INFORMATION ---
        body = _collapsible(
            layout, "openstudio_file_status", "Local File Status:", 'FILE_BLEND'
        )
        if body is not None:
            body.label(text=filename)

        layout.separator()

        # --- SECTION: PRODUCTION CONTEXT (SHOT VS ASSET) ---
        context_icon = 'OBJECT_DATA' if entity_type == "ASSET" else 'SCENE_DATA'
        body = _collapsible(
            layout, "openstudio_production_context", "Production Context:", context_icon
        )
        if body is not None:
            if entity_type == "ASSET":
                body.label(text="Context: ASSET", icon='OBJECT_DATA')
                asset_type = os.environ.get("OPENSTUDIO_KITSU_ASSET_TYPE_NAME", "Prop")
                body.label(text=f"Category: {asset_type}")
            else:
                body.label(text="Context: SHOT", icon='SCENE_DATA')
                seq_name = os.environ.get("OPENSTUDIO_KITSU_SEQUENCE_NAME", "Sequence")
                body.label(text=f"Sequence: {seq_name}")

            body.label(text=f"Name: {entity_name}")
            body.label(text=f"Task: {task_type}")

        layout.separator()

        # --- SECTION: ACTIONS ---
        body = _collapsible(
            layout, "openstudio_scene_actions", "Scene Actions:", 'TOOL_SETTINGS'
        )
        if body is not None:
            body.operator("openstudio.audit_task", text="Audit Scene", icon='CHECKMARK')
            body.operator(
                "openstudio.fix_textures",
                text="Fix Out-of-Bounds Textures",
                icon='FILE_IMAGE',
            )
            body.operator("openstudio.purge_orphans", text="Purge Orphans", icon='TRASH')
            body.operator("openstudio.lock_file", text="Lock File", icon='LOCKED')
            body.operator(
                "openstudio.publish_task",
                text="Save & Commit",
                icon='FILE_TICK',
            )

        # --- SECTION: PROJECT PREFERENCES (collapsed by default) ---
        body = _collapsible(
            layout,
            "openstudio_project_preferences",
            "Project Preferences:",
            'PREFERENCES',
            default_closed=True,
        )
        if body is not None:
            body.operator(
                "openstudio.save_preferences",
                text="Save Preferences",
                icon='FILE_TICK',
            )
            body.operator(
                "openstudio.reload_preferences",
                text="Reload Preferences",
                icon='FILE_REFRESH',
            )
            body.operator(
                "openstudio.restore_preferences",
                text="Restore Saved Preferences",
                icon='LOOP_BACK',
            )
            body.operator(
                "openstudio.import_preferences",
                text="Import Preferences…",
                icon='IMPORT',
            )
            body.operator(
                "openstudio.export_preferences",
                text="Export Preferences…",
                icon='EXPORT',
            )

# =========================================================================================
# REGISTRATION FUNCTIONS
# =========================================================================================

classes = (
    OPENSTUDIO_PT_kitsu_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
