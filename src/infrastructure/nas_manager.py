# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/nas_manager.py
# Rol Arquitectónico: File System Manager / NAS Orchestrator
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0 (Genesis)
# =========================================================================================

"""
Gestor centralizado para las operaciones de lectura y escritura en el servidor NAS (Local/Red).
Aísla a la UI de las comprobaciones de disco, búsquedas de directorios,
lectura de manifiestos (Blueprints) y operaciones destructivas.
"""

import json
import shutil
from pathlib import Path
from typing import Optional, Dict

class NasManager:
    def __init__(self, base_dir: Path):
        """
        Inicializa el gestor con la ruta raíz del almacenamiento local o de red (NAS).
        """
        self.base_dir = Path(base_dir) if base_dir else None

    def is_connected(self) -> bool:
        """Verifica si la ruta raíz está configurada y accesible."""
        return self.base_dir is not None and self.base_dir.exists()

    def resolve_project_dir(self, project_name: str, project_code: str = "") -> Optional[Path]:
        """
        Intenta resolver la ruta física del proyecto usando su nombre o su código.
        """
        if not self.is_connected():
            return None

        # 1. Buscar coincidencia exacta (Nombre crudo)
        target_dir = self.base_dir / project_name
        if target_dir.exists():
            return target_dir

        # 2. Buscar versión normalizada (Guiones en vez de espacios, minúsculas)
        clean_name = project_name.strip().lower().replace(" ", "-") if project_name else "unknown"
        target_dir_clean = self.base_dir / clean_name
        if target_dir_clean.exists():
            return target_dir_clean

        # 3. Fallback al código corto de Kitsu
        if project_code:
            target_dir_code = self.base_dir / project_code
            if target_dir_code.exists():
                return target_dir_code

        return None

    def get_project_blueprint(self, project_dir: Path) -> Dict:
        """
        Busca dinámicamente el archivo project_init.json dentro de la carpeta
        del proyecto (independientemente del nombre del VFS interno) y retorna sus metadatos.
        """
        if not project_dir or not project_dir.exists():
            return {}

        try:
            # Busca un nivel adentro usando glob
            meta_files = list(project_dir.glob("*/project_init.json"))
            if meta_files:
                with open(meta_files[0], "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"[NasManager] Error leyendo blueprint en {project_dir}: {e}")
            
        return {}

    def delete_project_folder(self, project_dir: Path) -> bool:
        """
        Destruye recursivamente el directorio del proyecto en el disco local/NAS.
        """
        if not project_dir or not project_dir.exists():
            return False

        try:
            shutil.rmtree(project_dir, ignore_errors=True)
            print(f"[NasManager] Directorio local destruido exitosamente: {project_dir}")
            return True
        except Exception as e:
            print(f"[NasManager] Error al destruir directorio {project_dir}: {e}")
            return False
