# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/templates/headless_builder.py
# Rol Arquitectónico: DCC Scripting / Creador Maestro de Archivos (VFS & Kitsu)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
# =========================================================================================

"""
Script ejecutado en modo Headless (background) por el ProjectBuilder o el ProductionManager.
Recibe órdenes mediante variables de entorno para ensamblar archivos .blend desde cero
utilizando los operadores nativos del add-on de Blender Kitsu.
"""

import bpy
import os
import sys
import importlib
from pathlib import Path

# =================================================================
# 0. BOOTSTRAP: Hacer importable el paquete 'core' del Hub
#    (este script se ejecuta con el Python EMBEBIDO de Blender, donde
#    el root del repositorio no está en sys.path por defecto).
# =================================================================
_HUB_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(_HUB_ROOT))

# =================================================================
# 1. RESOLUCIÓN DINÁMICA DE EXTENSIONES (Paridad con bootstrap.py)
# =================================================================
def _get_kitsu_addon_key() -> str:
    """Encuentra la clave exacta de Kitsu en el nuevo sistema de extensiones (v4.2+)."""
    # 1. Buscar en preferencias activas
    for key in bpy.context.preferences.addons.keys():
        if "blender_kitsu" in key:
            return key
            
    # 2. Si no está activa, buscar en la lista de módulos instalados
    import addon_utils
    for mod in addon_utils.modules():
        if "blender_kitsu" in mod.__name__:
            return mod.__name__
            
    return "blender_kitsu" # Fallback legacy

def _get_kitsu_module():
    """Devuelve el módulo cargado en memoria de Kitsu."""
    addon_key = _get_kitsu_addon_key()
    return sys.modules.get(addon_key)

def despertar_kitsu_module():
    """Busca y activa el módulo usando el operador oficial de Blender asegurando inicialización RNA."""
    addon_key = _get_kitsu_addon_key()
    
    try:
        bpy.ops.preferences.addon_enable(module=addon_key)
    except Exception as e:
        print(f"[HeadlessBuilder] Advertencia al habilitar {addon_key}: {e}")
        
    # Forzar la importación a sys.modules
    importlib.import_module(addon_key)
    return sys.modules.get(addon_key), addon_key


# =================================================================
# 2. MECANISMOS DE PROTECCIÓN
# =================================================================
def inyectar_parche_proteccion_memoria():
    """
    Evita el crash de RNA desactivando la carga de archivos .blend 
    DENTRO de los operadores de Kitsu. Cargar archivos destruye 
    la instancia `self` del operador en modo Headless.
    """
    try:
        kitsu_module = _get_kitsu_module()
        if not kitsu_module: return

        # Interceptamos la referencia directamente en el módulo 'ops' donde se usa
        kitsu_ops = kitsu_module.shot_builder.ops
        
        def parche_open_template(task_type_name):
            print(f"[HeadlessBuilder] 🛡️ Bypass de plantilla '{task_type_name}' ejecutado para proteger memoria RNA.")
            pass
            
        kitsu_ops.open_template_as_homefile = parche_open_template
        print("[HeadlessBuilder] ✓ Parche de protección de memoria RNA inyectado.")
        
    except Exception as e:
        print(f"[HeadlessBuilder] ⚠️ Advertencia: No se pudo inyectar protección de memoria: {e}")

def cargar_plantilla_segura(task_type_name: str = None, app_template: str = None):
    """Carga el template y restaura el contexto de Kitsu borrado por Blender."""
    kitsu_module = _get_kitsu_module()
    addon_key = _get_kitsu_addon_key()
    
    # 1. EXTRACCIÓN DE SALVAVIDAS (Antes de destruir la memoria de la escena)
    project_id = ""
    if kitsu_module and addon_key in bpy.context.preferences.addons:
        prefs = bpy.context.preferences.addons[addon_key].preferences
        project_id = getattr(prefs, "project_active_id", "")
        
    try:
        if app_template:
            print(f"[HeadlessBuilder] 🎬 Cargando App-Template '{app_template}' en contexto seguro...")
            bpy.ops.wm.read_homefile(app_template=app_template)
        elif task_type_name and kitsu_module:
            template_path = kitsu_module.shot_builder.template.get_template_for_task_type(task_type_name)
            if template_path and template_path.exists():
                print(f"[HeadlessBuilder] 🎬 Cargando plantilla '{task_type_name}' en contexto seguro...")
                bpy.ops.wm.open_mainfile(filepath=str(template_path), load_ui=False)
    except Exception as e:
        print(f"[HeadlessBuilder] Info: Omitiendo plantilla ({e})")
        
    # 2. REINYECCIÓN DEL CONTEXTO Y AUTENTICACIÓN
    if kitsu_module and project_id:
        print("[HeadlessBuilder] 🔑 Re-autenticando sesión (Bypass de amnesia de seguridad)...")
        # Forzamos el login nuevamente para reconstruir el token de Gazu borrado al abrir el archivo
        bpy.ops.kitsu.session_start('EXEC_DEFAULT')
        
        print(f"[HeadlessBuilder] ♻️ Restaurando contexto Kitsu en la nueva escena (Project ID: {project_id})")
        kitsu_module.cache.project_active_set_by_id(bpy.context, project_id)

        # =======================================================
        # 3. REINYECCIÓN DEL MONKEY PATCH VFS
        # =======================================================
        vfs_svn = os.environ.get("OPENSTUDIO_PRODUCTION_FOLDER", "svn")
        try:
            kitsu_prefs_mod = importlib.import_module(f"{kitsu_module.__name__}.prefs")
            
            # 1. Parche a nivel de módulo (Legacy)
            def custom_root_dir_get(context):
                pref_instance = kitsu_prefs_mod.addon_prefs_get(context)
                return Path(pref_instance.project_root_dir) / vfs_svn
                
            kitsu_prefs_mod.project_root_dir_get = custom_root_dir_get
            
            # 2. NUEVO: Parche profundo a nivel de clase para eliminar 'project_files'
            if hasattr(kitsu_prefs_mod, "KITSU_addon_preferences"):
                def custom_project_root_path(self):
                    # 'self' es la instancia de preferencias. Devolvemos la ruta limpia.
                    return Path(self.project_root_dir) / vfs_svn
                
                # Inyectamos el método directamente en la clase original del add-on
                kitsu_prefs_mod.KITSU_addon_preferences.project_root_path = custom_project_root_path
                
            print(f"[HeadlessBuilder] 🛡️ Monkey patch VFS ({vfs_svn}) inyectado (Bypass 'project_files').")
        except Exception as e:
            print(f"[HeadlessBuilder] ⚠️ Advertencia: Fallo al inyectar Monkey Patch VFS: {e}")

        # =======================================================
        # 4. PARCHE DE GUARDADO SÍNCRONO (Anti-Timer)
        # =======================================================
        try:
            kitsu_file_save = kitsu_module.shot_builder.file_save
            
            def save_shot_sync(file_path: str) -> bool:
                path_obj = Path(file_path)
                if path_obj.exists(): 
                    print(f"[HeadlessBuilder] ⚠️ El archivo ya existe: {path_obj.name}")
                    return False
                    
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                
                # Guardado instantáneo, bloqueando el hilo principal hasta terminar
                bpy.ops.wm.save_mainfile(filepath=str(path_obj), relative_remap=True)
                print(f"[HeadlessBuilder] 💾 Archivo físico escrito síncronamente: {path_obj.name}")
                return True
                
            # Sobrescribimos la función original
            kitsu_file_save.save_shot_builder_file = save_shot_sync
            print("[HeadlessBuilder] ✓ Parche de guardado síncrono (Anti-Timer) inyectado exitosamente.")
        except AttributeError as attr_err:
            print(f"[HeadlessBuilder] ⚠️ No se pudo inyectar el parche Anti-Timer: {attr_err}")


# =======================================================
# 3. FUNCIÓN MAESTRA DE I/O Y AUTENTICACIÓN
# =======================================================
def autenticar_kitsu_headless(kitsu_module, mod_name):
    """
    Inyecta el Host y las credenciales (provistas por EnvLauncher a través del OS env)
    dentro del addon de Kitsu e inicia sesión de forma estricta.
    Resuelve el problema de Gazu intentando conectar a 'gazu.change.serverhost'.
    """
    hub_host = os.environ.get("OPENSTUDIO_KITSU_HOST", "http://localhost:8080/api")
    hub_user = os.environ.get("OPENSTUDIO_KITSU_USER", "")
    hub_pwd = os.environ.get("OPENSTUDIO_KITSU_PWD", "")
    project_id = os.environ.get("OPENSTUDIO_KITSU_PROJECT_ID", "")
    project_root = os.environ.get("OPENSTUDIO_PROJECT_ROOT", "")
    
    if not (hub_user and hub_pwd):
        print(f"[HeadlessBuilder] ⚠️ Advertencia: No se proporcionaron credenciales completas para {hub_host}")
        return False

    print(f"[HeadlessBuilder] 🔒 Autenticando estricto en RAM como: {hub_user} en {hub_host}")
    
    prefs = bpy.context.preferences.addons[mod_name].preferences
    prefs.host = hub_host
    prefs.email = hub_user
    prefs.passwd = hub_pwd
    
    if project_root:
        prefs.project_root_dir = project_root

    try:
        bpy.ops.kitsu.session_start('EXEC_DEFAULT')
    except Exception as e:
        print(f"[HeadlessBuilder] ❌ Error de autenticación con Kitsu API: {e}")
        return False
    
    if project_id:
        print(f"[HeadlessBuilder] ♻️ Fijando proyecto activo global (ID: {project_id})")
        kitsu_module.cache.project_active_set_by_id(bpy.context, project_id)
        prefs.project_active_id = project_id

    # Inyectar el Monkey Patch VFS Inicial
    vfs_svn = os.environ.get("OPENSTUDIO_PRODUCTION_FOLDER", "svn")
    try:
        kitsu_prefs_mod = importlib.import_module(f"{kitsu_module.__name__}.prefs")
        def custom_root_dir_get(context):
            pref_instance = kitsu_prefs_mod.addon_prefs_get(context)
            return Path(pref_instance.project_root_dir) / vfs_svn
            
        kitsu_prefs_mod.project_root_dir_get = custom_root_dir_get
    except Exception as e:
        print(f"[HeadlessBuilder] ⚠️ Advertencia: Fallo al inyectar Monkey Patch VFS inicial: {e}")

    return True


def _guardar_entidad_forjada(filepath_str: str, debug_label: str = "ENTIDAD"):
    """
    Centraliza la I/O de disco: crea los directorios padres si no existen
    y ejecuta el guardado síncrono del archivo .blend maestro.
    """
    out_path = Path(filepath_str)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Guardado manual forzado (Síncrono y bloqueante)
    bpy.ops.wm.save_mainfile(filepath=str(out_path), relative_remap=True)
    print(f"[HeadlessBuilder DEBUG] 💾 GUARDADO DE {debug_label} EXITOSO EN: {out_path}")
    return out_path


# =======================================================
# CONSTRUCTORES ESPECÍFICOS (Estrategias)
# =======================================================
def forjar_storyboard():
    print("[HeadlessBuilder] Iniciando forjado del Archivo Maestro de Storyboard...")
    inyectar_parche_proteccion_memoria()
    
    # Para consistencia y evitar sorpresas, despertamos y autenticamos
    kitsu_module, mod_name = despertar_kitsu_module()
    if kitsu_module:
        autenticar_kitsu_headless(kitsu_module, mod_name)
    
    # 1. Cargamos la plantilla nativa de Blender para Storyboard (2D Animation)
    try:
        print("[HeadlessBuilder] 🎬 Cargando plantilla nativa 'Storyboarding'...")
        cargar_plantilla_segura(app_template="Storyboarding")
    except Exception as e:
        print(f"[HeadlessBuilder] ⚠️ Plantilla Storyboarding no encontrada, usando default. Error: {e}")
        bpy.ops.wm.read_homefile()
        
    try:
        # 2. Extraer contexto inyectado por el Hub
        project_root = Path(os.environ.get("OPENSTUDIO_PROJECT_ROOT", ""))
        vfs_svn = os.environ.get("OPENSTUDIO_PRODUCTION_FOLDER", "svn")
        seq_name = os.environ.get("OPENSTUDIO_TARGET_SEQUENCE", "SQ000").lower()
        
        # 3. Construir la ruta (En la carpeta de edición, tal como lo definimos)
        out_path = project_root / vfs_svn / "edit" / "storyboards" / f"{seq_name}-storyboard.blend"
        
        # 4. Guardado manual forzado (Síncrono y bloqueante)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_mainfile(filepath=str(out_path), relative_remap=True)
        
        print(f"[HeadlessBuilder DEBUG] 💾 GUARDADO FORZADO EXITOSO EN: {out_path}")
        
    except Exception as e:
        print(f"[HeadlessBuilder] ❌ Fallo crítico al crear el archivo de Storyboard: {e}")


def forjar_edit_master():
    print("[HeadlessBuilder] Iniciando forjado del Archivo Maestro de Edición...")
    inyectar_parche_proteccion_memoria()
    
    # 0. DESPERTAR EL MÓDULO (Nos devuelve el módulo y su nombre oficial)
    kitsu_module, mod_name = despertar_kitsu_module()
    if not kitsu_module: return
    
    # 1. AUTENTICACIÓN CENTRALIZADA
    autenticar_kitsu_headless(kitsu_module, mod_name)

    # 2. DISPARAR LA CREACIÓN DEL EDIT
    try:
        print("[HeadlessBuilder] 🎬 Ejecutando kitsu.create_edit_file()...")
        bpy.ops.kitsu.create_edit_file(create_kitsu_edit=True, save_file=False)
        print("[HeadlessBuilder] ✓ Archivo Maestro de Edición configurado en memoria por Kitsu.")

        # 3. EXTRACCIÓN DE LA RUTA Y GUARDADO FÍSICO
        edit_entity = kitsu_module.cache.edit_default_get(episode_id=bpy.context.scene.kitsu.episode_active_id)
        filepath_str = edit_entity.get_filepath(bpy.context)
        
        _guardar_entidad_forjada(filepath_str, "EDIT MASTER")
        
    except Exception as e:
        import traceback
        print(f"[HeadlessBuilder] ❌ Fallo crítico al crear el archivo Edit: {e}")
        traceback.print_exc()


def forjar_shot():
    print("[HeadlessBuilder] Iniciando forjado de Shot (Toma)...")
    inyectar_parche_proteccion_memoria()
    
    try:
        kitsu_module, mod_name = despertar_kitsu_module()
        if not kitsu_module: return

        # 1. AUTENTICACIÓN CENTRALIZADA
        autenticar_kitsu_headless(kitsu_module, mod_name)

        # 2. EXTRAER NOMBRES DESDE LAS VARIABLES DE ENTORNO
        seq_name = os.environ.get("OPENSTUDIO_KITSU_SEQUENCE_NAME", "")
        shot_name = os.environ.get("OPENSTUDIO_KITSU_ENTITY_NAME", "")
        task_type_name = os.environ.get("OPENSTUDIO_KITSU_TASK_TYPE_NAME", "Layout")
        
        # 3. PREPARAR PLANTILLA USANDO LA TAREA
        # task_type = kitsu_module.cache.task_type_active_get()
        # if task_type:
        #     cargar_plantilla_segura(task_type_name=task_type.name)
        # else:
        #     cargar_plantilla_segura()
        # 4. INYECTAR VARIABLES EN LA ESCENA ACTUAL (SIMULANDO CLICS EN LA UI)
        if seq_name:
            print(f"[HeadlessBuilder] ♻️ Fijando Secuencia en Escena: {seq_name}")
            bpy.context.scene.kitsu.sequence_active_name = seq_name
            
        if shot_name:
            print(f"[HeadlessBuilder] ♻️ Fijando Shot en Escena: {shot_name}")
            bpy.context.scene.kitsu.shot_active_name = shot_name

        if task_type_name:
            print(f"[HeadlessBuilder] ♻️ Fijando Task Type en Escena: {task_type_name}")
            bpy.context.scene.kitsu.task_type_active_name = task_type_name 

        # 5. FORJAR EL ARCHIVO
        print("[HeadlessBuilder] 🎬 Ejecutando kitsu.build_new_shot()...")
        bpy.ops.kitsu.build_new_shot(save_file=False)
        
        # 6. EXTRACCIÓN DE LA RUTA Y GUARDADO
        task_type = kitsu_module.cache.task_type_active_get()
        shot = kitsu_module.cache.shot_active_get()
        filepath_str = shot.get_filepath(bpy.context, task_type.get_short_name() if task_type else "")
        
        out_path = _guardar_entidad_forjada(filepath_str, "SHOT")
        
        # ==========================================================
        # 7. REGISTRAR RUTA EN EL CUSTOM FIELD DE LA TAREA EN KITSU
        # ==========================================================
        try:
            from core.kitsu_manager import KitsuManager
            kitsu_mgr = KitsuManager()
            # EXTRAEMOS LOS IDs CRUDOS (.id) DE LOS OBJETOS DE BLENDER_KITSU
            shot_id = shot.id
            tt_id = task_type.id
            
            # Usamos los IDs en formato texto para buscar en gazu
            task = kitsu_mgr.get_task_by_entity(shot_id, tt_id)
            
            if task:
                # Calculamos la ruta relativa al VFS (Ej: pro/shots/01/010/010-layout.blend)
                vfs_root = Path(os.environ.get("OPENSTUDIO_PROJECT_ROOT", "")) / os.environ.get("OPENSTUDIO_PRODUCTION_FOLDER", "svn")
                rel_path = out_path.relative_to(vfs_root).as_posix()
                
                # Preparamos e inyectamos los datos en Kitsu
                task_data = task.get("data")
                if not task_data: 
                    task_data = {}
                    
                task_data["filepath"] = rel_path
                task["data"] = task_data
                #gazu.task.update_task(task["id"], task_data)
                kitsu_mgr.update_task(task)
                
                print(f"[HeadlessBuilder] ✓ Metadata guardada en Kitsu Task ({task_type.name}): {rel_path}")
            else:
                print(f"[HeadlessBuilder] ⚠️ Tarea {task_type.name} no encontrada en Kitsu para actualizar metadatos.")
        except Exception as api_e:
            print(f"[HeadlessBuilder] ❌ Error actualizando la Tarea en Kitsu: {api_e}")
        # ==========================================================

    except Exception as e:
        import traceback
        print(f"[HeadlessBuilder] ❌ Fallo crítico al crear el Shot: {e}")
        traceback.print_exc()

def forjar_asset():
    print("[HeadlessBuilder] Iniciando forjado de Asset (Recurso)...")
    inyectar_parche_proteccion_memoria()
    
    try:
        kitsu_module, mod_name = despertar_kitsu_module()
        if not kitsu_module: return

        # 1. AUTENTICACIÓN CENTRALIZADA
        autenticar_kitsu_headless(kitsu_module, mod_name)

        # 2. RECUPERAR IDs DEL ENTORNO
        target_id = os.environ.get("OPENSTUDIO_TARGET_ENTITY_ID", "")
        asset_type_id = os.environ.get("OPENSTUDIO_KITSU_ASSET_TYPE_ID", "")

        # --- DEBUG TEMPORAL ---
        print(f"[DEBUG Headless] TARGET_ID recibido: '{target_id}'")
        print(f"[DEBUG Headless] ASSET_TYPE_ID recibido: '{asset_type_id}'")
        # ----------------------
        
        # 3. EXTRAER NOMBRES DIRECTAMENTE VÍA ID DE Kitsu/Gazu
        from core.kitsu_manager import KitsuManager
        kitsu_mgr = KitsuManager()
        asset_type_name = ""
        asset_name = ""
        
        if asset_type_id:
            try:
                at_data = kitsu_mgr.get_asset_type(asset_type_id)
                asset_type_name = at_data.get("name", "") if at_data else ""
            except Exception as e:
                print(f"[HeadlessBuilder] Error obteniendo Asset Type: {e}")
                
        if target_id:
            try:
                asset_data = kitsu_mgr.get_asset(target_id)
                asset_name = asset_data.get("name", "") if asset_data else ""
            except Exception as e:
                print(f"[HeadlessBuilder] Error obteniendo Asset: {e}")

        # 4. INYECTAR VARIABLES EN LA ESCENA ACTUAL ANTES DEL OPERADOR
        if asset_type_name:
            print(f"[HeadlessBuilder] ♻️ Fijando Asset Type en Escena: {asset_type_name}")
            bpy.context.scene.kitsu.asset_type_active_name = asset_type_name
            
        if asset_name:
            print(f"[HeadlessBuilder] ♻️ Fijando Asset en Escena: {asset_name}")
            bpy.context.scene.kitsu.asset_active_name = asset_name

        # 5. FORJAR EL ARCHIVO (El operador carga la plantilla internamente)
        print("[HeadlessBuilder] 🎬 Ejecutando kitsu.build_new_asset()...")
        bpy.ops.kitsu.build_new_asset(save_file=False)
        
        # 6. EXTRACCIÓN DE LA RUTA Y GUARDADO
        asset = kitsu_module.cache.asset_active_get()
        filepath_str = asset.get_filepath(bpy.context)
        
        _guardar_entidad_forjada(filepath_str, "ASSET")
        
    except Exception as e:
        import traceback
        print(f"[HeadlessBuilder] ❌ Fallo crítico al crear el Asset: {e}")
        traceback.print_exc()

# =======================================================
# MAIN ORCHESTRATOR
# =======================================================
def main():
    print("\n" + "="*50)
    print("[OPENSTUDIO HUB] Iniciando Constructor Headless...")
    
    build_target = os.environ.get("OPENSTUDIO_BUILD_TARGET", "STORYBOARD").upper()
    
    if build_target == "STORYBOARD":
        forjar_storyboard()
    elif build_target == "EDIT":
        forjar_edit_master()
    elif build_target == "SHOT":
        forjar_shot()
    elif build_target == "ASSET":
        forjar_asset()
    else:
        print(f"[HeadlessBuilder] ❌ Error: Objetivo de construcción desconocido -> {build_target}")

    print("[OPENSTUDIO HUB] Constructor Headless Finalizado.")
    print("="*50 + "\n")
    
    sys.exit(0)

if __name__ == "__main__":
    main()
