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

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from src.application.services.addon_config_generator import AddonConfigGenerator
from src.application.services.task_file_resolver import TaskFileResolver
from src.domain.shared_kernel.env_contract import SandboxEnvironment
from src.domain.workspace.blueprint import ProjectBlueprint
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

        self._ensure_workspace_is_current(project_root, blueprint)

        template_name = blueprint.get("template", "Macuare_Estudio")
        version = blueprint.get("version_locking", {}).get(
            "blender_version", blueprint.get("blender_version", "5.1.2")
        )

        status_callback(f"Looking for Blender {version} in the local sandbox...", "yellow")

        base_blender_dir = project_root / vfs_local / "blender-build"
        blender_bin = BlenderLocator.resolve(base_blender_dir, version=version)

        status_callback(
            f"Isolated executable found at: {BlenderLocator.archive_folder_name(version)}", "green"
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
        if target_file is None:
            raise FileNotFoundError(
                "Task file not found on disk. Ask a PM/TD to create or link the file."
            )

        vcs_adapter = self._resolve_vcs_adapter(project_root)
        svn_locale = self._resolve_svn_locale(project_root)

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
            vcs_adapter=vcs_adapter,
            svn_user=svn_user,
            svn_password=svn_pwd,
            svn_locale=svn_locale,
            blender_user_resources=str(sandbox_dir),
            blender_user_config=str(sandbox_dir / "config"),
            blender_user_scripts=str(sandbox_dir / "scripts"),
        )

        # Merge the typed env over the process env (None is already dropped).
        env = os.environ.copy()
        for key, value in sandbox_env.to_os_environ().items():
            env[key] = str(value)

        self._refresh_addon_config(project_root)
        self._snapshot_project_preferences(project_root, vfs_local)

        bootstrap_dst = self._deploy_bootstrap(project_root, vfs_local)

        status_callback(f"Arrancando {project_name} (Contexto: {task_type.upper()})...", "green")

        cmd = [str(blender_bin), "--app-template", template_name, "--python", str(bootstrap_dst)]
        proceso = subprocess.Popen(cmd, env=env)

        status_callback(f"Blender en ejecucion ({project_name})...", "#00aaff")
        proceso.wait()
        status_callback(f"Sesion de {project_name} terminada.", "green")

    def _resolve_svn_locale(self, project_root: Path) -> str:
        """Return the SVN client locale configured for the project's server."""
        try:
            getter = getattr(self.config_factory, "get_server_for_project", None)
            server = getter(project_root) if callable(getter) else None
            profile = getattr(server, "profile", None)
            if profile is None:
                profile = self.config_factory.get_vcs_server_profile()
            return str(getattr(profile, "locale", "") or "").strip()
        except Exception:  # noqa: BLE001 - the DCC can start without a locale
            return ""

    def _resolve_vcs_adapter(self, project_root: Path) -> str:
        """Return the project's VCS adapter, or an empty string when disabled."""
        adapter = ""
        try:
            getter = getattr(self.config_factory, "get_server_for_project", None)
            server = getter(project_root) if callable(getter) else None
            adapter = str(getattr(server, "adapter", "") or "")
            if not adapter:
                adapter = str(self.config_factory.get_vcs_adapter_type() or "")
        except Exception:  # noqa: BLE001
            adapter = ""
        adapter = adapter.strip().lower()
        return "" if adapter in ("", "none") else adapter

    def _ensure_workspace_is_current(self, project_root: Path, local_config: dict) -> None:
        """Refuse to launch a workspace whose project_init.json changed.

        ``project_config.json`` remains the launch source. The Hub only mirrors
        project_init.json into it after a project configuration change; if the
        user edited the blueprint outside the Hub, the workspace must be
        updated before launching.
        """
        if bool(local_config.get("workspace_update_required")):
            raise RuntimeError(
                "The project configuration changed. Update the workspace before launching."
            )

        pipeline_getter = getattr(self.config_factory, "get_vfs_pipeline_name", None)
        vfs_pipeline = (
            (local_config.get("topography_signature") or {}).get("vfs_pipeline")
            or (pipeline_getter() if callable(pipeline_getter) else "pipeline")
        )
        init_path = Path(project_root) / vfs_pipeline / "project_init.json"
        if not init_path.exists():
            return
        try:
            with open(init_path, "r", encoding="utf-8") as handle:
                init_data = json.load(handle)
        except Exception:  # noqa: BLE001
            return

        blueprint_version = str(
            (init_data or {}).get("blender_version")
            or ((init_data or {}).get("version_locking") or {}).get("blender_version")
            or ""
        )
        local_version = str(local_config.get("blender_version") or "")
        if blueprint_version and local_version and blueprint_version != local_version:
            raise RuntimeError(
                "The project configuration changed. Update the workspace before launching."
            )

    @staticmethod
    def _resolve_target_file(
        project_root: Path, production_folder: str, task_data: dict, target_file: Optional[Path]
    ) -> Optional[Path]:
        if target_file:
            return target_file

        resolved = TaskFileResolver().resolve(
            project_root, task_data, production_folder=production_folder
        )
        return resolved.absolute_path if resolved is not None else None

    @staticmethod
    def _find_latest_versioned(base_target: Path) -> Optional[Path]:
        """Return the newest ``<base>-vNNN.blend`` (case-insensitive), if any."""
        directory = base_target.parent
        if not directory.exists():
            return None

        pattern = re.compile(rf"^{re.escape(base_target.name)}-v(\d+)\.blend$", re.IGNORECASE)
        matches = []
        for entry in directory.iterdir():
            match = pattern.match(entry.name)
            if match:
                matches.append((int(match.group(1)), entry))

        if not matches:
            return None
        return max(matches, key=lambda item: item[0])[1]

    @staticmethod
    def _find_case_insensitive(path: Path) -> Optional[Path]:
        """Return an existing file whose name matches ``path`` ignoring case."""
        directory = path.parent
        if not directory.exists():
            return None

        target = path.name.lower()
        for entry in directory.iterdir():
            if entry.name.lower() == target:
                return entry
        return None

    @staticmethod
    def _snapshot_project_preferences(project_root: Path, vfs_local: str) -> None:
        """Keep a per-session copy of userpref.blend for restore diagnostics."""
        source = project_root / vfs_local / "blender_data" / "config" / "userpref.blend"
        if not source.is_file():
            return
        destination = project_root / vfs_local / "blender_prefs" / "session_start.blend"
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as error:
            print(f"[LaunchService] Preference snapshot skipped: {error}")

    def _refresh_addon_config(self, project_root: Path) -> None:
        """Regenerate the ``cfg_<addon>.py`` scripts from the project blueprint.

        This keeps already-installed workspaces (and older blueprints) in sync
        without requiring a full reinstall, and guarantees the DCC-side support
        modules are present before Blender boots.
        """
        try:
            vfs_pipeline = self.config_factory.get_vfs_pipeline_name()
            init_path = project_root / vfs_pipeline / "project_init.json"
            if not init_path.exists():
                return
            with open(init_path, "r", encoding="utf-8") as handle:
                blueprint = ProjectBlueprint.from_dict(json.load(handle))
            AddonConfigGenerator(self.config_factory).generate(
                project_root,
                blueprint.addon_configuration,
                blueprint.topography,
            )
        except Exception as error:  # noqa: BLE001
            print(f"[LaunchService] Add-on config refresh skipped: {error}")

    @staticmethod
    def _deploy_bootstrap(project_root: Path, vfs_local: str) -> Path:
        src_root = Path(__file__).resolve().parent.parent.parent  # -> src/
        templates_dir = src_root / "infrastructure" / "templates"
        bootstrap_src = templates_dir / "bootstrap.py"
        env_contract_src = src_root / "domain" / "shared_kernel" / "env_contract.py"
        addon_runtime_src = templates_dir / "addon_runtime.py"

        bootstrap_dst = project_root / vfs_local / "bootstrap.py"
        bootstrap_dst.parent.mkdir(parents=True, exist_ok=True)

        if not bootstrap_src.exists():
            raise FileNotFoundError("No se encontro src/infrastructure/templates/bootstrap.py")

        shutil.copy2(bootstrap_src, bootstrap_dst)
        # Ship the shared env contract + add-on runtime next to bootstrap.py so
        # the DCC-side scripts can import them from their own directory
        # (Blender has no `src`).
        if env_contract_src.exists():
            shutil.copy2(env_contract_src, bootstrap_dst.parent / "env_contract.py")
        if addon_runtime_src.exists():
            shutil.copy2(addon_runtime_src, bootstrap_dst.parent / "addon_runtime.py")
        return bootstrap_dst
