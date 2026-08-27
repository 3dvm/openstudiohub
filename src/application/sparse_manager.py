# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/sparse_manager.py
# Rol Arquitectónico: Backend Orchestrator / Jailing Manager
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.4.0
# =========================================================================================

"""
Orquestador del Sparse Checkout (Jailing).
Recibe metadatos de Tareas, resuelve rutas y delega la descarga restrictiva 
a la capa de abstracción VCS de forma iterativa y recursiva leyendo los 
manifiestos de dependencias locales (*-meta.json).
"""

import json
from pathlib import Path
from typing import Dict, Callable, List, Set
from src.domain.path_resolver import PathResolver
from src.domain.workspace.jailing import JailingPolicy
from src.infrastructure.vcs.vcs_router import VCSRouter

class SparseManager:
    """
    Gestiona el aislamiento de directorios (Jailing) para usuarios con rol 'vendor'.
    """
    
    def __init__(self, vcs_router: VCSRouter, status_callback: Callable[[str, str], None]):
        self.router = vcs_router
        self.status_callback = status_callback

    def setup_vendor_workspace(self, task_metadata: Dict[str, str], username: str, password: str) -> bool:
        """
        Orquesta el descubrimiento de ruta inicial y detona el pull recursivo.
        """
        self.status_callback("Calculando ruta estricta de Jailing...", "yellow")
        
        print("\n[SPARSE DEBUG] Iniciando Jailing...")
        print(f"[SPARSE DEBUG] Metadata recibida de Kitsu: {task_metadata}")

        try:
            # 1. Resolución de Ruta Principal (Traducción Kitsu -> LocalFS)
            sparse_path = PathResolver.get_sparse_path(task_metadata)
            
            print(f"[SPARSE DEBUG] Ruta resuelta por el PathResolver: {sparse_path}")
            
            if not sparse_path:
                print("[SPARSE ERROR] La ruta resuelta está vacía o es inválida.")
                self.status_callback("Error: Metadatos de tarea inválidos o vacíos.", "red")
                return False
            
            self.status_callback(f"Jailing activo. Descargando dependencias...", "yellow")
            
            # 2. Delegación Recursiva al Adaptador VCS
            adapter = self.router.get_adapter()
            visited_paths = set()
            
            # Disparamos la recursividad con la carpeta inicial de la tarea
            self._pull_recursive(
                paths=[sparse_path], 
                adapter=adapter, 
                username=username, 
                password=password, 
                visited=visited_paths
            )
            
            print("[SPARSE DEBUG] Jailing completado con éxito.")
            self.status_callback("Jailing completado: Workspace restrictivo preparado.", "green")
            return True
            
        except ValueError as ve:
            print(f"[SPARSE ERROR FATAL] ValueError atrapado (Lógica Kitsu): {ve}")
            self.status_callback(f"Error de Resolución Kitsu: {str(ve)}", "red")
            return False
        except RuntimeError as re:
            print(f"[SPARSE ERROR FATAL] RuntimeError (VCS/Red): {re}")
            self.status_callback("Fallo de conexión en Sparse Checkout. Revisa credenciales.", "red")
            return False
        except Exception as e:
            print(f"[SPARSE ERROR FATAL] Excepción crítica general: {e}")
            self.status_callback(f"Error crítico durante el Jailing: {str(e)}", "red")
            return False

    def _pull_recursive(self, paths: List[str], adapter, username: str, password: str, visited: Set[str]):
        """
        Descarga las rutas dadas, busca manifiestos (*-meta.json) en ellas y 
        dispara una nueva descarga para las dependencias descubiertas.
        """
        unvisited = [p for p in paths if p not in visited]
        if not unvisited:
            return

        print(f"[SPARSE DEBUG] Descargando lote: {unvisited}")
        # Descarga física de los archivos o directorios
        adapter.sparse_pull(paths=unvisited, username=username, password=password)
        visited.update(unvisited)

        next_batch = set()

        for path in unvisited:
            local_path = Path(adapter.workspace_dir) / path
            
            # Buscar manifiestos de dependencias
            meta_files = []
            if local_path.is_dir():
                meta_files = list(local_path.glob("*-meta.json"))
            elif local_path.is_file() and local_path.name.endswith("-meta.json"):
                meta_files = [local_path]
            
            # Analizar cada manifiesto encontrado
            for meta_file in meta_files:
                print(f"[SPARSE DEBUG] Analizando manifiesto: {meta_file.name}")
                try:
                    with open(meta_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    deps = data.get("dependencies", [])
                    rel_dir = meta_file.parent.relative_to(adapter.workspace_dir)
                    for dep in deps:
                        combined = JailingPolicy.resolve_dependency(str(rel_dir), dep)
                        if combined is None:
                            continue
                        for target in JailingPolicy.expand_with_meta(combined):
                            if target not in visited:
                                next_batch.add(target)
                                        
                except Exception as e:
                    print(f"[SPARSE ERROR] Fallo al leer manifiesto {meta_file.name}: {e}")
        
        # Si descubrimos nuevas rutas, las enviamos a descargar en el siguiente ciclo
        if next_batch:
            self._pull_recursive(list(next_batch), adapter, username, password, visited)
