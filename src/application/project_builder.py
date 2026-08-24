# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/project_builder.py
# Rol Arquitectónico: I/O Orchestrator / Project Generator (B2B Multi-OS)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.6.1 (Restauración de Headless Builder)
# =========================================================================================

# import os
import json
import shutil
# import zipfile
# import tarfile
# import subprocess
# import tempfile
import platform
from pathlib import Path

from src.infrastructure.vcs.vcs_router import VCSRouter
from src.infrastructure.kitsu_manager import KitsuManager
from src.infrastructure.dev_defaults import DEV_SVN_USER, DEV_SVN_PASSWORD

class ProjectBuilder:
    def __init__(self, config_factory):
        self.config_factory = config_factory

    @property
    def base_dir(self) -> Path:
        return self.config_factory.get_workspace_root()

    @property
    def vault_root(self) -> Path:
        return self.config_factory.get_vault_path()

    @property
    def vault_templates_dir(self) -> Path:
        return self.vault_root / "project_templates"

    @property
    def vault_blender_dir(self) -> Path:
        return self.vault_root / "blender_versions"

    def _get_os_info(self) -> str:
        system = platform.system().lower()
        if system == "linux": return "linux"
        elif system == "windows": return "windows"
        else: return "macos"

    def create_project(self, project_name: str, blender_version: str, dependencies: dict, project_template: str, splash_image_path: str = "", vcs_user: str = "", vcs_pwd: str = "") -> tuple[bool, str]:
        if not project_name.strip(): return False, "Project name cannot be empty."
        if not blender_version.strip(): return False, "You must specify a Blender version."

        folder_name = project_name.strip().lower().replace(" ", "-")
        project_path = self.base_dir / folder_name

        if project_path.exists():
            return False, f"Folder '{folder_name}' already exists on the NAS."

        kitsu = KitsuManager()
        
        # INYECCIÓN DE LA PLANTILLA DE KITSU POR DEFECTO
        success, kitsu_msg, kitsu_project = kitsu.create_project_from_template(
            project_name.strip(), 
            template_name="standard-3d-production"
        )
        
        if not success:
            return False, f"Abortado por Kitsu: {kitsu_msg}"
            
        project_id = kitsu_project.get("id", "")
        print(f"[ProjectBuilder] Entidad Kitsu forjada con plantilla. ID: {project_id}")

        try:
            vfs_svn = self.config_factory.get_vfs_svn_name()
            vfs_shared = self.config_factory.get_vfs_shared_name()
            vfs_local = self.config_factory.get_vfs_local_name()
            vfs_pipe = self.config_factory.get_vfs_pipeline_name()
            custom_dirs = self.config_factory.get_custom_dirs()

            # Solo carpetas estructurales, el PM generará el resto a demanda
            base_folders = [
                vfs_local, vfs_shared, vfs_pipe,
                f"{vfs_svn}/pro", f"{vfs_svn}/tools",
                f"{vfs_svn}/pro/assets",
                f"{vfs_svn}/pro/shots",
                f"{vfs_svn}/pro/edit",
                f"{vfs_svn}/pro/strips"
            ] + custom_dirs

            for folder in base_folders:
                (project_path / folder).mkdir(parents=True, exist_ok=True)

            template_path = self.vault_templates_dir / project_template
            if template_path.exists() and template_path.is_dir():
                for item in template_path.iterdir():
                    if item.is_file(): shutil.copy2(item, project_path / vfs_svn)
                    elif item.is_dir(): shutil.copytree(item, project_path / vfs_svn / item.name, dirs_exist_ok=True)

            payload_data = {
                "project_name": project_name.strip(),
                "kitsu_project_id": project_id,
                "blender_version": blender_version.strip(),
                "template": project_template.strip(),
                "dependencies": dependencies,
                "topography_signature": {
                    "vfs_svn": vfs_svn, "vfs_shared": vfs_shared,
                    "vfs_local": vfs_local, "vfs_pipeline": vfs_pipe
                }
            }

            payload_file_svn = project_path / vfs_svn / "project_init.json"
            with open(payload_file_svn, 'w', encoding='utf-8') as f: json.dump(payload_data, f, indent=4)
            shutil.copy2(payload_file_svn, project_path / vfs_pipe / "project_init.json")

            if splash_image_path:
                splash_source = Path(splash_image_path)
                if splash_source.exists() and splash_source.is_file():
                    shutil.copy(splash_source, project_path / vfs_pipe / "splash.png")
                    kitsu.upload_project_splash(project_id, splash_image_path)

            base_repo_url = self.config_factory.get_vcs_repository_url()
            
            try:
                vcs_type = self.config_factory.get_vcs_adapter_type()
                final_repo_url = f"{base_repo_url}/{folder_name}/{vfs_svn}" if "localhost" in base_repo_url else f"{base_repo_url}/{folder_name}/{vfs_svn}"
                
                vcs_root = project_path / vfs_svn
                router = VCSRouter(vcs_type=vcs_type, repo_url=final_repo_url, workspace_dir=vcs_root)
                adapter = router.get_adapter()
                
                if "localhost" in base_repo_url and not vcs_user:
                    vcs_user, vcs_pwd = DEV_SVN_USER, DEV_SVN_PASSWORD
                    
                adapter.create_server_repository(project_name, vfs_svn)
                
                if vcs_user and vcs_pwd:
                    adapter.full_pull(username=vcs_user, password=vcs_pwd)
                    print("[ProjectBuilder] Repositorio VCS emparejado.")
                    
                    ignore_patterns = [f"{vfs_local}", f"{vfs_shared}", f"{vfs_pipe}", "*.blend1", "*.blend2", "quit.blend"]
                    adapter.setup_ignore(ignore_patterns)

                    # INYECCIÓN DEL SCRIPT PARA SVN/VFS LOCAL
                    startup_dir = project_path / vfs_local / "blender_data" / "scripts" / "startup"
                    startup_dir.mkdir(parents=True, exist_ok=True)
                    patch_file = startup_dir / "00_openstudio_vfs_patch.py"
                    
                    template_patch_path = Path(__file__).resolve().parent.parent / "infrastructure" / "templates" / "vfs_patch.py.template"
                    if template_patch_path.exists():
                        with open(template_patch_path, "r", encoding="utf-8") as t_file:
                            patch_content = t_file.read()
                        patch_content = patch_content.replace("{VFS_SVN_PLACEHOLDER}", vfs_svn)
                        with open(patch_file, "w", encoding="utf-8") as f:
                            f.write(patch_content)
                        print(f"[ProjectBuilder] Parche VFS inyectado exitosamente.")

                    # COMMIT INICIAL LIMPIO (Sin forzar edición)
                    adapter.add_all(".")
                    adapter.commit(
                        message="Initial commit: Hub Project Blueprint established.", 
                        paths=["."], 
                        username=vcs_user, 
                        password=vcs_pwd
                    )
                else:
                    print("[ProjectBuilder] No VCS credentials provided. Skipping initial commit.")
            except Exception as e:
                print(f"[ProjectBuilder] Warning: Initial VCS commit failed: {e}")

            return True, f"Project '{folder_name}' successfully generated."

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"\n[ProjectBuilder] CRASH FATAL:\n{error_trace}\n")
            return False, f"System error creating directory tree: {str(e)}"
