# =========================================================================================
# OPENSTUDIOHUB
# Module: core/env_contract.py
# Architectural role: Shared Kernel / Sandbox Environment Contract (SPEC)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. All rights reserved.
# License: GNU General Public License v3.0 (GPLv3)
# =========================================================================================

"""
Single source of truth for the process-environment "contract" between the Hub
and the Blender-side scripts (``src/infrastructure/templates/bootstrap.py``,
``src/infrastructure/templates/headless_builder.py``, and ``addons/openstudio_toolkit``).

Historically the ~25 ``OPENSTUDIO_*`` / ``BLENDER_*`` variables were written by
six different modules and read by three more, as raw ``os.environ`` strings with
no validation — so producer/consumer drift was guaranteed. This module is the
typed model they must all share.

STATUS (Phase 0): this is the *specification only*. It is not yet wired into the
producers/consumers; that happens in Phase 5 (LaunchService) and Phase 7
(Blender-side alignment). Until then it must stay in sync with the existing
string keys listed below.

Because Blender runs its own embedded Python and cannot import the Hub package
tree, this single file is copied into the sandbox alongside ``bootstrap.py`` and
``headless_builder.py`` (same mechanism already used to ship ``bootstrap.py``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from typing import Dict, Optional


class EnvKey:
    """Canonical environment-variable names. Use these, never bare strings."""

    # Workspace / sandbox
    PROJECT_CONFIG = "OPENSTUDIO_PROJECT_CONFIG"
    PROJECT_ROOT = "OPENSTUDIO_PROJECT_ROOT"
    PROJECT_NAME = "OPENSTUDIO_PROJECT_NAME"
    PRODUCTION_FOLDER = "OPENSTUDIO_PRODUCTION_FOLDER"
    EXTENSIONS_DIR = "OPENSTUDIO_EXTENSIONS_DIR"
    SPLASH_PATH = "OPENSTUDIO_SPLASH_PATH"
    TARGET_FILE = "OPENSTUDIO_TARGET_FILE"
    USER_ROLE = "OPENSTUDIO_USER_ROLE"
    TASK_TYPE = "OPENSTUDIO_TASK_TYPE"

    # Kitsu context
    KITSU_HOST = "OPENSTUDIO_KITSU_HOST"
    KITSU_USER = "OPENSTUDIO_KITSU_USER"
    KITSU_PWD = "OPENSTUDIO_KITSU_PWD"
    KITSU_PROJECT_ID = "OPENSTUDIO_KITSU_PROJECT_ID"
    KITSU_ENTITY_TYPE = "OPENSTUDIO_KITSU_ENTITY_TYPE"
    KITSU_ENTITY_ID = "OPENSTUDIO_KITSU_ENTITY_ID"
    KITSU_ENTITY_NAME = "OPENSTUDIO_KITSU_ENTITY_NAME"
    KITSU_SEQUENCE_ID = "OPENSTUDIO_KITSU_SEQUENCE_ID"
    KITSU_SEQUENCE_NAME = "OPENSTUDIO_KITSU_SEQUENCE_NAME"
    KITSU_TASK_TYPE_ID = "OPENSTUDIO_KITSU_TASK_TYPE_ID"
    KITSU_TASK_TYPE_NAME = "OPENSTUDIO_KITSU_TASK_TYPE_NAME"
    KITSU_ASSET_TYPE_ID = "OPENSTUDIO_KITSU_ASSET_TYPE_ID"
    KITSU_ASSET_TYPE_NAME = "OPENSTUDIO_KITSU_ASSET_TYPE_NAME"

    # Headless builder context
    BUILD_TARGET = "OPENSTUDIO_BUILD_TARGET"
    TARGET_ENTITY_ID = "OPENSTUDIO_TARGET_ENTITY_ID"
    TARGET_SEQUENCE = "OPENSTUDIO_TARGET_SEQUENCE"

    # VCS credentials (RAM-only, injected for the DCC subprocess)
    SVN_USER = "OPENSTUDIO_SVN_USER"
    SVN_PASSWORD = "OPENSTUDIO_SVN_PASSWORD"

    # Blender sandbox overrides (user resources / config / scripts isolation)
    BLENDER_USER_RESOURCES = "BLENDER_USER_RESOURCES"
    BLENDER_USER_CONFIG = "BLENDER_USER_CONFIG"
    BLENDER_USER_SCRIPTS = "BLENDER_USER_SCRIPTS"


# dataclass field name -> EnvKey constant (single mapping for both directions).
_FIELD_TO_KEY: Dict[str, str] = {
    "project_config": EnvKey.PROJECT_CONFIG,
    "project_root": EnvKey.PROJECT_ROOT,
    "project_name": EnvKey.PROJECT_NAME,
    "production_folder": EnvKey.PRODUCTION_FOLDER,
    "extensions_dir": EnvKey.EXTENSIONS_DIR,
    "splash_path": EnvKey.SPLASH_PATH,
    "target_file": EnvKey.TARGET_FILE,
    "user_role": EnvKey.USER_ROLE,
    "task_type": EnvKey.TASK_TYPE,
    "kitsu_host": EnvKey.KITSU_HOST,
    "kitsu_user": EnvKey.KITSU_USER,
    "kitsu_pwd": EnvKey.KITSU_PWD,
    "kitsu_project_id": EnvKey.KITSU_PROJECT_ID,
    "kitsu_entity_type": EnvKey.KITSU_ENTITY_TYPE,
    "kitsu_entity_id": EnvKey.KITSU_ENTITY_ID,
    "kitsu_entity_name": EnvKey.KITSU_ENTITY_NAME,
    "kitsu_sequence_id": EnvKey.KITSU_SEQUENCE_ID,
    "kitsu_sequence_name": EnvKey.KITSU_SEQUENCE_NAME,
    "kitsu_task_type_id": EnvKey.KITSU_TASK_TYPE_ID,
    "kitsu_task_type_name": EnvKey.KITSU_TASK_TYPE_NAME,
    "kitsu_asset_type_id": EnvKey.KITSU_ASSET_TYPE_ID,
    "kitsu_asset_type_name": EnvKey.KITSU_ASSET_TYPE_NAME,
    "build_target": EnvKey.BUILD_TARGET,
    "target_entity_id": EnvKey.TARGET_ENTITY_ID,
    "target_sequence": EnvKey.TARGET_SEQUENCE,
    "svn_user": EnvKey.SVN_USER,
    "svn_password": EnvKey.SVN_PASSWORD,
    "blender_user_resources": EnvKey.BLENDER_USER_RESOURCES,
    "blender_user_config": EnvKey.BLENDER_USER_CONFIG,
    "blender_user_scripts": EnvKey.BLENDER_USER_SCRIPTS,
}


@dataclass
class SandboxEnvironment:
    """
    Typed model of the environment injected into Blender subprocesses.

    Every field maps 1:1 to an :class:`EnvKey`. ``to_os_environ()`` serializes
    only the populated fields (empty values are dropped, matching the existing
    "sanitize None to ''" behavior without leaking empty vars).
    """

    project_config: Optional[str] = None
    project_root: Optional[str] = None
    project_name: Optional[str] = None
    production_folder: Optional[str] = None
    extensions_dir: Optional[str] = None
    splash_path: Optional[str] = None
    target_file: Optional[str] = None
    user_role: Optional[str] = None
    task_type: Optional[str] = None

    kitsu_host: Optional[str] = None
    kitsu_user: Optional[str] = None
    kitsu_pwd: Optional[str] = None
    kitsu_project_id: Optional[str] = None
    kitsu_entity_type: Optional[str] = None
    kitsu_entity_id: Optional[str] = None
    kitsu_entity_name: Optional[str] = None
    kitsu_sequence_id: Optional[str] = None
    kitsu_sequence_name: Optional[str] = None
    kitsu_task_type_id: Optional[str] = None
    kitsu_task_type_name: Optional[str] = None
    kitsu_asset_type_id: Optional[str] = None
    kitsu_asset_type_name: Optional[str] = None

    build_target: Optional[str] = None
    target_entity_id: Optional[str] = None
    target_sequence: Optional[str] = None

    svn_user: Optional[str] = None
    svn_password: Optional[str] = None

    blender_user_resources: Optional[str] = None
    blender_user_config: Optional[str] = None
    blender_user_scripts: Optional[str] = None

    def to_os_environ(self) -> Dict[str, str]:
        """Serialize populated fields to an ``os.environ``-style dict (str -> str)."""
        out: Dict[str, str] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue
            out[_FIELD_TO_KEY[f.name]] = str(value)
        return out

    @classmethod
    def from_os_environ(cls, environ: Optional[Dict[str, str]] = None) -> "SandboxEnvironment":
        """
        Parse a process environment back into a :class:`SandboxEnvironment`.
        Used by the Blender-side scripts (which only receive raw strings).
        """
        environ = environ if environ is not None else dict(os.environ)
        key_to_field = {v: k for k, v in _FIELD_TO_KEY.items()}
        kwargs: Dict[str, str] = {}
        for key, field_name in key_to_field.items():
            if key in environ:
                kwargs[field_name] = environ[key]
        return cls(**kwargs)
