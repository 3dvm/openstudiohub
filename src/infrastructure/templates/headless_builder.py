# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/templates/headless_builder.py
# Rol Arquitectónico: DCC Scripting / Creador Maestro de Archivos (VFS)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
# =========================================================================================

"""
Script ejecutado en modo Headless (background) por el ProjectBuilder o el
ProductionManager. Recibe órdenes mediante variables de entorno para ensamblar
archivos .blend desde cero.

La **configuración de add-ons** (activación, autenticación, monkey patches,
restauración de contexto) se delega a los scripts ``cfg_<addon>.py``
autogenerados y se invoca a través de ``addon_runtime``. Este script solo
conserva la orquestación de construcción (forjado) de archivos.
"""

import os
import sys
from pathlib import Path

import bpy

# =================================================================
# 0. BOOTSTRAP: Hacer importables el paquete 'src' del Hub y los
#    módulos de soporte desplegados en el sandbox (env_contract.py,
#    addon_runtime.py), que viven junto a bootstrap.py en vfs_local/.
# =================================================================
_HUB_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(_HUB_ROOT))

_TEMPLATES_DIR = Path(__file__).resolve().parent


def _resolve_support_dir():
    """Locate the deployed DCC support modules (mirrors bootstrap.py)."""
    scripts = os.environ.get("BLENDER_USER_SCRIPTS")
    if scripts:
        candidate = Path(scripts).resolve().parents[1]  # <vfs_local>
        if (candidate / "env_contract.py").exists():
            return candidate

    resources = os.environ.get("BLENDER_USER_RESOURCES")
    if resources:
        candidate = Path(resources).resolve().parent  # <vfs_local>
        if (candidate / "env_contract.py").exists():
            return candidate

    return None


_SUPPORT_DIR = _resolve_support_dir()

# The templates dir is only a development fallback; the sandbox support dir
# must win so the deployed env_contract/addon_runtime are imported.
if str(_TEMPLATES_DIR) not in sys.path:
    sys.path.insert(0, str(_TEMPLATES_DIR))
if _SUPPORT_DIR is not None and str(_SUPPORT_DIR) in sys.path:
    sys.path.remove(str(_SUPPORT_DIR))
if _SUPPORT_DIR is not None:
    sys.path.insert(0, str(_SUPPORT_DIR))

import addon_runtime
from src.domain.shared_kernel.env_contract import SandboxEnvironment

_ENV = SandboxEnvironment.from_os_environ()

_CONFIG_DIR = Path(_ENV.blender_user_scripts) / "openstudio" if _ENV.blender_user_scripts else None


# =================================================================
# 1. ACCESO A LOS ADD-ONS (delegado a los scripts autogenerados)
# =================================================================
def _kitsu_cfg():
    """Devuelve el módulo de configuración generado para Blender Kitsu."""
    return addon_runtime.load("blender_kitsu")


def _kitsu_module():
    """Devuelve el módulo real del addon Blender Kitsu cargado en memoria."""
    config_module = _kitsu_cfg()
    if config_module is not None and hasattr(config_module, "get_addon_module"):
        module = config_module.get_addon_module()
        if module is not None:
            return module
    return sys.modules.get("blender_kitsu")


def _reapply_addon_context():
    """Restaura sesión/preferencias del addon tras una operación destructiva."""
    config_module = _kitsu_cfg()
    if config_module is not None and hasattr(config_module, "on_file_opened"):
        config_module.on_file_opened()


# =================================================================
# 2. MECANISMOS DE PROTECCIÓN (build-specific)
# =================================================================
def inyectar_parche_proteccion_memoria():
    """
    Evita el crash de RNA desactivando la carga de archivos .blend
    DENTRO de los operadores de Kitsu. Cargar archivos destruye
    la instancia `self` del operador en modo Headless.
    """
    try:
        kitsu_module = _kitsu_module()
        if not kitsu_module:
            return

        # Interceptamos la referencia directamente en el módulo 'ops' donde se usa
        kitsu_ops = kitsu_module.shot_builder.ops

        def parche_open_template(task_type_name):
            print(f"[HeadlessBuilder] 🛡️ Bypass de plantilla '{task_type_name}' ejecutado para proteger memoria RNA.")
            pass

        kitsu_ops.open_template_as_homefile = parche_open_template
        print("[HeadlessBuilder] ✓ Parche de protección de memoria RNA inyectado.")

    except Exception as error:  # noqa: BLE001
        print(f"[HeadlessBuilder] ⚠️ Advertencia: No se pudo inyectar protección de memoria: {error}")


def _inyectar_parche_guardado_sincrono():
    """Sobrescribe el guardado de Kitsu para que sea síncrono (Anti-Timer)."""
    kitsu_module = _kitsu_module()
    if not kitsu_module:
        return
    try:
        kitsu_file_save = kitsu_module.shot_builder.file_save

        def save_shot_sync(file_path: str) -> bool:
            path_obj = Path(file_path)
            if path_obj.exists():
                print(f"[HeadlessBuilder] ⚠️ El archivo ya existe: {path_obj.name}")
                return False

            path_obj.parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_mainfile(filepath=str(path_obj), relative_remap=True)
            print(f"[HeadlessBuilder] 💾 Archivo físico escrito síncronamente: {path_obj.name}")
            return True

        kitsu_file_save.save_shot_builder_file = save_shot_sync
        print("[HeadlessBuilder] ✓ Parche de guardado síncrono (Anti-Timer) inyectado exitosamente.")
    except AttributeError as attr_err:
        print(f"[HeadlessBuilder] ⚠️ No se pudo inyectar el parche Anti-Timer: {attr_err}")


def cargar_plantilla_segura(task_type_name: str = None, app_template: str = None):
    """Carga el template y delega la restauración de contexto al add-on."""
    kitsu_module = _kitsu_module()

    try:
        if app_template:
            print(f"[HeadlessBuilder] 🎬 Cargando App-Template '{app_template}' en contexto seguro...")
            bpy.ops.wm.read_homefile(app_template=app_template)
        elif task_type_name and kitsu_module:
            template_path = kitsu_module.shot_builder.template.get_template_for_task_type(task_type_name)
            if template_path and template_path.exists():
                print(f"[HeadlessBuilder] 🎬 Cargando plantilla '{task_type_name}' en contexto seguro...")
                bpy.ops.wm.open_mainfile(filepath=str(template_path), load_ui=False)
    except Exception as error:  # noqa: BLE001
        print(f"[HeadlessBuilder] Info: Omitiendo plantilla ({error})")

    # Reinyectar contexto/preferencias/sesión del add-on tras cargar el archivo.
    _reapply_addon_context()
    _inyectar_parche_guardado_sincrono()


def _guardar_entidad_forjada(filepath_str: str, debug_label: str = "ENTIDAD"):
    """
    Centraliza la I/O de disco: crea los directorios padres si no existen
    y ejecuta el guardado síncrono del archivo .blend maestro.
    """
    out_path = Path(filepath_str)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_mainfile(filepath=str(out_path), relative_remap=True)

    if not out_path.exists():
        raise RuntimeError(f"save_mainfile did not write '{out_path}'")

    print(f"[HeadlessBuilder DEBUG] 💾 GUARDADO DE {debug_label} EXITOSO EN: {out_path}")
    return out_path


# =======================================================
# CONSTRUCTORES ESPECÍFICOS (Estrategias)
# =======================================================
def forge_storyboard():
    print("[HeadlessBuilder] Iniciando forjado del Archivo Maestro de Storyboard...")
    inyectar_parche_proteccion_memoria()
    _reapply_addon_context()

    # 1. Cargamos la plantilla nativa de Blender para Storyboard (2D Animation)
    try:
        print("[HeadlessBuilder] 🎬 Cargando plantilla nativa 'Storyboarding'...")
        cargar_plantilla_segura(app_template="Storyboarding")
    except Exception as error:  # noqa: BLE001
        print(f"[HeadlessBuilder] ⚠️ Plantilla Storyboarding no encontrada, usando default. Error: {error}")
        bpy.ops.wm.read_homefile()

    try:
        # 2. Extraer contexto inyectado por el Hub
        project_root = Path((_ENV.project_root or ""))
        vfs_svn = (_ENV.production_folder or "svn")
        seq_name = (_ENV.target_sequence or "SQ000").lower()

        # 3. Construir la ruta (En la carpeta de edición, tal como lo definimos)
        out_path = project_root / vfs_svn / "edit" / "storyboards" / f"{seq_name}-storyboard.blend"

        # 4. Guardado manual forzado (Síncrono y bloqueante)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_mainfile(filepath=str(out_path), relative_remap=True)

        print(f"[HeadlessBuilder DEBUG] 💾 GUARDADO FORZADO EXITOSO EN: {out_path}")
        return True

    except Exception as error:  # noqa: BLE001
        print(f"[HeadlessBuilder] ❌ Fallo crítico al crear el archivo de Storyboard: {error}")
        return False


def forge_edit_master() -> bool:
    print("[HeadlessBuilder] Iniciando forjado del Archivo Maestro de Edición...")

    kitsu_module = _kitsu_module()
    if not kitsu_module:
        print(
            "[HeadlessBuilder] ❌ Edit abortado: el addon 'blender_kitsu' no está disponible. "
            "Revisa los mensajes de addon_runtime/registro más arriba (support dir, cfg scripts)."
        )
        return False

    inyectar_parche_proteccion_memoria()
    _reapply_addon_context()

    # 1. DISPARAR LA CREACIÓN DEL EDIT
    try:
        project = kitsu_module.cache.project_active_get()
        project_name = getattr(project, "name", "")
        project_id = getattr(project, "id", "")
        print(f"[HeadlessBuilder] Proyecto activo Kitsu: {project_name!r} (id={project_id!r})")
        if not project_id:
            print(
                "[HeadlessBuilder] ❌ Edit abortado: no hay proyecto activo en Kitsu. "
                "La sesión del addon no se autenticó (revisa credenciales/host)."
            )
            return False

        print("[HeadlessBuilder] 🎬 Ejecutando kitsu.create_edit_file()...")
        result = bpy.ops.kitsu.create_edit_file(create_kitsu_edit=True, save_file=False)
        print(f"[HeadlessBuilder] create_edit_file result: {result}")
        if "CANCELLED" in result:
            print("[HeadlessBuilder] ❌ create_edit_file fue cancelado por el addon.")
            return False
        print("[HeadlessBuilder] ✓ Archivo Maestro de Edición configurado en memoria por Kitsu.")

        # 2. EXTRACCIÓN DE LA RUTA Y GUARDADO FÍSICO
        edit_entity = kitsu_module.cache.edit_default_get(episode_id=bpy.context.scene.kitsu.episode_active_id)
        if not edit_entity or not getattr(edit_entity, "id", ""):
            print("[HeadlessBuilder] ❌ No se pudo resolver la entidad Edit de Kitsu.")
            return False

        filepath_str = edit_entity.get_filepath(bpy.context)

        # The add-on derives the master name from the Kitsu project name (which
        # may be mixed case). The Hub standard is lower-case file names, so
        # normalize the file name before saving. Rename any previously created
        # mixed-case master so there is a single canonical file.
        original_path = Path(filepath_str)
        out_path = original_path.with_name(original_path.name.lower())
        if out_path != original_path and original_path.exists() and not out_path.exists():
            try:
                original_path.rename(out_path)
            except OSError as rename_error:
                print(f"[HeadlessBuilder] ⚠️ No se pudo renombrar el Edit a minúsculas: {rename_error}")
        print(f"[HeadlessBuilder] Ruta de guardado Edit (normalizada): {out_path}")

        out_path = _guardar_entidad_forjada(str(out_path), "EDIT MASTER")
        if not out_path.exists():
            print(f"[HeadlessBuilder] ❌ El archivo Edit no existe tras guardar: {out_path}")
            return False

        print(f"[HeadlessBuilder] ✓ EDIT MASTER creado en: {out_path}")
        return True

    except Exception as error:
        import traceback

        print(f"[HeadlessBuilder] ❌ Fallo crítico al crear el archivo Edit: {error}")
        traceback.print_exc()
        return False


def forge_shot():
    print("[HeadlessBuilder] Iniciando forjado de Shot (Toma)...")
    inyectar_parche_proteccion_memoria()

    try:
        kitsu_module = _kitsu_module()
        if not kitsu_module:
            print("[HeadlessBuilder] ❌ Shot abortado: el addon 'blender_kitsu' no está disponible.")
            return False
        _reapply_addon_context()

        # 1. EXTRAER NOMBRES DESDE LAS VARIABLES DE ENTORNO
        seq_name = (_ENV.kitsu_sequence_name or "")
        shot_name = (_ENV.kitsu_entity_name or "")
        task_type_name = (_ENV.kitsu_task_type_name or "Layout")

        # 2. INYECTAR VARIABLES EN LA ESCENA ACTUAL (SIMULANDO CLICS EN LA UI)
        if seq_name:
            print(f"[HeadlessBuilder] ♻️ Fijando Secuencia en Escena: {seq_name}")
            bpy.context.scene.kitsu.sequence_active_name = seq_name

        if shot_name:
            print(f"[HeadlessBuilder] ♻️ Fijando Shot en Escena: {shot_name}")
            bpy.context.scene.kitsu.shot_active_name = shot_name

        if task_type_name:
            print(f"[HeadlessBuilder] ♻️ Fijando Task Type en Escena: {task_type_name}")
            bpy.context.scene.kitsu.task_type_active_name = task_type_name

        # 3. FORJAR EL ARCHIVO
        print("[HeadlessBuilder] 🎬 Ejecutando kitsu.build_new_shot()...")
        bpy.ops.kitsu.build_new_shot(save_file=False)

        # 4. EXTRACCIÓN DE LA RUTA Y GUARDADO
        task_type = kitsu_module.cache.task_type_active_get()
        shot = kitsu_module.cache.shot_active_get()
        filepath_str = shot.get_filepath(bpy.context, task_type.get_short_name() if task_type else "")

        out_path = _guardar_entidad_forjada(filepath_str, "SHOT")

        # ==========================================================
        # 5. REGISTRAR RUTA EN EL CUSTOM FIELD DE LA TAREA EN KITSU
        # ==========================================================
        mapped = False
        try:
            from src.infrastructure.kitsu_manager import KitsuManager

            kitsu_mgr = KitsuManager()
            shot_id = shot.id
            tt_id = task_type.id

            task = kitsu_mgr.get_task_by_entity(shot_id, tt_id)

            if task:
                vfs_root = Path((_ENV.project_root or "")) / (_ENV.production_folder or "svn")
                rel_path = out_path.relative_to(vfs_root).as_posix()

                task_data = task.get("data")
                if not task_data:
                    task_data = {}

                task_data["filepath"] = rel_path
                task["data"] = task_data
                kitsu_mgr.update_task(task)
                mapped = True

                print(f"[HeadlessBuilder] ✓ Metadata guardada en Kitsu Task ({task_type.name}): {rel_path}")
            else:
                print(f"[HeadlessBuilder] ⚠️ Tarea {task_type.name} no encontrada en Kitsu para actualizar metadatos.")
        except Exception as api_e:  # noqa: BLE001
            print(f"[HeadlessBuilder] ❌ Error actualizando la Tarea en Kitsu: {api_e}")
        # ==========================================================

        if not mapped:
            print("[HeadlessBuilder] ❌ El Shot se guardó pero no se pudo enlazar a su tarea en Kitsu.")
            return False

        return True

    except Exception as error:  # noqa: BLE001
        import traceback

        print(f"[HeadlessBuilder] ❌ Fallo crítico al crear el Shot: {error}")
        traceback.print_exc()
        return False


def forge_asset():
    print("[HeadlessBuilder] Iniciando forjado de Asset (Recurso)...")
    inyectar_parche_proteccion_memoria()

    try:
        kitsu_module = _kitsu_module()
        if not kitsu_module:
            print("[HeadlessBuilder] ❌ Asset abortado: el addon 'blender_kitsu' no está disponible.")
            return False
        _reapply_addon_context()

        # 1. RECUPERAR IDs DEL ENTORNO
        target_id = (_ENV.target_entity_id or "")
        asset_type_id = (_ENV.kitsu_asset_type_id or "")

        print(f"[DEBUG Headless] TARGET_ID recibido: '{target_id}'")
        print(f"[DEBUG Headless] ASSET_TYPE_ID recibido: '{asset_type_id}'")

        # 2. EXTRAER NOMBRES DIRECTAMENTE VÍA ID DE Kitsu/Gazu
        from src.infrastructure.kitsu_manager import KitsuManager

        kitsu_mgr = KitsuManager()
        asset_type_name = ""
        asset_name = ""

        if asset_type_id:
            try:
                at_data = kitsu_mgr.get_asset_type(asset_type_id)
                asset_type_name = at_data.get("name", "") if at_data else ""
            except Exception as error:  # noqa: BLE001
                print(f"[HeadlessBuilder] Error obteniendo Asset Type: {error}")

        if target_id:
            try:
                asset_data = kitsu_mgr.get_asset(target_id)
                asset_name = asset_data.get("name", "") if asset_data else ""
            except Exception as error:  # noqa: BLE001
                print(f"[HeadlessBuilder] Error obteniendo Asset: {error}")

        # 3. INYECTAR VARIABLES EN LA ESCENA ACTUAL ANTES DEL OPERADOR
        if asset_type_name:
            print(f"[HeadlessBuilder] ♻️ Fijando Asset Type en Escena: {asset_type_name}")
            bpy.context.scene.kitsu.asset_type_active_name = asset_type_name

        if asset_name:
            print(f"[HeadlessBuilder] ♻️ Fijando Asset en Escena: {asset_name}")
            bpy.context.scene.kitsu.asset_active_name = asset_name

        # 4. FORJAR EL ARCHIVO (El operador carga la plantilla internamente)
        print("[HeadlessBuilder] 🎬 Ejecutando kitsu.build_new_asset()...")
        bpy.ops.kitsu.build_new_asset(save_file=False)

        # 5. RESOLVER LA RUTA DE LA TAREA Y GUARDAR
        asset = kitsu_module.cache.asset_active_get()
        task_type_name = (_ENV.kitsu_task_type_name or "")
        vfs_root = Path((_ENV.project_root or "")) / (_ENV.production_folder or "svn")

        relative_path = (_ENV.task_file_path or "")
        if not relative_path:
            from src.domain.production.naming import NamingPolicy

            try:
                relative_path = str(NamingPolicy.asset_path(asset_type_name, asset_name, task_type_name))
            except Exception:  # noqa: BLE001
                relative_path = ""

        if relative_path:
            out_path = vfs_root / relative_path
        else:
            # Fallback: Kitsu's own asset master path.
            out_path = Path(asset.get_filepath(bpy.context))

        out_path = _guardar_entidad_forjada(str(out_path), "ASSET")

        # 6. MAPEAR LA RUTA EN LA TAREA DE KITSU (data.filepath)
        mapped = False
        if task_type_name:
            try:
                rel_path = out_path.relative_to(vfs_root).as_posix()
                task_type = kitsu_mgr.get_task_type_by_name(task_type_name, for_entity="Asset")
                if task_type:
                    task = kitsu_mgr.get_task_by_entity(asset.id, task_type.get("id", ""))
                    if task:
                        task_data = task.get("data") or {}
                        task_data["filepath"] = rel_path
                        task["data"] = task_data
                        kitsu_mgr.update_task(task)
                        mapped = True
                        print(f"[HeadlessBuilder] ✓ Ruta mapeada a la tarea Asset ({task_type_name}): {rel_path}")
                    else:
                        print(f"[HeadlessBuilder] ⚠️ Tarea '{task_type_name}' no encontrada para mapear.")
            except Exception as api_error:  # noqa: BLE001
                print(f"[HeadlessBuilder] ❌ Error mapeando la tarea del Asset: {api_error}")

        if task_type_name and not mapped:
            print(
                f"[HeadlessBuilder] ❌ El Asset se guardó pero no se pudo enlazar "
                f"a la tarea '{task_type_name}' en Kitsu. Revisa que la tarea exista."
            )
            return False

        return True

    except Exception as error:  # noqa: BLE001
        import traceback

        print(f"[HeadlessBuilder] ❌ Fallo crítico al crear el Asset: {error}")
        traceback.print_exc()
        return False


# =======================================================
# MAIN ORCHESTRATOR
# =======================================================
def main():
    print("\n" + "=" * 50)
    print("[OPENSTUDIO HUB] Iniciando Constructor Headless...")

    # --- Diagnostics: make the addon-resolution path visible. ---
    print(f"[HeadlessBuilder] Support dir: {_SUPPORT_DIR}")
    print(f"[HeadlessBuilder] Config dir: {_CONFIG_DIR}")
    if _CONFIG_DIR is not None and _CONFIG_DIR.exists():
        cfg_scripts = sorted(p.name for p in _CONFIG_DIR.glob("cfg_*.py"))
        print(f"[HeadlessBuilder] cfg scripts: {cfg_scripts}")

    # Delegar la configuración de add-ons a los scripts autogenerados.
    registered = addon_runtime.register_all(_CONFIG_DIR)
    print(f"[HeadlessBuilder] Add-ons configurados: {registered}")

    build_target = (_ENV.build_target or "STORYBOARD").upper()
    print(f"[HeadlessBuilder] Build target: {build_target}")

    builders = {
        "STORYBOARD": forge_storyboard,
        "EDIT": forge_edit_master,
        "SHOT": forge_shot,
        "ASSET": forge_asset,
    }

    builder = builders.get(build_target)
    if builder is None:
        print(f"[HeadlessBuilder] ❌ Error: Objetivo de construcción desconocido -> {build_target}")
        ok = False
    else:
        ok = bool(builder())

    print(f"[OPENSTUDIO HUB] RESULT: {'OK' if ok else 'FAILED'}")
    print("[OPENSTUDIO HUB] Constructor Headless Finalizado.")
    print("=" * 50 + "\n")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
