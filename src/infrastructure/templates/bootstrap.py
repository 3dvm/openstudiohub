# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/templates/bootstrap.py
# Rol Arquitectónico: DCC Scripting / Pre-Flight Config & Jailing
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.6.1 (Kitsu Wake Parity with Headless)
# =========================================================================================

"""
Script de inyección ejecutado asíncronamente al iniciar Blender.
Aplica la Matriz RBAC, activa extensiones contextualmente, establece credenciales RAM,
abre el archivo de la tarea (si existe), e invoca la autodetección nativa del contexto Kitsu.
"""

import bpy
import os
import importlib
import addon_utils
from pathlib import Path
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_contract import SandboxEnvironment
_ENV = SandboxEnvironment.from_os_environ()

# =================================================================
# 1. RESOLUCIÓN DINÁMICA DE EXTENSIONES
# =================================================================
def _get_kitsu_addon_key() -> str:
    """Encuentra la clave exacta de Kitsu en el nuevo sistema de extensiones (v4.2+)."""
    for key in bpy.context.preferences.addons.keys():
        if "blender_kitsu" in key:
            return key
    
    # Búsqueda profunda si no está en las preferencias activas
    for mod in addon_utils.modules():
        if "blender_kitsu" in mod.__name__:
            return mod.__name__
            
    return "blender_kitsu" # Fallback legacy

def _get_kitsu_module():
    """Devuelve el módulo cargado en memoria de Kitsu."""
    addon_key = _get_kitsu_addon_key()
    import sys
    return sys.modules.get(addon_key)

# =================================================================
# 2. HANDLERS PERSISTENTES (Sobreviven a F8 y apertura de archivos)
# =================================================================
@bpy.app.handlers.persistent
def _apply_persistent_overrides(dummy=None):
    """
    Se ejecuta CADA VEZ que se carga un archivo .blend.
    Garantiza que el Monkey Patch y el RBAC nunca desaparezcan.
    """
    # 1. Extraer variables de entorno vitales
    project_root = (_ENV.project_root or "")
    prod_folder = (_ENV.production_folder or "02_archivos_de_produccion")
    user_role = (_ENV.user_role or "artist").lower()
    
    kitsu_mod = _get_kitsu_module()
    
    # 2. Re-aplicar Monkey Patch del VFS
    if kitsu_mod and project_root:
        try:
            kitsu_prefs_mod = importlib.import_module(f"{kitsu_mod.__name__}.prefs")
            
            def custom_project_root_dir_get(context):
                pref_instance = kitsu_prefs_mod.addon_prefs_get(context)
                return Path(pref_instance.project_root_dir) / prod_folder
                
            kitsu_prefs_mod.project_root_dir_get = custom_project_root_dir_get

            # Parche de clase (Evita el hardcodeo del add-on)
            if hasattr(kitsu_prefs_mod, "KITSU_addon_preferences"):
                def custom_project_root_path(self):
                    return Path(self.project_root_dir) / prod_folder
                
                kitsu_prefs_mod.KITSU_addon_preferences.project_root_path = custom_project_root_path

        except Exception as e:
            print(f"[OPENSTUDIO HUB] Error en Monkey Patch: {e}")

    # 3. Re-aplicar Guardrails (Jailing RBAC)
    if user_role not in ["lead", "supervisor", "td"]:
        @classmethod
        def poll_restringido(cls, context):
            return False 
            
        if hasattr(bpy.types, "ASSETPIPE_OT_force_push"):
            bpy.types.ASSETPIPE_OT_force_push.poll = poll_restringido
            
        if hasattr(bpy.types, "OPENSTUDIO_OT_override_sanity"):
            bpy.types.OPENSTUDIO_OT_override_sanity.poll = poll_restringido

# =================================================================
# 3. SECUENCIA DE ARRANQUE INICIAL (One-Shot Timer)
# =================================================================
def _startup_sequence():
    """
    Función de un solo uso. Configura preferencias, abre el archivo,
    y establece la sesión. Retorna None para que el timer se autodestruya.
    """
    try:
        print("\n" + "="*50)
        print("[OPENSTUDIO HUB] Iniciando Secuencia de Arranque...")

        target_file = (_ENV.target_file or "")
        task_type = (_ENV.task_type or "generic").lower()
        
        kitsu_user = (_ENV.kitsu_user or "")
        kitsu_pwd = (_ENV.kitsu_pwd or "")
        kitsu_host = (_ENV.kitsu_host or "")
        project_id = (_ENV.kitsu_project_id or "")
        project_root = (_ENV.project_root or "")
        prod_folder = (_ENV.production_folder or "02_archivos_de_produccion")

        addon_key = _get_kitsu_addon_key()

        # =========================================================
        # NUEVO: FORZAR ACTIVACIÓN (Paridad exacta con Headless Builder)
        # =========================================================
        if addon_key not in bpy.context.preferences.addons:
            print(f"[OPENSTUDIO HUB] Despertando extensión: {addon_key}...")
            try:
                # Evitamos addon_utils.enable porque dispara un unregister() buggeado en Kitsu
                bpy.ops.preferences.addon_enable(module=addon_key)
            except Exception as e:
                print(f"[OPENSTUDIO HUB] Advertencia al activar Kitsu: {e}")
            
            # Forzamos la importación en memoria para el registro de RNA
            importlib.import_module(addon_key)
        # =========================================================
        
        # 1. Configurar Preferencias Físicas y Credenciales
        if addon_key in bpy.context.preferences.addons:
            addon_prefs = bpy.context.preferences.addons[addon_key].preferences
            
            # Enrutamiento de Kitsu
            if project_root and hasattr(addon_prefs, "project_root_dir"):
                addon_prefs.project_root_dir = project_root
            if hasattr(addon_prefs, "version_control"): addon_prefs.version_control = True
            if hasattr(addon_prefs, "shot_dir_name"): addon_prefs.shot_dir_name = "shots"
            if hasattr(addon_prefs, "asset_dir_name"): addon_prefs.asset_dir_name = "assets"
            if hasattr(addon_prefs, "seq_dir_name"): addon_prefs.seq_dir_name = "strips"
            if hasattr(addon_prefs, "edit_dir_name"): addon_prefs.edit_dir_name = "edit"
            
            # Enrutamiento de Playblasts
            vfs_root = Path(project_root) / prod_folder
            footage_dir = vfs_root / "edit" / "footage"
            if hasattr(addon_prefs, "shot_playblast_root_dir"): addon_prefs.shot_playblast_root_dir = str(footage_dir / "pro")
            if hasattr(addon_prefs, "seq_playblast_root_dir"): addon_prefs.seq_playblast_root_dir = str(footage_dir / "pre")
            if hasattr(addon_prefs, "frames_root_dir"): addon_prefs.frames_root_dir = str(footage_dir / "post")

            # Autenticación RAM
            if kitsu_user and kitsu_pwd:
                addon_prefs.host = kitsu_host
                addon_prefs.email = kitsu_user
                addon_prefs.passwd = kitsu_pwd
                try:
                    print(f"[OPENSTUDIO HUB] Autenticando Kitsu con {kitsu_user}...")
                    bpy.ops.kitsu.session_start('EXEC_DEFAULT')
                    bpy.ops.kitsu.con_productions_load('EXEC_DEFAULT')
                    if project_id:
                        kitsu_mod = _get_kitsu_module()
                        if kitsu_mod:
                            kitsu_mod.cache.project_active_set_by_id(bpy.context, project_id)
                        addon_prefs.project_active_id = project_id 
                except Exception as e:
                    print(f"[OPENSTUDIO HUB] Error al autenticar Kitsu API: {e}")
        else:
            print(f"[OPENSTUDIO HUB] ❌ ERROR: El addon {addon_key} no pudo inicializarse en las preferencias.")

        # 2. Carga del Archivo Maestro
        if target_file and os.path.exists(target_file):
            print(f"[OPENSTUDIO HUB] Cargando archivo de producción: {target_file}")
            try:
                bpy.ops.wm.open_mainfile(filepath=target_file)
                
                # Autodetección o forzado de contexto
                if hasattr(bpy.ops.kitsu, "con_detect_context"):
                    bpy.ops.kitsu.con_detect_context('EXEC_DEFAULT')
                    
                # Forzado Visual de Workspaces
                ws_map = {"edit": "Video Editing", "editorial": "Video Editing", "montaje": "Video Editing", "storyboard": "Storyboard"}
                ws_name = ws_map.get(task_type)
                if ws_name and ws_name in bpy.data.workspaces:
                    bpy.context.window.workspace = bpy.data.workspaces[ws_name]
                    
            except Exception as e:
                print(f"[OPENSTUDIO HUB] Fallo al abrir archivo: {e}")
        else:
            print(f"[OPENSTUDIO HUB] ADVERTENCIA: Archivo base inexistente en {target_file}")

        print("="*50 + "\n")
        return None # Destruye el timer para evitar ejecuciones repetidas

    except Exception as e:
        print(f"[OPENSTUDIO HUB] ❌ ERROR FATAL EN ARRANQUE: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("="*50 + "\n")
        # GARANTÍA ABSOLUTA DE DESTRUCCIÓN DEL TIMER
        return None 

# =================================================================
# 4. REGISTRO EN EL MOTOR DE BLENDER
# =================================================================
def register():
    # Registrar el hook persistente
    if _apply_persistent_overrides not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_apply_persistent_overrides)
        
    # Disparar la secuencia de arranque un instante después de que la UI respire
    bpy.app.timers.register(_startup_sequence, first_interval=0.1)

if __name__ == "__main__":
    register()
