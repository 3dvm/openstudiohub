# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/templates/bootstrap.py
# Rol Arquitectónico: DCC Scripting / Hub Context (RBAC, UI & Add-on orchestration)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.7.0 (Add-on agnostic)
# =========================================================================================

"""
Script de inyección ejecutado asíncronamente al iniciar Blender.

Este script solo se encarga del **contexto del Hub**:
  * Matriz RBAC (guardrails persistentes).
  * Apertura del archivo de la tarea y forzado visual de workspaces.
  * Orquestación de los scripts ``cfg_<addon>.py`` autogenerados.

Toda la configuración específica de add-ons (p.ej. Blender Kitsu) vive en los
templates ``templates/addons/cfg_*.py.template`` y se ejecuta a través de
``addon_runtime``. El Hub ya no conoce detalles de ningún add-on.
"""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_contract import SandboxEnvironment
import addon_runtime

_ENV = SandboxEnvironment.from_os_environ()


# =================================================================
# 1. HANDLERS PERSISTENTES (Hub context: RBAC)
# =================================================================
@bpy.app.handlers.persistent
def _apply_persistent_overrides(dummy=None):
    """
    Se ejecuta CADA VEZ que se carga un archivo .blend.
    Garantiza que el Jailing RBAC nunca desaparezca.
    """
    user_role = (_ENV.user_role or "artist").lower()

    if user_role not in ["lead", "supervisor", "td"]:
        @classmethod
        def poll_restringido(cls, context):
            return False

        if hasattr(bpy.types, "ASSETPIPE_OT_force_push"):
            bpy.types.ASSETPIPE_OT_force_push.poll = poll_restringido

        if hasattr(bpy.types, "OPENSTUDIO_OT_override_sanity"):
            bpy.types.OPENSTUDIO_OT_override_sanity.poll = poll_restringido


# =================================================================
# 2. SECUENCIA DE ARRANQUE INICIAL (One-Shot Timer)
# =================================================================
def _startup_sequence():
    """
    Función de un solo uso. Configura los add-ons activos, abre el archivo,
    y establece la sesión. Retorna None para que el timer se autodestruya.
    """
    try:
        print("\n" + "=" * 50)
        print("[OPENSTUDIO HUB] Iniciando Secuencia de Arranque...")

        # 1. Delegar la configuración de add-ons a los scripts autogenerados.
        registered = addon_runtime.register_all()
        if registered:
            print(f"[OPENSTUDIO HUB] Add-ons configurados: {', '.join(registered)}")

        # 2. Carga del Archivo Maestro (contexto del Hub).
        target_file = (_ENV.target_file or "")
        task_type = (_ENV.task_type or "generic").lower()

        if target_file and os.path.exists(target_file):
            print(f"[OPENSTUDIO HUB] Cargando archivo de producción: {target_file}")
            try:
                bpy.ops.wm.open_mainfile(filepath=target_file)

                # Reacciones de los add-ons a la apertura de un .blend.
                addon_runtime.notify_file_opened()

                # Forzado Visual de Workspaces
                ws_map = {
                    "edit": "Video Editing",
                    "editorial": "Video Editing",
                    "montaje": "Video Editing",
                    "storyboard": "Storyboard",
                }
                ws_name = ws_map.get(task_type)
                if ws_name and ws_name in bpy.data.workspaces:
                    bpy.context.window.workspace = bpy.data.workspaces[ws_name]

            except Exception as error:  # noqa: BLE001
                print(f"[OPENSTUDIO HUB] Fallo al abrir archivo: {error}")
        else:
            print(f"[OPENSTUDIO HUB] ADVERTENCIA: Archivo base inexistente en {target_file}")

        print("=" * 50 + "\n")
        return None  # Destruye el timer para evitar ejecuciones repetidas

    except Exception as error:  # noqa: BLE001
        print(f"[OPENSTUDIO HUB] ❌ ERROR FATAL EN ARRANQUE: {error}")
        import traceback

        traceback.print_exc()
    finally:
        print("=" * 50 + "\n")
        # GARANTÍA ABSOLUTA DE DESTRUCCIÓN DEL TIMER
        return None


# =================================================================
# 3. REGISTRO EN EL MOTOR DE BLENDER
# =================================================================
def register():
    # Registrar el hook persistente (RBAC)
    if _apply_persistent_overrides not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_apply_persistent_overrides)

    # Disparar la secuencia de arranque un instante después de que la UI respire
    bpy.app.timers.register(_startup_sequence, first_interval=0.1)


if __name__ == "__main__":
    register()
