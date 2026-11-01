# =========================================================================================
# OPENSTUDIOHUB
# Módulo: addons/openstudio_toolkit/gatekeeper.py
# Rol Arquitectónico: DCC Scripting / Quality Assurance (QA)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.6.0
# =========================================================================================

"""Scene QA and publish operators for the OpenStudio Toolkit add-on."""

import bpy
import os
import shutil
import sys
from pathlib import Path
from .vcs import vcs_factory

# Make the Hub's shared QA kernel importable from the addon (dev checkout).
_HUB_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(_HUB_ROOT))

try:
    # The add-on ships a copy so it also works from the Blender extension
    # sandbox, where the Hub's ``src`` package is not importable.
    from .qa_rules import (
        AUDITABLE_OBJECT_TYPES,
        FORBIDDEN_PRIMITIVES,
        asset_name_from_filename,
        is_dirty_transform,
        is_out_of_bounds,
        is_valid_object_name,
    )
except ImportError:  # pragma: no cover - development checkout fallback
    from src.domain.qa.rules import (
        AUDITABLE_OBJECT_TYPES,
        FORBIDDEN_PRIMITIVES,
        asset_name_from_filename,
        is_dirty_transform,
        is_out_of_bounds,
        is_valid_object_name,
    )

# Backward-compatible aliases (the domain rules are now the single source of truth).
PRIMITIVAS_PROHIBIDAS = set(FORBIDDEN_PRIMITIVES)
TIPOS_AUDITABLES = set(AUDITABLE_OBJECT_TYPES)

# ---------------------------------------------------------
# PHASE 1: CLEANING
# ---------------------------------------------------------

def purgar_huerfanos_recursivo() -> int:
    total_purgados = 0
    purgados_en_pasada = 1

    while purgados_en_pasada > 0:
        purgados_en_pasada = bpy.data.orphans_purge(
            do_local_ids=True,
            do_linked_ids=True,
            do_recursive=True
        )
        total_purgados += purgados_en_pasada

    return total_purgados

def aislar_coleccion_temp() -> bool:
    temp_col = bpy.data.collections.get("__TEMP__")
    if not temp_col:
        return False

    for layer_collection in bpy.context.view_layer.layer_collection.children:
        if layer_collection.collection.name == "__TEMP__":
            layer_collection.exclude = True
            return True

    return False

# ---------------------------------------------------------
# FUNCIONES DE LA FASE 2: AUDITORÍA DE DEPENDENCIAS
# ---------------------------------------------------------

def escanear_out_of_bounds() -> list:
    project_root = os.environ.get("OPENSTUDIO_PROJECT_ROOT")

    if not project_root:
        if not bpy.data.filepath:
            return []
        project_root = os.path.dirname(bpy.data.filepath)

    project_root = os.path.normpath(project_root)
    infractores = []

    for img in bpy.data.images:
        if not img.filepath or img.packed_file or img.source in ('GENERATED', 'VIEWER'):
            continue

        abs_path = os.path.normpath(bpy.path.abspath(img.filepath))
        if is_out_of_bounds(abs_path, project_root):
            infractores.append({
                "tipo": "IMAGE",
                "nombre": img.name,
                "ruta_actual": abs_path,
                "datablock": img
            })

    return infractores

def auto_fix_dependencias(infractores: list, clasificaciones: dict) -> int:
    blend_dir = os.path.dirname(bpy.data.filepath)
    siendo_fijados = 0

    for item in infractores:
        nombre = item["nombre"]
        ruta_origen = item["ruta_actual"]
        datablock = item["datablock"]

        categoria = clasificaciones.get(nombre, "textures")
        ruta_destino_dir = os.path.join(blend_dir, categoria)

        if not os.path.exists(ruta_destino_dir):
            os.makedirs(ruta_destino_dir)

        nombre_archivo = os.path.basename(ruta_origen)
        ruta_destino_archivo = os.path.join(ruta_destino_dir, nombre_archivo)

        try:
            shutil.copy2(ruta_origen, ruta_destino_archivo)
            datablock.filepath = ruta_destino_archivo
            siendo_fijados += 1
        except Exception as e:
            print(f"[CONSERJE ERROR] No se pudo copiar {nombre}: {e}")

    bpy.ops.file.make_paths_relative()
    return siendo_fijados

# ---------------------------------------------------------
# FUNCIONES DE LA FASE 2.5: SANIDAD MATEMÁTICA Y GEOMETRÍA
# ---------------------------------------------------------

def escanear_geometria_sucia() -> list:
    infractores = []
    for obj in bpy.context.view_layer.objects:
        if obj.type in TIPOS_AUDITABLES:
            if is_dirty_transform(
                (obj.location.x, obj.location.y, obj.location.z),
                (obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z),
                (obj.scale.x, obj.scale.y, obj.scale.z),
            ):
                infractores.append(obj.name)

    return infractores

def aplicar_transformaciones(nombres_infractores: list) -> int:
    if not nombres_infractores: return 0
    fijados = 0
    modo_original = bpy.context.object.mode if bpy.context.object else 'OBJECT'
    if modo_original != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')

    for nombre in nombres_infractores:
        obj = bpy.context.scene.objects.get(nombre)
        if obj and obj.name in bpy.context.view_layer.objects:
            estado_oculto = obj.hide_get()
            estado_seleccion = obj.hide_select

            obj.hide_set(False)
            obj.hide_select = False

            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            obj.select_set(False)

            obj.hide_set(estado_oculto)
            obj.hide_select = estado_seleccion
            fijados += 1

    if modo_original != 'OBJECT': bpy.ops.object.mode_set(mode=modo_original)
    return fijados

def limpiar_transformaciones(nombres_infractores: list) -> int:
    if not nombres_infractores: return 0
    fijados = 0

    for nombre in nombres_infractores:
        obj = bpy.context.scene.objects.get(nombre)
        if obj:
            obj.location = (0.0, 0.0, 0.0)
            obj.rotation_euler = (0.0, 0.0, 0.0)
            obj.scale = (1.0, 1.0, 1.0)
            fijados += 1

    return fijados

# ---------------------------------------------------------
# FUNCIONES DE LA FASE 2.6: NOMENCLATURA
# ---------------------------------------------------------

def _obtener_asset_name() -> str:
    return asset_name_from_filename(bpy.path.basename(bpy.context.blend_data.filepath))

def escanear_nombres_sucios() -> list:
    infractores = []
    asset_name = _obtener_asset_name()

    for obj in bpy.context.view_layer.objects:
        if obj.type in TIPOS_AUDITABLES:
            if not is_valid_object_name(obj.name, asset_name):
                infractores.append(obj.name)

    return infractores

def auto_fix_nombres(nombres_infractores: list) -> int:
    if not nombres_infractores: return 0
    asset_name = _obtener_asset_name()
    fijados = 0

    for nombre in nombres_infractores:
        obj = bpy.context.scene.objects.get(nombre)
        if obj:
            nombre_limpio = obj.name.split('.')[0]
            if not nombre_limpio.startswith(f"{asset_name}-"):
                nuevo_nombre = f"{asset_name}-{nombre_limpio}"
                obj.name = nuevo_nombre
                if obj.data:
                    obj.data.name = nuevo_nombre
                fijados += 1
    return fijados

# ---------------------------------------------------------
# OPERATORS
# ---------------------------------------------------------

def _audit_issues():
    return (
        escanear_out_of_bounds(),
        escanear_geometria_sucia(),
        escanear_nombres_sucios(),
    )


def _is_hdri(item: dict) -> bool:
    path = str(item.get("ruta_actual") or item.get("nombre") or "").lower()
    name = str(item.get("nombre") or "").lower()
    return path.endswith((".hdr", ".exr")) or "hdri" in name


class OPENSTUDIO_OT_audit_task(bpy.types.Operator):
    bl_idname = "openstudio.audit_task"
    bl_label = "Audit Scene"
    bl_description = "Run the scene quality checks without saving or committing"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        print("[GATEKEEPER] Running scene audit...")
        out_of_bounds, dirty_geometry, dirty_names = _audit_issues()
        if not (out_of_bounds or dirty_geometry or dirty_names):
            self.report({'INFO'}, "Audit passed: no issues found.")
            return {'FINISHED'}

        context.scene.os_geo_infractores = ",".join(dirty_geometry)
        context.scene.os_nom_infractores = ",".join(dirty_names)
        try:
            bpy.ops.openstudio.master_qa_ui('INVOKE_DEFAULT')
        except AttributeError:
            self.report({'ERROR'}, "The Master QA UI module is not loaded.")
            return {'CANCELLED'}
        self.report({'WARNING'}, "Audit found issues to resolve.")
        return {'FINISHED'}


class OPENSTUDIO_OT_purge_orphans(bpy.types.Operator):
    bl_idname = "openstudio.purge_orphans"
    bl_label = "Purge Orphans"
    bl_description = "Purge unused datablocks and exclude the temporary collection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        isolated = aislar_coleccion_temp()
        purged = purgar_huerfanos_recursivo()
        if isolated:
            self.report({'INFO'}, f"Temporary collection excluded; {purged} orphan(s) purged.")
        else:
            self.report({'INFO'}, f"{purged} orphan(s) purged.")
        return {'FINISHED'}


class OPENSTUDIO_OT_fix_textures(bpy.types.Operator):
    bl_idname = "openstudio.fix_textures"
    bl_label = "Fix Out-of-Bounds Textures"
    bl_description = "Copy external textures into the .blend folder and make paths relative"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        offenders = escanear_out_of_bounds()
        if not offenders:
            self.report({'INFO'}, "No out-of-bounds textures found.")
            return {'FINISHED'}

        categories = {
            item["nombre"]: ("hdri" if _is_hdri(item) else "textures")
            for item in offenders
        }
        fixed = auto_fix_dependencias(offenders, categories)
        self.report({'INFO'}, f"Fixed {fixed} out-of-bounds texture path(s).")
        return {'FINISHED'}


class OPENSTUDIO_OT_publish_task(bpy.types.Operator):
    bl_idname = "openstudio.publish_task"
    bl_label = "Save & Commit"
    bl_description = "Save the .blend locally and commit it when the project uses VCS"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        if not bpy.data.filepath:
            self.report({'ERROR'}, "Save the .blend before publishing.")
            return {'CANCELLED'}

        bpy.ops.wm.save_mainfile()
        filepath = bpy.data.filepath

        adapter = (os.environ.get("OPENSTUDIO_VCS_ADAPTER", "") or "").strip().lower()
        if adapter in ("", "none"):
            self.report({'INFO'}, "Saved locally; VCS is not in use.")
            return {'FINISHED'}

        if adapter != "svn":
            self.report({'ERROR'}, f"Unsupported VCS adapter: {adapter}")
            return {'CANCELLED'}

        project_root = os.environ.get("OPENSTUDIO_PROJECT_ROOT", "")
        production_folder = os.environ.get("OPENSTUDIO_PRODUCTION_FOLDER", "svn")
        vcs_user = os.environ.get("OPENSTUDIO_SVN_USER", "")
        vcs_pwd = os.environ.get("OPENSTUDIO_SVN_PASSWORD", "")

        if not (project_root and vcs_user and vcs_pwd):
            self.report({'WARNING'}, "Saved locally; VCS credentials are missing.")
            return {'FINISHED'}

        workspace_root = os.path.join(project_root, production_folder)
        try:
            self.report({'INFO'}, "Committing to the VCS...")
            vcs_manager = vcs_factory.get_vcs_manager(
                adapter, workspace_root, vcs_user, vcs_pwd
            )
            if vcs_manager is None:
                self.report({'ERROR'}, "VCS is enabled but no adapter is available.")
                return {'CANCELLED'}

            message = f"OpenStudio Hub: {bpy.path.basename(filepath)} saved and committed."
            if not vcs_manager.commit(message, filepath):
                self.report({'ERROR'}, "Commit failed. Check the console for details.")
                return {'CANCELLED'}
            self.report({'INFO'}, "Commit completed.")
        except Exception as error:  # noqa: BLE001
            self.report({'ERROR'}, f"VCS error: {error}")
            return {'CANCELLED'}

        return {'FINISHED'}


def register():
    bpy.types.Scene.os_geo_infractores = bpy.props.StringProperty()
    bpy.types.Scene.os_nom_infractores = bpy.props.StringProperty()
    for operator in (
        OPENSTUDIO_OT_audit_task,
        OPENSTUDIO_OT_purge_orphans,
        OPENSTUDIO_OT_fix_textures,
        OPENSTUDIO_OT_publish_task,
    ):
        bpy.utils.register_class(operator)


def unregister():
    for operator in (
        OPENSTUDIO_OT_publish_task,
        OPENSTUDIO_OT_fix_textures,
        OPENSTUDIO_OT_purge_orphans,
        OPENSTUDIO_OT_audit_task,
    ):
        bpy.utils.unregister_class(operator)
    del bpy.types.Scene.os_nom_infractores
    del bpy.types.Scene.os_geo_infractores


if __name__ == "__main__":
    register()
