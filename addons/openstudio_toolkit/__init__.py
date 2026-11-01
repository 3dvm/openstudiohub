# =========================================================================================
# OPENSTUDIOHUB
# Módulo: addons/openstudio_toolkit/__init__.py
# Rol Arquitectónico: DCC Add-on Entry Point
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.6.0
# =========================================================================================

"""
Punto de entrada oficial para la extensión OpenStudio Toolkit en Blender 5.x.
Gestiona el registro de clases, módulos (como Gatekeeper) y operadores nativos.
"""

import bpy
from . import gatekeeper
from . import ui_modals
from . import hooks
from . import utils_logger
from . import preferences
from . import ui_panel

# Importaremos los módulos a medida que los vayamos construyendo en esta Fase
# from . import gatekeeper

modules = [
    gatekeeper,
    ui_modals,
    hooks,
    utils_logger,
    preferences,
    ui_panel,
]

def register():
    """Registra dinámicamente todos los submódulos del Toolkit."""
    for mod in modules:
        if hasattr(mod, "register"):
            mod.register()
    print("[OPENSTUDIO TOOLKIT] Extensión inicializada correctamente.")

def unregister():
    """Desregistra los submódulos en orden inverso para evitar dependencias colgadas."""
    for mod in reversed(modules):
        if hasattr(mod, "unregister"):
            mod.unregister()
    print("[OPENSTUDIO TOOLKIT] Extensión deshabilitada.")

if __name__ == "__main__":
    register()
