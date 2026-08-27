# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/env_launcher.py
# Architectural role: Deprecated shim over LaunchService
# =========================================================================================

"""DEPRECATED shim.

The DCC-launch saga now lives in
``src.application.services.launch_service.LaunchService``. This module-level
function keeps the legacy ``lanzar_blender`` signature so existing callers
(``view_artist``'s LaunchTaskWorker) keep working.
"""

from pathlib import Path
from typing import Optional

from src.application.services.launch_service import LaunchService


def lanzar_blender(
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
    status_callback,
    production_folder: str = "",
    config_factory=None,
):
    try:
        if not config_factory:
            raise RuntimeError("ConfigFactory no fue inyectado en el EnvLauncher.")

        LaunchService(config_factory).launch(
            project_root=project_root,
            config_path=config_path,
            svn_user=svn_user,
            svn_pwd=svn_pwd,
            kitsu_user=kitsu_user,
            kitsu_pwd=kitsu_pwd,
            kitsu_host=kitsu_host,
            user_role=user_role,
            task_data=task_data,
            target_file=target_file,
            status_callback=status_callback,
            production_folder=production_folder,
        )
    except Exception as error:  # noqa: BLE001
        status_callback(f"Error Crítico Launcher: {str(error)}", "red")
        import traceback

        print(f"Error detallado Launcher:\n{traceback.format_exc()}")
