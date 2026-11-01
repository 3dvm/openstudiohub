# =========================================================================================
# OPENSTUDIOHUB
# Módulo: addons/openstudio_toolkit/ui_modals.py
# Rol Arquitectónico: DCC UI / Interceptores Modales
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.5.2
# =========================================================================================

"""
Módulo de interfaces modales interactivas para el Gatekeeper.
Provee el Master QA UI, una ventana emergente unificada que obliga al usuario a resolver
inconsistencias en la escena antes de continuar con la publicación.
"""

import bpy
from . import gatekeeper

# ---------------------------------------------------------
# ESTRUCTURAS DE DATOS TEMPORALES (UI)
# ---------------------------------------------------------

class OpenStudioInfractorItem(bpy.types.PropertyGroup):
    """Estructura para listar archivos Out-of-Bounds."""
    nombre: bpy.props.StringProperty()
    ruta_actual: bpy.props.StringProperty()
    categoria: bpy.props.EnumProperty(
        name="Destino",
        items=[
            ('textures', "Textura (Base, Normal)", ""),
            ('hdri', "Entorno HDRI", ""),
            ('caches', "Caché o Simulación", "")
        ],
        default='textures'
    )

class OpenStudioGeoItem(bpy.types.PropertyGroup):
    """Estructura para listar mallas con errores matemáticos."""
    nombre: bpy.props.StringProperty()
    accion: bpy.props.EnumProperty(
        name="Resolución",
        description="Elige cómo resolver las transformaciones sucias",
        items=[
            ('apply', "Aplicar (Ctrl+A)", "Congela la escala/rotación actual"),
            ('clear', "Limpiar (Alt+G/R/S)", "Devuelve el objeto a posición cero"),
            ('ignore', "Ignorar por ahora", "No altera la malla")
        ],
        default='apply'
    )

# ---------------------------------------------------------
# INTERFAZ UNIFICADA: MASTER QA
# ---------------------------------------------------------

class OPENSTUDIO_OT_master_qa_ui(bpy.types.Operator):
    """
    Despliega el Pop-up interactivo unificado del Gatekeeper.
    Muestra dependencias externas, geometría sucia y errores de nomenclatura en un solo panel.
    """
    bl_idname = "openstudio.master_qa_ui"
    bl_label = "Master QA: Resolución de Conflictos"
    bl_description = "Resuelve todos los problemas de la escena en un solo lugar"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        """Inicializa las listas leyendo los datos del Gatekeeper."""
        context.scene.os_infractores.clear()
        context.scene.os_geo_items.clear()
        
        # 1. Poblamos la lista de Dependencias
        infractores_ext = gatekeeper.escanear_out_of_bounds()
        for item in infractores_ext:
            new_item = context.scene.os_infractores.add()
            new_item.nombre = item["nombre"]
            new_item.ruta_actual = item["ruta_actual"]
            
        # 2. Poblamos la lista de Geometría
        geo_str = context.scene.os_geo_infractores
        if geo_str:
            nombres_geo = geo_str.split(",")
            for nom in nombres_geo:
                new_item = context.scene.os_geo_items.add()
                new_item.nombre = nom
                
        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, context):
        layout = self.layout
        
        # Panel 1: Out-of-Bounds
        if len(context.scene.os_infractores) > 0:
            box = layout.box()
            box.label(text="Dependencias Externas (Out-of-Bounds)", icon='URL')
            for item in context.scene.os_infractores:
                row = box.row()
                row.label(text=item.nombre, icon='FILE_IMAGE')
                row.prop(item, "categoria", text="")
                
            layout.separator()
            
        # Panel 2: Geometría
        if len(context.scene.os_geo_items) > 0:
            box = layout.box()
            box.label(text="Sanidad Matemática (Escalas/Rotaciones/Posición)", icon='MESH_DATA')
            for item in context.scene.os_geo_items:
                row = box.row()
                row.label(text=item.nombre, icon='OBJECT_DATA')
                row.prop(item, "accion", text="")
                
            layout.separator()
            
        # Panel 3: Nomenclatura
        nom_str = context.scene.os_nom_infractores
        if nom_str:
            box = layout.box()
            box.label(text="Nomenclatura (Se aplicará convención automáticamente)", icon='SORTALPHA')
            nombres_nom = nom_str.split(",")
            for nom in nombres_nom:
                box.label(text=f"• {nom}", icon='BLANK1')

    def execute(self, context):
        """Ejecuta las reparaciones delegando al Gatekeeper."""
        
        # 1. Reparar Dependencias
        clasificaciones = {item.nombre: item.categoria for item in context.scene.os_infractores}
        if clasificaciones:
            infractores_crudos = gatekeeper.escanear_out_of_bounds()
            gatekeeper.auto_fix_dependencias(infractores_crudos, clasificaciones)
            
        # 2. Reparar Geometría (Filtrado por acción elegida)
        apply_list = [item.nombre for item in context.scene.os_geo_items if item.accion == 'apply']
        clear_list = [item.nombre for item in context.scene.os_geo_items if item.accion == 'clear']
        
        gatekeeper.aplicar_transformaciones(apply_list)
        gatekeeper.limpiar_transformaciones(clear_list)
        
        # 3. Reparar Nomenclatura
        nom_str = context.scene.os_nom_infractores
        if nom_str:
            gatekeeper.auto_fix_nombres(nom_str.split(","))

        # Limpieza de memoria
        context.scene.os_infractores.clear()
        context.scene.os_geo_items.clear()
        context.scene.os_geo_infractores = ""
        context.scene.os_nom_infractores = ""
        
        self.report({'INFO'}, "Master QA: repairs applied. Re-run the audit or continue when ready.")
        return {'FINISHED'}

# ---------------------------------------------------------
# REGISTRO
# ---------------------------------------------------------

def register():
    bpy.utils.register_class(OpenStudioInfractorItem)
    bpy.utils.register_class(OpenStudioGeoItem)
    
    bpy.types.Scene.os_infractores = bpy.props.CollectionProperty(type=OpenStudioInfractorItem)
    bpy.types.Scene.os_geo_items = bpy.props.CollectionProperty(type=OpenStudioGeoItem)
    
    bpy.utils.register_class(OPENSTUDIO_OT_master_qa_ui)

def unregister():
    bpy.utils.unregister_class(OPENSTUDIO_OT_master_qa_ui)
    
    del bpy.types.Scene.os_geo_items
    del bpy.types.Scene.os_infractores
    
    bpy.utils.unregister_class(OpenStudioGeoItem)
    bpy.utils.unregister_class(OpenStudioInfractorItem)
