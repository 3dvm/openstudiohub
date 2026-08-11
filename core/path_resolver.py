# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/path_resolver.py
# Rol Arquitectónico: Motor Lógico / Kitsu Path Resolver
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.1
# =========================================================================================

"""
Translate Kitsu tasks into phisical file paths. Cleans file names and keeps the
naming conventions from the configuration. Mapping 'entity_type_name'.
"""

from typing import Dict, Optional

class PathResolver:
    """
    Motor de resolución de rutas (Path Resolver).
    Calcula el path relativo necesario para orquestar el Sparse Checkout del VCS
    y la invocación de los archivos de trabajo en Blender.
    """
    
    @staticmethod
    def get_sparse_path(task_data: Dict[str, str]) -> Optional[str]:
        """
        Calcula la ruta relativa del directorio para el SparseManager.
        Retorna ej: 'pro/shots/sq01/sh010'
        """
        if not task_data:
            return None
            
        # Kitsu mapping: Extraer tipo desde entity_type_name o fallback a entity_type
        entity_type = task_data.get("entity_type_name", task_data.get("entity_type", "")).lower()
        entity_name = task_data.get("entity_name", "")
        
        if entity_type == "shot":
            seq_name = task_data.get("sequence_name", "")
            if not seq_name or not entity_name:
                raise ValueError("Metadatos incompletos para Shot: Falta sequence_name.")
            
            return f"pro/shots/{seq_name}/{entity_name}"
            
        elif entity_type == "asset":
            # Normalización Jailing para Assets: Si no hay categoría asignada cae en props
            asset_type = task_data.get("asset_type_name", "props").lower()
            if not entity_name:
                raise ValueError("Metadatos incompletos para Asset: Falta entity_name.")
            
            return f"pro/assets/{asset_type}/{entity_name}"
            
        else:
            raise ValueError(f"Tipo de entidad Kitsu desconocido: {entity_type}")

    def resolve(self, task_data: Dict[str, str]) -> Optional[str]:
        """
        Calcula la ruta relativa exacta al archivo .blend de la tarea actual.
        Basado en el Diagrama 1.6 (Entity to path graph) del SDD.
        
        Retorna ej: 'shots/sq01/sh010/sh010-anim.blend'
        """
        if not task_data:
            return None
            
        # Corrección de Mapeo API: Captura 'entity_type_name' mapeado por Kitsu
        entity_type = task_data.get("entity_type_name", task_data.get("entity_type", "")).lower()
        entity_name = task_data.get("entity_name", "")
        
        # Priorizar short_name para archivos (ej. 'anim' o 'modelado')
        task_name = task_data.get("task_type_short_name", task_data.get("task_type_name", "generic")).lower()
        
        # Normalizar strings con acentos comunes en entornos en español (animación -> anim)
        if "anim" in task_name:
            task_name = "anim"
        elif "model" in task_name:
            task_name = "model"

        # NUEVO: Soporte explícito para Storyboard (Entidad Secuencia)
        if entity_type == "sequence" or task_name == "storyboard":
            # Para las secuencias, 'entity_name' es el nombre de la secuencia (ej: '01' o 'sq010')
            seq_name = task_data.get("entity_name", task_data.get("sequence_name", "")).lower()
            if not seq_name: return None
            
            # Leemos la ruta que el HeadlessBuilder forjó (Regla estricta de Topología)
            return f"edit/storyboards/{seq_name}-storyboard.blend"
        
        # NUEVO: Soporte explícito para Tareas de Edición
        if task_name == "edit" or entity_type == "edit":
            project_name = task_data.get("project_name", "project").strip().lower().replace(" ", "-")
            return f"edit/{project_name}-edit.blend"

        if entity_type == "shot":
            seq_name = task_data.get("sequence_name", "")
            if not seq_name or not entity_name: return None
            return f"pro/shots/{seq_name}/{entity_name}/{entity_name}-{task_name}.blend"
            
        elif entity_type == "asset":
            asset_type = task_data.get("asset_type_name", "props").lower()
            if not entity_name: return None
            return f"pro/assets/{asset_type}/{entity_name}/{asset_type}-{entity_name}-{task_name}.blend"
            
        return None
