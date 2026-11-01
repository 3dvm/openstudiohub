# =========================================================================================
# OPENSTUDIOHUB
# Módulo: addons/openstudio_toolkit/hooks.py
# Rol Arquitectónico: API Integration / Kitsu Synergy
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.6.0
# =========================================================================================

"""Blender load handlers for the project splash screen."""

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

def register():
    # This module exposes pure handlers; no bpy classes need registration.
    if inyectar_splash_corporativo not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(inyectar_splash_corporativo)


def unregister():
    if inyectar_splash_corporativo in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(inyectar_splash_corporativo)
