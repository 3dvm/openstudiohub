# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/addon_inspector.py
# Rol Arquitectónico: Core Utility / Semantic Metadata Parser
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0
# =========================================================================================

import re
import zipfile
from pathlib import Path

class AddonInspector:
    """Utilidad estática para leer y extraer propiedades de Addons desde archivos ZIP o directorios crudos."""
    
    @staticmethod
    def parse_manifest_content(content: str, is_toml: bool) -> dict:
        """Aplica expresiones regulares sobre el texto crudo para aislar las propiedades semánticas."""
        resultado = {
            "name": "unknown_addon",
            "version": "1.0.0",
            "description": "Custom loaded addon",
            "blender_min": (0, 0, 0)
        }

        if is_toml:
            id_m = re.search(r'id\s*=\s*"([^"]+)"', content)
            ver_m = re.search(r'version\s*=\s*"([^"]+)"', content)
            desc_m = re.search(r'description\s*=\s*"([^"]+)"', content)
            min_v_m = re.search(r'blender_version_min\s*=\s*"([^"]+)"', content)

            if id_m: resultado["name"] = id_m.group(1)
            if ver_m: resultado["version"] = ver_m.group(1)
            if desc_m: resultado["description"] = desc_m.group(1)
            if min_v_m:
                resultado["blender_min"] = tuple(int(x) for x in min_v_m.group(1).split('.') if x.isdigit())
        else:
            # Parseo Legacy (bl_info)
            v_match = re.search(r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*(\d+))?\s*\)', content)
            b_match = re.search(r'"blender"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*(\d+))?\s*\)', content)
            desc_m = re.search(r'"description"\s*:\s*"([^"]+)"', content)

            # Para legacy, sacamos el nombre de un campo alternativo o se debe inferir por carpeta fuera de este método
            name_m = re.search(r'"name"\s*:\s*"([^"]+)"', content)
            if name_m: resultado["name"] = name_m.group(1).lower().replace(" ", "_")

            if v_match: resultado["version"] = f"{v_match.group(1)}.{v_match.group(2)}.{v_match.group(3) or '0'}"
            if desc_m: resultado["description"] = desc_m.group(1)
            if b_match:
                resultado["blender_min"] = (int(b_match.group(1)), int(b_match.group(2)), int(b_match.group(3) or 0))

        return resultado

    @staticmethod
    def inspect_zip(zip_path: Path) -> dict:
        """Abre un archivo ZIP en memoria y busca su manifiesto."""
        if not zipfile.is_zipfile(zip_path):
            return {}

        with zipfile.ZipFile(zip_path, 'r') as z:
            # 1. Buscar extensiones modernas
            for item in z.namelist():
                if item.endswith("blender_manifest.toml"):
                    content = z.read(item).decode('utf-8', errors='ignore')
                    return AddonInspector.parse_manifest_content(content, is_toml=True)
            
            # 2. Buscar legacy
            for item in z.namelist():
                if item.endswith("__init__.py"):
                    content = z.read(item).decode('utf-8', errors='ignore')
                    if "bl_info" in content:
                        parsed = AddonInspector.parse_manifest_content(content, is_toml=False)
                        # Inferir nombre base de la carpeta si el regex no lo capturó bien
                        if parsed["name"] == "unknown_addon":
                            parsed["name"] = Path(item).parent.name
                        return parsed
        return {}

    @staticmethod
    def inspect_directory(dir_path: Path) -> dict:
        """Analiza un directorio extraído en disco (Útil para el FetchWorker)."""
        toml_path = dir_path / "blender_manifest.toml"
        if toml_path.exists():
            return AddonInspector.parse_manifest_content(toml_path.read_text(encoding='utf-8', errors='ignore'), is_toml=True)
            
        init_path = dir_path / "__init__.py"
        if init_path.exists():
            content = init_path.read_text(encoding='utf-8', errors='ignore')
            if "bl_info" in content:
                parsed = AddonInspector.parse_manifest_content(content, is_toml=False)
                if parsed["name"] == "unknown_addon":
                    parsed["name"] = dir_path.name
                return parsed
        return {}

    @staticmethod
    def is_compatible(min_version_tuple: tuple, target_v_str: str) -> bool:
        """Contrasta la versión mínima exigida contra la versión objetivo de Blender."""
        try:
            t_parts = [int(x) for x in target_v_str.split('.') if x.isdigit()]
            while len(t_parts) < 3: t_parts.append(0)
            r_parts = list(min_version_tuple)
            while len(r_parts) < 3: r_parts.append(0)

            for t, r in zip(t_parts, r_parts):
                if t > r: return True
                if t < r: return False
            return True 
        except:
            return True
