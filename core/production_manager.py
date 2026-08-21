# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/production_manager.py
# Rol Arquitectónico: Production Orchestrator / Batch Entity Genesis
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0
# =========================================================================================

"""
Logical orchestrator for the Production Manager (PM).
Connects to Gazu (Kitsu API) to fetch entities proposed by Editorial, batch-spawns 
production tasks, and executes the physical generation of master .blend files inside 
the VCS repository via Semantic Topography. Anchored to English standard.
"""

import shutil
from pathlib import Path
from typing import List, Dict, Any, Tuple
from core.kitsu_manager import KitsuManager

class ProductionManager:
    def __init__(self, auth_manager, config_factory):
        self.auth_manager = auth_manager
        self.config_factory = config_factory
        # Todas las llamadas a Gazu se delegan al KitsuManager (SSoT).
        self.kitsu = KitsuManager()
        
        try:
            self.vault_root = self.config_factory.get_workspace_root() / "openstudio_vault"
        except Exception:
            self.vault_root = Path.home() / "openstudio_vault"
            
        self.vault_templates_dir = self.vault_root / "project_templates"

    def get_pending_entities(self, project_id: str) -> List[Dict[str, Any]]:
        """
        Queries the Kitsu API for Shots and Assets that require PM validation.
        Typically, these are pushed by the Editorial department (Blender VSE) 
        and sit in 'Pending Validation' or 'Waiting for Approval' statuses.
        """
        pending_list = []
        try:
            # Ampliamos el espectro para atrapar las tomas recién creadas por el Editor
            valid_statuses = ["Todo", "Ready To Start"]
            
            shots = self.kitsu.all_shots_for_project(project_id)
            for shot in shots:
                status = shot.get("status", "Todo") # Fallback a Todo si es nueva
                if status in valid_statuses:
                    seq = self.kitsu.get_sequence(shot.get("sequence_id"))
                    pending_list.append({
                        "id": shot["id"],
                        "name": shot["name"],
                        "type": "Shot",
                        "parent": seq["name"] if seq else "Unknown",
                        "frame_in": shot.get("nb_frames", 0),
                        "status": status,
                        "raw_data": shot
                    })
                    
            assets = self.kitsu.all_assets_for_project(project_id)
            for asset in assets:
                status = asset.get("status", "Todo")
                if status == "Todo":
                    
                    asset_type_id = asset.get("entity_type_id", "")

                    asset_type = self.kitsu.get_asset_type(asset.get("entity_type_id"))
                    
                    pending_list.append({
                        "id": asset["id"],
                        "name": asset["name"],
                        "Parent": asset.get("parent"),
                        "type": asset_type["name"] if asset_type else "Unknown",
                        "asset_type_id": asset_type_id,
                        "frame_in": 0,
                        "status": status,
                        "raw_data": asset
                    })
                    
        except Exception as e:
            print(f"[PRODUCTION MANAGER] Gazu API Error fetching entities: {e}")
            
        return pending_list

    def map_file_to_task(self, entity_dict: dict, task_type_name: str, relative_path: str) -> bool:
        """
        Utility for the Spawning Workers: Inyecta la ruta física del .blend generado 
        en la Metadata de la entidad (Custom Data) para que el PathResolver la encuentre.
        """
        try:
            entity_data = entity_dict.get("data")
            if not entity_data:
                entity_data = {}
                
            entity_data["blend_file_path"] = relative_path
            self.kitsu.update_entity_data(entity_dict["id"], entity_data)
            return True
        except Exception as e:
            print(f"[PRODUCTION MANAGER] Error maping file to Kitsu: {e}")
            return False

    def batch_create_entity_files(self, project_name: str, entities: List[Dict[str, Any]], 
                                  base_template: str, task_types: List[str], status_callback) -> Tuple[bool, str]:
        """
        The genesis engine. Iterates over approved entities to:
        1. Spawn production tasks in Kitsu.
        2. Generate the physical nested directories in the VCS Workspace.
        3. Copy the base template .blend file to prevent Sparse Checkout deadlocks.
        """
        if not entities:
            return False, "No entities provided for batch creation."

        # 1. Resolve Project Root & Topography
        try:
            project_root = self.config_factory.get_workspace_root() / project_name
            vfs_svn = self.config_factory.get_vfs_svn_name()
            vcs_root = project_root / vfs_svn
        except Exception as e:
            return False, f"Failed to resolve NAS topography: {e}"

        template_path = self.vault_templates_dir / base_template
        if not template_path.exists() or not template_path.is_file():
            return False, f"Master template '{base_template}' not found in Vault."

        success_count = 0
        error_count = 0

        for idx, entity in enumerate(entities):
            e_name = entity.get("name", "unknown").lower().replace(" ", "_")
            e_type = entity.get("type", "Shot")
            e_parent = entity.get("parent", "unknown").lower().replace(" ", "_")
            e_id = entity.get("id")
            
            status_callback(f"Processing {e_type}: {e_name} ({idx + 1}/{len(entities)})...", "yellow")
            
            # 2. Path Generation (Blender Studio Standard via Semantic Topography)
            if e_type == "Shot":
                entity_dir = vcs_root / "pro" / "shots" / e_parent / e_name
            else:
                entity_dir = vcs_root / "pro" / "assets" / e_parent / e_name

            try:
                # 3. Directory Scaffolding
                entity_dir.mkdir(parents=True, exist_ok=True)
                
                # 4. Kitsu Task Spawning & File Injection
                for task_name in task_types:
                    # Spawn in API (Silent fail if already exists)
                    try:
                        gazu_task_type = self.kitsu.get_task_type_by_name(task_name)
                        if gazu_task_type:
                            self.kitsu.create_task(e_id, gazu_task_type)
                    except Exception as api_e:
                        print(f"[PRODUCTION MANAGER] Task {task_name} already exists or API error: {api_e}")

                    # Spawn Physical .blend file
                    safe_task_name = task_name.lower().replace(" ", "")
                    blend_filename = f"{e_name}-{safe_task_name}.blend"
                    dest_blend_path = entity_dir / blend_filename
                    
                    if not dest_blend_path.exists():
                        shutil.copy2(template_path, dest_blend_path)
                
                # Update Kitsu Status to active (Ready to Start / WIP)
                # In a real scenario, you map a specific status UUID.
                # gazu.entity.update_entity_status(e_id, "Ready to Start")
                
                success_count += 1
                
            except Exception as io_error:
                print(f"[PRODUCTION MANAGER] File System error on {e_name}: {io_error}")
                error_count += 1

        status_callback(f"Batch completed: {success_count} created, {error_count} failed.", "green" if error_count == 0 else "yellow")
        return True, f"Successfully processed {success_count} entities."

    def get_or_create_storyboard_task_type(self, project_id: str) -> dict:
        """
        Busca el Task Type 'Storyboard' para 'Sequence'. 
        Gracias a la plantilla del TD, este ya existe en el proyecto.
        """
        # 1. Buscar a nivel global
        task_types = self.kitsu.all_task_types()
        storyboard_tt = next((tt for tt in task_types if tt["name"].lower() == "storyboard" and tt["for_entity"].lower() == "sequence"), None)
        
        # 2. Fallback de seguridad (solo lo crea en memoria global si alguien lo borró)
        if not storyboard_tt:
            storyboard_tt = self.kitsu.new_task_type(
                name="StoryboardSeq", 
                color="#F97316",
                for_entity="Sequence"
            )
            
        # ¡ELIMINADO el gazu.project.add_task_type que causaba el error de permisos!
        return storyboard_tt

    def create_sequence_with_task(self, project_id: str, sequence_name: str, task_type_id: str) -> dict:
        """Crea la entidad Sequence y le adjunta la tarea de Storyboard."""
        # Kitsu requiere el nombre del proyecto como objeto o dict para crear la secuencia
        project = self.kitsu.get_project(project_id)
        
        # Crear la secuencia en Kitsu
        sequence = self.kitsu.new_sequence(project, name=sequence_name)
        
        # Crear la tarea inicial de Storyboard
        # El estado inicial suele ser 'todo' o el por defecto del estudio
        default_status = self.kitsu.get_default_task_status()
        self.kitsu.new_task(
            entity=sequence, 
            task_type=task_type_id, 
            name="main", 
            task_status=default_status
        )
        return sequence
