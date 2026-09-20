# =========================================================================================
# OPENSTUDIOHUB
# Module: core/templates/addon_runtime.py
# Architectural role: DCC Scripting / Add-on startup runtime (sandbox helper)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
# =========================================================================================

"""Add-on agnostic loader for the generated ``cfg_<addon>.py`` scripts.

The Hub writes one config script per active add-on into the Blender user-scripts
``openstudio/`` folder. That folder is intentionally outside ``startup/`` and
``modules/``: Blender imports and calls ``register()`` on those before the
extension repositories (``bl_ext``/``bl_pkg``) exist, which broke add-on
activation. This module discovers the scripts and invokes their ``register()``
entry point from a controlled moment (Hub timer for interactive sessions,
synchronously for headless builds). It is shipped into the sandbox next to
``bootstrap.py`` and ``env_contract.py``.

Importing a ``cfg_*.py`` file is side-effect free: the script only defines
functions. This runtime decides *when* each add-on is configured.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import List, Optional


def default_config_dir() -> Optional[Path]:
    """Resolve ``<BLENDER_USER_SCRIPTS>/openstudio`` from the env contract."""
    try:
        from env_contract import SandboxEnvironment

        env = SandboxEnvironment.from_os_environ()
        scripts_dir = env.blender_user_scripts
        if scripts_dir:
            return Path(scripts_dir) / "openstudio"
    except Exception:  # noqa: BLE001
        return None
    return None


def discover(config_dir: Path) -> List[Path]:
    """Return the generated ``cfg_*.py`` scripts in deterministic order."""
    if not config_dir or not Path(config_dir).exists():
        return []
    return sorted(Path(config_dir).glob("cfg_*.py"))


def load_module(script_path: Path):
    """Import a generated config script by file path (idempotent)."""
    script_path = Path(script_path)
    module_name = script_path.stem
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # noqa: BLE001
        print(f"[AddonRuntime] Failed to import {script_path.name}: {error}")
        sys.modules.pop(module_name, None)
        return None
    return module


def register_all(config_dir: Optional[Path] = None) -> List[str]:
    """Load and register every generated add-on config script.

    Returns the list of add-on module names that were registered.
    """
    directory = Path(config_dir) if config_dir else default_config_dir()
    registered: List[str] = []
    for script_path in discover(directory):
        module = load_module(script_path)
        if module is None:
            continue
        register = getattr(module, "register", None)
        if callable(register):
            try:
                register()
                registered.append(script_path.stem)
            except Exception as error:  # noqa: BLE001
                print(f"[AddonRuntime] register() failed for {script_path.name}: {error}")
    return registered


def load(addon_name: str, config_dir: Optional[Path] = None):
    """Return the loaded config module for ``addon_name`` (or ``None``)."""
    module_name = f"cfg_{addon_name}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    directory = Path(config_dir) if config_dir else default_config_dir()
    script_path = (directory / f"{module_name}.py") if directory else None
    if script_path and script_path.exists():
        return load_module(script_path)
    return sys.modules.get(addon_name)


def notify_file_opened(config_dir: Optional[Path] = None) -> None:
    """Notify every generated add-on that a ``.blend`` file was just loaded.

    Add-ons exposing the optional ``on_file_opened()`` hook use it to restore
    context wiped by Blender (Kitsu re-authenticates and rebuilds its cache).
    """
    directory = Path(config_dir) if config_dir else default_config_dir()
    for script_path in discover(directory):
        module = load_module(script_path)
        if module is None:
            continue
        hook = getattr(module, "on_file_opened", None)
        if callable(hook):
            try:
                hook()
            except Exception as error:  # noqa: BLE001
                print(f"[AddonRuntime] on_file_opened() failed for {script_path.name}: {error}")
