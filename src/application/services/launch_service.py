# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/launch_service.py
# Architectural role: Application service / DCC launch saga
# =========================================================================================

"""Launch application service.

Encapsulates the DCC-launch saga: resolve the isolated Blender binary, build
the typed ``SandboxEnvironment`` (the shared env contract), deploy the
bootstrap script, and spawn the subprocess.

Extracted from the module-level ``lanzar_blender`` function; the raw
``os.environ`` string writes are replaced by ``SandboxEnvironment.to_os_environ()``.
"""

import glob
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from src.domain.path_resolver import PathResolver
from src.domain.shared_kernel.env_contract import SandboxEnvironment
from src.infrastructure.sandbox.blender_locator import BlenderLocator

StatusCallback = Callable[[str, str], None]


class LaunchService:
    def __init__(self, config_factory) -> None:
        self.config_factory = config_factory

    def launch(
        self,
        project_root: Path,
        config_path: Path,
        svn_user: str,
        svn_pwd: str,
        kitsu_user: str,
        kitsu_pwd: str,
        kitsu_host: str,
        user_role: str,
        task_data: dict,
        target_file: Optional[Path],
        status_callback: StatusCallback,
        production_folder: str = "",
    ) -> None:
        vfs_local = self.config_factory.get_vfs_local_name()
        vfs_svn = self.config_factory.get_vfs_svn_name()

        if not production_folder:
            production_folder = vfs_svn

        with open(config_path, "r", encoding="utf-8") as handle:
            blueprint = json.load(handle)

        template_name = blueprint.get("template", "Macuare_Estudio")
        version = blueprint.get("version_locking", {}).get(
            "blender_version", blueprint.get("blender_version", "5.1.2")
        )

        status_callback(f"Buscando Blender {version} en Sandbox Local...", "yellow")

        base_blender_dir = project_root / vfs_local / "blender-build"
        blender_bin = BlenderLocator.resolve(base_blender_dir, version=version)

        status_callback(
            f"Ejecutable aislado encontrado en: {BlenderLocator.archive_folder_name(version)}", "green"
        )
        status_callback("Preparando Sandboxing y Variables de Entorno...", "yellow")

        sandbox_dir = project_root / vfs_local / "blender_data"
        extensions_dir = sandbox_dir / "extensions" / "user_default"
        extensions_dir.mkdir(parents=True, exist_ok=True)

        task_type = task_data.get("task_type_name", "generic")
        project_name = task_data.get("project_name", project_root.name)

        vfs_pipe = self.config_factory.get_vfs_pipeline_name()
        splash_path = project_root / vfs_pipe / "splash.png"

        target_file = self._resolve_target_file(project_root, production_folder, task_data, target_file)

        sandbox_env = SandboxEnvironment(
            project_config=str(config_path),
            project_root=str(project_root),
            project_name=project_name,
            production_folder=production_folder,
            extensions_dir=str(extensions_dir),
            splash_path=str(splash_path) if splash_path.exists() else "",
            target_file=str(target_file) if target_file else "",
            user_role=user_role,
            task_type=task_type,
            kitsu_host=kitsu_host,
            kitsu_user=kitsu_user,
            kitsu_pwd=kitsu_pwd,
            kitsu_project_id=task_data.get("project_id", ""),
            kitsu_entity_type=(task_data.get("entity_type") or "SHOT").upper(),
            kitsu_entity_id=task_data.get("entity_id", ""),
            kitsu_entity_name=task_data.get("entity_name", ""),
            kitsu_sequence_id=task_data.get("sequence_id", ""),
            kitsu_sequence_name=task_data.get("sequence_name", ""),
            kitsu_task_type_id=task_data.get("task_type_id", ""),
            kitsu_task_type_name=task_type,
            kitsu_asset_type_id=task_data.get("asset_type_id", task_data.get("entity_type_id", "")),
            kitsu_asset_type_name=task_data.get("asset_type_name", ""),
            svn_user=svn_user,
            svn_password=svn_pwd,
            blender_user_resources=str(sandbox_dir),
            blender_user_config=str(sandbox_dir / "config"),
            blender_user_scripts=str(sandbox_dir / "scripts"),
        )

        # Merge the typed env over the process env (None is already dropped).
        env = os.environ.copy()
        for key, value in sandbox_env.to_os_environ().items():
            env[key] = str(value)

        bootstrap_dst = self._deploy_bootstrap(project_root, vfs_local)

        status_callback(f"Arrancando {project_name} (Contexto: {task_type.upper()})...", "green")

        cmd = [str(blender_bin), "--app-template", template_name, "--python", str(bootstrap_dst)]
        proceso = subprocess.Popen(cmd, env=env)

        status_callback(f"Blender en ejecucion ({project_name})...", "#00aaff")
        proceso.wait()
        status_callback(f"Sesion de {project_name} terminada.", "green")

    @staticmethod
    def _resolve_target_file(
        project_root: Path, production_folder: str, task_data: dict, target_file: Optional[Path]
    ) -> Optional[Path]:
        if target_file:
            return target_file

        resolver = PathResolver()
        resolved_rel_path = resolver.resolve(task_data)
        if not resolved_rel_path:
            return None

        base_target_str = str(project_root / production_folder / resolved_rel_path).replace(".blend", "")
        versioned_files = glob.glob(f"{base_target_str}-v*.blend")
        if versioned_files:
            return Path(sorted(versioned_files)[-1])
        return Path(f"{base_target_str}.blend")

    @staticmethod
    def _deploy_bootstrap(project_root: Path, vfs_local: str) -> Path:
        bootstrap_src = (
            Path(__file__).resolve().parent.parent.parent / "infrastructure" / "templates" / "bootstrap.py"
        )
        bootstrap_dst = project_root / vfs_local / "bootstrap.py"
        bootstrap_dst.parent.mkdir(parents=True, exist_ok=True)
        if bootstrap_src.exists():
            shutil.copy2(bootstrap_src, bootstrap_dst)
        else:
            raise FileNotFoundError("No se encontro src/infrastructure/templates/bootstrap.py")
        return bootstrap_dst
