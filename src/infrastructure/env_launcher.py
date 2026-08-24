# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/env_launcher.py
# Rol Arquitectónico: Subprocess Orchestrator / Sandboxing
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.1.0 (Dynamic VFS & PathResolver Integration)
# =========================================================================================

"""
Orquestador de subprocesos para el ecosistema OpenStudio.
Se encarga de ubicar el binario de Blender de forma dinámica mediante el ConfigFactory, 
construir el entorno aislado (Sandboxing VFS), e inyectar las variables de entorno 
para el Context-Aware Tooling y la navegación RNA.
"""

import os
import json
import subprocess
import shutil
import platform
from pathlib import Path
from typing import Optional

from src.domain.path_resolver import PathResolver

def _get_os_info() -> str:
    system = platform.system().lower()
    if system == "linux": return "linux"
    elif system == "windows": return "windows"
    else: return "macos"

def lanzar_blender(project_root: Path, config_path: Path, svn_user: str, svn_pwd: str, 
                   kitsu_user: str, kitsu_pwd: str, kitsu_host: str, user_role: str, 
                   task_data: dict, target_file: Optional[Path], status_callback,
                   production_folder: str = "", config_factory = None):
    try:
        if not config_factory:
            raise RuntimeError("ConfigFactory no fue inyectado en el EnvLauncher.")

        # Extracción de Topología Dinámica B2B
        vfs_local = config_factory.get_vfs_local_name()
        vfs_svn = config_factory.get_vfs_svn_name()
        vault_path = config_factory.get_vault_path()

        if not production_folder:
            production_folder = vfs_svn

        with open(config_path, 'r', encoding='utf-8') as f:
            adn = json.load(f)

        template_name = adn.get("template", "Macuare_Estudio")
        version = adn.get("version_locking", {}).get("blender_version", adn.get("blender_version", "5.1.2"))

        #status_callback(f"Buscando Blender {version}...", "yellow")

        status_callback(f"Buscando Blender {version} en Sandbox Local...", "yellow")

        # 1. Búsqueda Estricta de Binario (Exclusivo en Sandbox VFS)
        os_name = _get_os_info()
        archive_folder = f"blender-{version}-{os_name}-x64"
        
        base_blender_dir = project_root / vfs_local / "blender-build" / archive_folder
        
        if os_name == "windows":
            blender_bin = base_blender_dir / "blender.exe"
        elif os_name == "macos":
            # En macOS, el ejecutable real vive dentro del paquete .app
            blender_bin = base_blender_dir / "Blender.app" / "Contents" / "MacOS" / "Blender"
            if not blender_bin.exists():
                blender_bin = base_blender_dir / "Blender" # Fallback de seguridad
        else:
            blender_bin = base_blender_dir / "blender"

        if not blender_bin.exists():
            raise FileNotFoundError(f"Fallo de Sandboxing: No se encontró el ejecutable en {blender_bin}")

        status_callback(f"Ejecutable aislado encontrado en: {archive_folder}", "green")
        status_callback("Preparando Sandboxing y Variables de Entorno...", "yellow")

        # 2. Configurar Sandbox Dirs (Aislamiento absoluto VFS)
        sandbox_dir = project_root / vfs_local / "blender_data"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        
        extensions_dir = sandbox_dir / "extensions" / "user_default"
        extensions_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["OPENSTUDIO_PROJECT_CONFIG"] = str(config_path)

        task_type = task_data.get("task_type_name", "generic")
        project_name = task_data.get("project_name", project_root.name)

        # Inyección VFS & Sandboxing Env Vars
        env["BLENDER_USER_RESOURCES"] = str(sandbox_dir)
        env["BLENDER_USER_CONFIG"] = str(sandbox_dir / "config")
        env["BLENDER_USER_SCRIPTS"] = str(sandbox_dir / "scripts")
        env["OPENSTUDIO_EXTENSIONS_DIR"] = str(extensions_dir) 

        env["OPENSTUDIO_PROJECT_ROOT"] = str(project_root)
        env["OPENSTUDIO_PRODUCTION_FOLDER"] = production_folder
        env["OPENSTUDIO_USER_ROLE"] = user_role
        env["OPENSTUDIO_TASK_TYPE"] = task_type
        
        # Inyección de Credenciales 
        env["OPENSTUDIO_KITSU_USER"] = kitsu_user
        env["OPENSTUDIO_KITSU_PWD"] = kitsu_pwd
        env["OPENSTUDIO_KITSU_HOST"] = kitsu_host

        # NUEVO: Calcular ruta del Splash Screen usando el ConfigFactory
        vfs_pipe = config_factory.get_vfs_pipeline_name()
        splash_path = project_root / vfs_pipe / "splash.png"
        env["OPENSTUDIO_SPLASH_PATH"] = str(splash_path) if splash_path.exists() else ""


        # ---------------------------------------------------------
        # PATH RESOLVER: INYECCIÓN DINÁMICA DE CONTEXTO
        # ---------------------------------------------------------
        if not target_file:
            resolver = PathResolver()
            resolved_rel_path = resolver.resolve(task_data)
            if resolved_rel_path:
                import glob
                # Quitamos el ".blend" para buscar variaciones con -v001, -v002, etc.
                base_target_str = str(project_root / production_folder / resolved_rel_path).replace(".blend", "")
                
                versioned_files = glob.glob(f"{base_target_str}-v*.blend")
                if versioned_files:
                    # Ordenamos y tomamos el archivo con la versión más reciente
                    target_file = Path(sorted(versioned_files)[-1])
                else:
                    # Fallback estándar
                    target_file = Path(f"{base_target_str}.blend")

        env["OPENSTUDIO_TARGET_FILE"] = str(target_file) if target_file else ""
        
        env["OPENSTUDIO_KITSU_PROJECT_ID"] = task_data.get("project_id", "")
        env["OPENSTUDIO_PROJECT_NAME"] = project_name
        env["OPENSTUDIO_KITSU_ENTITY_TYPE"] = task_data.get("entity_type", "SHOT").upper()
        env["OPENSTUDIO_KITSU_TASK_TYPE_ID"] = task_data.get("task_type_id", "")
        env["OPENSTUDIO_KITSU_TASK_TYPE_NAME"] = task_type
        env["OPENSTUDIO_KITSU_ENTITY_ID"] = task_data.get("entity_id", "")
        env["OPENSTUDIO_KITSU_ENTITY_NAME"] = task_data.get("entity_name", "")
        env["OPENSTUDIO_KITSU_SEQUENCE_ID"] = task_data.get("sequence_id", "")
        env["OPENSTUDIO_KITSU_SEQUENCE_NAME"] = task_data.get("sequence_name", "")
        # env["OPENSTUDIO_KITSU_ASSET_TYPE_ID"] = task_data.get("asset_type_id", "")
        # env["OPENSTUDIO_KITSU_ASSET_TYPE_NAME"] = task_data.get("asset_type_name", "")

        # Kitsu usa 'entity_type_id' para referirse al tipo de Asset dentro de un diccionario de Asset crudo
        env["OPENSTUDIO_KITSU_ASSET_TYPE_ID"] = task_data.get("asset_type_id", task_data.get("entity_type_id", ""))
        env["OPENSTUDIO_KITSU_ASSET_TYPE_NAME"] = task_data.get("asset_type_name", "")

        env["OPENSTUDIO_SVN_USER"] = svn_user
        env["OPENSTUDIO_SVN_PASSWORD"] = svn_pwd

        # 3. Preparar el script bootstrap
        bootstrap_src = Path(__file__).parent / "templates" / "bootstrap.py"
        bootstrap_dst = project_root / vfs_local / "bootstrap.py"

        bootstrap_dst.parent.mkdir(parents=True, exist_ok=True)
        if bootstrap_src.exists():
            shutil.copy2(bootstrap_src, bootstrap_dst)
        else:
            raise FileNotFoundError("No se encontro src/infrastructure/templates/bootstrap.py")

        status_callback(f"Arrancando {project_name} (Contexto: {task_type.upper()})...", "green")

        # =========================================================
        # SANEAMIENTO DE ENTORNO: Evitar TypeError por Kitsu 'null'
        # =========================================================
        clean_env = {}
        for k, v in env.items():
            clean_env[k] = str(v) if v is not None else ""
        # =========================================================

        # 4. Lanzar el subproceso con Sandboxing Inyectado
        cmd = [str(blender_bin), "--app-template", template_name, "--python", str(bootstrap_dst)]
        # --- DEBUG VOLCADO DE ENTORNO ---
        print("\n" + "="*40)
        print("🔍 AUDITORÍA DE ENV_LAUNCHER ANTES DEL POPEN")
        print("="*40)
        for key in ["OPENSTUDIO_KITSU_ASSET_TYPE_ID", "OPENSTUDIO_KITSU_ASSET_TYPE_NAME", "OPENSTUDIO_KITSU_ENTITY_NAME"]:
            print(f"[{key}]: '{clean_env.get(key, 'NO EXISTE')}'")
        print("="*40 + "\n")
        # --------------------------------
        proceso = subprocess.Popen(cmd, env=clean_env)

        status_callback(f"Blender en ejecucion ({project_name})...", "#00aaff")
        proceso.wait()
        status_callback(f"Sesion de {project_name} terminada.", "green")
        
    except Exception as e:
        status_callback(f"Error Crítico Launcher: {str(e)}", "red")
        import traceback
        print(f"Error detallado Launcher:\n{traceback.format_exc()}")
