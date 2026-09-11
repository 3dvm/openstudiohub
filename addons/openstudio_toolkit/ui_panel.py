import bpy
import os

# =========================================================================================
# GRAPHICAL INTERFACE: VIEWPORT PANEL
# =========================================================================================

class OPENSTUDIO_PT_kitsu_panel(bpy.types.Panel):
    """Unified panel for the OpenStudio publishing context."""
    bl_label = "OpenStudio: Publish Manager"
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
        box_file = layout.box()
        box_file.label(text="Local File Status:", icon='FILE_BLEND')
        row = box_file.row()
        row.label(text=filename)

        layout.separator()

        # --- SECTION: PRODUCTION CONTEXT (SHOT VS ASSET) ---
        box_ctx = layout.box()
        if entity_type == "ASSET":
            box_ctx.label(text="Context: ASSET", icon='OBJECT_DATA')
            asset_type = os.environ.get("OPENSTUDIO_KITSU_ASSET_TYPE_NAME", "Prop")
            box_ctx.label(text=f"Category: {asset_type}")
        else:
            box_ctx.label(text="Context: SHOT", icon='SCENE_DATA')
            seq_name = os.environ.get("OPENSTUDIO_KITSU_SEQUENCE_NAME", "Sequence")
            box_ctx.label(text=f"Sequence: {seq_name}")

        box_ctx.label(text=f"Name: {entity_name}")
        box_ctx.label(text=f"Task: {task_type}")

        layout.separator()

        # --- SECTION: MASTER PUBLISH BUTTON ---
        # Direct call to the Gatekeeper (Sanity Check -> Save -> SVN -> Kitsu)
        layout.operator("openstudio.publish_task", text="Push / Publish (SVN + Kitsu)", icon='URL')

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
