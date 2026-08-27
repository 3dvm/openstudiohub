# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/installation_service.py
# Architectural role: Application service / workspace installation saga
# =========================================================================================

"""Workspace installation saga.

Orchestrates: VCS checkout (full or sparse jailing) -> Blender extraction ->
template injection -> add-on deployment -> VFS symlinks -> local config
generation. Extracted from ``LocalInstaller`` (now a thin facade).
"""

import json
import platform
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

from src.application.sparse_manager import SparseManager
from src.infrastructure.vcs.vcs_router import VCSRouter


class InstallationService:
    def __init__(self, config_factory, vault_root: Path) -> None:
        self.config_factory = config_factory
        self.vault_root = vault_root
        self.boveda_addons = self.vault_root / "addons"
        self.boveda_blender = self.vault_root / "blender_versions"
        self.boveda_templates = self.vault_root / "project_templates"

    @staticmethod
    def _get_os_info() -> Tuple[str, str]:
        system = platform.system().lower()
        if system == "linux":
            return "linux", "tar.xz"
        if system == "windows":
            return "windows", "zip"
        return "macos", "dmg"

    def instalar_entorno(
        self,
        project_root: Path,
        vcs_user: str,
        vcs_pwd: str,
        status_callback,
        user_role: str = "artist",
        task_metadata: Optional[Dict[str, str]] = None,
    ) -> Tuple[bool, str]:
        vfs_svn = self.config_factory.get_vfs_svn_name()
        vfs_local = self.config_factory.get_vfs_local_name()
        vfs_pipe = self.config_factory.get_vfs_pipeline_name()
        vfs_shared = self.config_factory.get_vfs_shared_name()

        vcs_root = project_root / vfs_svn
        init_json_path = project_root / vfs_pipe / "project_init.json"

        try:
            if not init_json_path.exists():
                return False, f"Critical: project_init.json not found in {vfs_pipe}/. Make sure the NAS is fully synced."

            status_callback("Reading structural topography and manifest...", "yellow")
            with open(init_json_path, "r", encoding="utf-8") as handle:
                init_data = json.load(handle)

            project_name = init_data.get("project_name", project_root.name)
            blender_version = init_data.get("blender_version", "4.2.0")
            dependencies = init_data.get("dependencies", {})
            template_name = init_data.get("template", "")

            checkout_ok = self._gestionar_vcs(project_root, vfs_svn, vcs_user, vcs_pwd, status_callback, user_role, task_metadata)
            if not checkout_ok:
                return False, "VCS Synchronization aborted."

            self._instalar_blender(project_root, vfs_local, blender_version, status_callback)

            if template_name:
                self._instalar_template(project_root, vfs_local, template_name, blender_version, status_callback)

            status_callback("Deploying project extensions...", "yellow")
            self._sincronizar_addons(project_root, vfs_local, dependencies, status_callback)

            status_callback("Configuring production VFS symlinks...", "yellow")
            self._crear_symlinks(project_path=project_root, vfs_svn=vfs_svn, vfs_shared=vfs_shared)

            status_callback("Generating local workspace configuration...", "yellow")
            config_local_dir = project_root / vfs_local
            config_local_dir.mkdir(exist_ok=True)

            local_config_data = {
                "project_name": project_name,
                "blender_version": blender_version,
                "kitsu_host": self.config_factory.get_kitsu_api_url(),
                "dependencies": dependencies,
                "paths": {
                    "root": str(project_root),
                    "svn_root": str(vcs_root),
                    "assets": str(vcs_root / "pro" / "assets"),
                    "shots": str(vcs_root / "pro" / "shots"),
                    "render_output": str(project_root / vfs_shared / "editorial" / "footage"),
                    "deliverables": str(project_root / vfs_shared / "editorial" / "deliver"),
                },
            }

            config_local_file = config_local_dir / "project_config.json"
            with open(config_local_file, "w", encoding="utf-8") as handle:
                json.dump(local_config_data, handle, indent=4)

            return True, "Local workspace installed and verified successfully."

        except Exception as error:  # noqa: BLE001
            return False, f"Critical error during local installation: {str(error)}"

    def _gestionar_vcs(self, project_root, vfs_svn, vcs_user, vcs_pwd, status_callback, user_role, task_metadata) -> bool:
        vcs_root = project_root / vfs_svn
        vcs_type = self.config_factory.get_vcs_adapter_type()

        base_repo_url = self.config_factory.get_vcs_repository_url()
        final_repo_url = f"{base_repo_url}/{project_root.name}/{vfs_svn}"

        router = VCSRouter(vcs_type=vcs_type, repo_url=final_repo_url, workspace_dir=vcs_root)
        is_sparse_enabled = getattr(self.config_factory, "is_vendor_sparse_enabled", lambda: True)()

        if user_role == "vendor" and is_sparse_enabled:
            status_callback("Initializing Sparse Checkout (Jailing Mode)...", "yellow")
            sparse_manager = SparseManager(vcs_router=router, status_callback=status_callback)
            return sparse_manager.setup_vendor_workspace(task_metadata, vcs_user, vcs_pwd)

        adapter = router.get_adapter()
        status_callback(f"Synchronizing Full Workspace with {vcs_type.upper()}...", "yellow")

        try:
            adapter.full_pull(username=vcs_user, password=vcs_pwd)
            status_callback(f"{vcs_type.upper()}: Synchronization completed successfully.", "green")
            return True
        except RuntimeError as error:
            status_callback("Repository connection failed: Check credentials or network.", "red")
            print(f"[InstallationService] VCS Driver Error: {error}")
            return False

    def _instalar_blender(self, project_root, vfs_local, version, status_callback):
        os_name, ext = self._get_os_info()
        archive_name = f"blender-{version}-{os_name}-x64.{ext}"
        archive_path = self.boveda_blender / archive_name

        dest_dir = project_root / vfs_local / "blender-build"
        folder_name_extracted = f"blender-{version}-{os_name}-x64"
        final_exec_dir = dest_dir / folder_name_extracted

        if final_exec_dir.exists():
            status_callback(f"Blender {version} is already cached locally.", "white")
            return

        if not archive_path.exists():
            raise FileNotFoundError(f"Binary archive not found in Vault: {archive_path}")

        status_callback(f"Extracting Blender {version} (This will take a couple of minutes)...", "yellow")
        dest_dir.mkdir(parents=True, exist_ok=True)

        if ext == "tar.xz":
            with tarfile.open(archive_path, "r:xz") as tar:
                tar.extractall(path=dest_dir)
        elif ext == "zip":
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                zip_ref.extractall(dest_dir)

        status_callback(f"Blender {version} extracted successfully.", "green")

    def _sincronizar_addons(self, project_root, vfs_local, dependencies, status_callback):
        extensions_dir = project_root / vfs_local / "blender_data" / "extensions" / "user_default"
        extensions_dir.mkdir(parents=True, exist_ok=True)

        if isinstance(dependencies, str):
            try:
                dependencies = json.loads(dependencies)
            except Exception:
                dependencies = {}

        addons_dict = dependencies.get("addons", {})

        for addon_name, addon_version in addons_dict.items():
            status_callback(f"Buscando extensión: {addon_name} (v{addon_version})...", "yellow")

            origen_addon_zip = None
            if self.boveda_addons.exists():
                for archivo in self.boveda_addons.rglob("*.zip"):
                    if addon_name.lower() in archivo.name.lower():
                        origen_addon_zip = archivo
                        break

            if origen_addon_zip and origen_addon_zip.exists():
                safe_folder_name = addon_name.replace(" ", "_").lower()
                destino_addon = extensions_dir / safe_folder_name

                if not destino_addon.exists():
                    status_callback(f"Desplegando extensión: {addon_name}...", "yellow")
                    destino_addon.mkdir(parents=True, exist_ok=True)
                    try:
                        with zipfile.ZipFile(origen_addon_zip, "r") as zip_ref:
                            zip_ref.extractall(destino_addon)
                    except zipfile.BadZipFile:
                        status_callback(f"Error: Archive {origen_addon_zip.name} is corrupted.", "red")
            else:
                status_callback(f"Warning: Extension '{addon_name}' not found in Vault.", "red")

    def _crear_symlinks(self, project_path, vfs_svn, vfs_shared):
        shared_edit_dir = project_path / vfs_shared / "editorial"
        svn_edit_dir = project_path / vfs_svn / "edit"
        svn_edit_dir.mkdir(parents=True, exist_ok=True)

        for folder in ["footage", "deliver", "export"]:
            target_path = shared_edit_dir / folder
            target_path.mkdir(parents=True, exist_ok=True)

            link_path = svn_edit_dir / folder
            if not link_path.exists() and not link_path.is_symlink():
                try:
                    link_path.symlink_to(target_path, target_is_directory=True)
                except OSError as error:
                    print(f"[VFS WARNING] Symlink creation failed (Privilege issue?): {error}")

    def _instalar_template(self, project_root, vfs_local, template_name, blender_version, status_callback):
        source_path = self.boveda_templates / template_name
        if not source_path.exists():
            status_callback(f"Warning: Project template '{template_name}' not found in Vault.", "red")
            return

        os_name, _ = self._get_os_info()
        ver_major = ".".join(blender_version.split(".")[:2])
        blender_folder = f"blender-{blender_version}-{os_name}-x64"
        dest_path = (
            project_root / vfs_local / "blender-build" / blender_folder / ver_major
            / "scripts" / "startup" / "bl_app_templates_system" / template_name
        )

        status_callback(f"Injecting template '{template_name}' into isolated container...", "yellow")
        if dest_path.exists():
            shutil.rmtree(dest_path)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_path, dest_path, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))
