# =========================================================================================
# OPENSTUDIOHUB
# Módulo: addons/openstudio_toolkit/gatekeeper.py
# Rol Arquitectónico: DCC Scripting / Quality Assurance (QA)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.5.7
# =========================================================================================

"""
Módulo principal de The Gatekeeper.
Implementa el Scene Sanity Check, la purga de datos huérfanos, validación de dependencias,
auditoría matemática de la geometría y detona los hooks de publicación.
"""

import bpy
import os
import shutil
import sys
from pathlib import Path
from . import hooks

from .vcs import vcs_factory

# Make the Hub's shared QA kernel importable from the addon (dev checkout).
_HUB_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(_HUB_ROOT))

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
# FUNCIONES DE LA FASE 1: LIMPIEZA
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
# OPERADOR PRINCIPAL: PUSH / PUBLISH
# ---------------------------------------------------------

class OPENSTUDIO_OT_publish_task(bpy.types.Operator):
    bl_idname = "openstudio.publish_task"
    bl_label = "Push / Publish"
    bl_description = "Purga el archivo, guarda localmente, hace commit en SVN y publica en Kitsu"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        print("\n==================================================")
        print("[GATEKEEPER] Iniciando Secuencia de Publicación...")

        # 1. SANITY CHECK (Reutilizando tus funciones existentes)
        if aislar_coleccion_temp():
            print(" -> Colección '__TEMP__' excluida.")
        purgados = purgar_huerfanos_recursivo()
        print(f" -> {purgados} huérfanos purgados.")

        infractores_ext = escanear_out_of_bounds()
        infractores_geo = escanear_geometria_sucia()
        infractores_nom = escanear_nombres_sucios()

        hay_errores = bool(infractores_ext or infractores_geo or infractores_nom)

        if hay_errores:
            print("[GATEKEEPER ALERTA] Se detectaron errores. Invocando Modal QA...")
            context.scene.os_geo_infractores = ",".join(infractores_geo)
            context.scene.os_nom_infractores = ",".join(infractores_nom)
            try:
                bpy.ops.openstudio.master_qa_ui('INVOKE_DEFAULT')
            except AttributeError:
                self.report({'ERROR'}, "Módulo UI Maestro no está cargado.")
            return {'CANCELLED'}

        print(" -> Todos los chequeos superados con éxito.")

        # 2. GUARDADO LOCAL SÍNCRONO
        self.report({'INFO'}, "Guardando archivo localmente...")
        bpy.ops.wm.save_mainfile()
        filepath = bpy.data.filepath

        # 3. CONEXIÓN AL CONTROL DE VERSIONES (VCS)
        project_root = os.environ.get("OPENSTUDIO_PROJECT_ROOT", "")
        svn_folder = os.environ.get("OPENSTUDIO_PRODUCTION_FOLDER", "svn")
        vcs_user = os.environ.get("OPENSTUDIO_SVN_USER", "")
        vcs_pwd = os.environ.get("OPENSTUDIO_SVN_PASSWORD", "")

        # Por ahora lo forzamos a "svn", luego podrías leer esto de las variables de entorno
        vcs_type = "svn"

        if project_root and vcs_user and vcs_pwd:
            workspace_root = os.path.join(project_root, svn_folder)
            try:
                self.report({'INFO'}, f"Enviando al servidor {vcs_type.upper()}...")
                vcs_manager = vcs_factory.get_vcs_manager(vcs_type, workspace_root, vcs_user, vcs_pwd)

                commit_msg = f"Auto-Commit: {bpy.path.basename(filepath)} actualizado vía Hub."

                exito = vcs_manager.commit(commit_msg, filepath)
                if not exito:
                    self.report({'ERROR'}, "Fallo al subir a SVN. Revisa la consola.")
                    return {'CANCELLED'}

                self.report({'INFO'}, "¡Commit SVN exitoso!")
            except Exception as e:
                self.report({'ERROR'}, f"Error VCS: {str(e)}")
                return {'CANCELLED'}
        else:
            self.report({'WARNING'}, "Sin credenciales SVN detectadas. Solo se guardó local.")

        # 4. THE SYNERGY HOOK (Kitsu)
        print("[GATEKEEPER] Fase 3: The Synergy Hook (Kitsu)...")
        self.report({'INFO'}, "Enviando Playblast a Kitsu...")
        hooks.disparar_playblast_kitsu()

        return {'FINISHED'}

def register():
    bpy.types.Scene.os_geo_infractores = bpy.props.StringProperty()
    bpy.types.Scene.os_nom_infractores = bpy.props.StringProperty()
    bpy.utils.register_class(OPENSTUDIO_OT_publish_task)

def unregister():
    del bpy.types.Scene.os_nom_infractores
    del bpy.types.Scene.os_geo_infractores
    bpy.utils.unregister_class(OPENSTUDIO_OT_publish_task)

if __name__ == "__main__":
    register()
