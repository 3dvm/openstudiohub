# =========================================================================================
# OPENSTUDIOHUB
# Módulo: addons/openstudio_toolkit/hooks.py
# Rol Arquitectónico: API Integration / Kitsu Synergy
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.5.0
# =========================================================================================

"""Blender load handlers for project context (splash and task timeline)."""

import bpy
import os
from pathlib import Path

def inyectar_splash_corporativo(dummy=None):
    """Atrapa el inicio de Blender y sobrescribe el logo default con la portada del Hub."""
    splash_path = os.environ.get("OPENSTUDIO_SPLASH_PATH", "")
    
    if not splash_path or not os.path.exists(splash_path):
        return
        
    img_name = Path(splash_path).name
    if img_name not in bpy.data.images:
        bpy.data.images.load(splash_path)
        
    try:
        bpy.context.preferences.view.splash_image = img_name
    except Exception as e:
        print(f"Error al insertar el splash screen: {e}")
        return False

_PROP_ASSET_TYPES = {"prop", "props"}


def ajustar_linea_tiempo_prop(dummy=None):
    """Keep prop tasks at two frames so playblasts are not hundreds of duplicates."""
    entity_type = os.environ.get("OPENSTUDIO_KITSU_ENTITY_TYPE", "").strip().upper()
    if entity_type != "ASSET":
        return

    asset_type = os.environ.get("OPENSTUDIO_KITSU_ASSET_TYPE_NAME", "").strip().lower()
    if asset_type not in _PROP_ASSET_TYPES:
        return

    try:
        scene = bpy.context.scene
        if scene.frame_start != 1 or scene.frame_end != 2:
            scene.frame_start = 1
            scene.frame_end = 2
            print("[OPENSTUDIO HOOK] Prop task timeline set to 2 frames (1-2).")
    except Exception as error:  # noqa: BLE001
        print(f"[OPENSTUDIO HOOK] Could not adjust the prop timeline: {error}")


def register():
    # This module exposes pure handlers; no bpy classes need registration.
    if inyectar_splash_corporativo not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(inyectar_splash_corporativo)
    if ajustar_linea_tiempo_prop not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(ajustar_linea_tiempo_prop)


def unregister():
    if inyectar_splash_corporativo in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(inyectar_splash_corporativo)
    if ajustar_linea_tiempo_prop in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(ajustar_linea_tiempo_prop)
