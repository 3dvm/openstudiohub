# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/addon_config_generator.py
# Architectural role: Application service / add-on startup script generation
# =========================================================================================

"""Generates one ``cfg_<addon>.py`` config script per active add-on.

The generator is add-on agnostic: it resolves a template by convention
(``templates/addons/cfg_<addon>.py.template``), injects the project's
``AddonConfiguration`` payload, and writes the result into the project's Blender
user-scripts *config* folder (``blender_data/scripts/openstudio/``).

The folder is deliberately **not** ``scripts/startup/``: Blender imports every
module found in ``startup/`` and calls its ``register()`` before the extension
repositories (``bl_ext``/``bl_pkg``) are initialized, which made add-on
activation fail. These scripts are loaded at a controlled moment instead, via
``addon_runtime``. The template is the only place where add-on specifics live;
adding a new configurable add-on means dropping a new template, never touching
this service.
"""

import shutil
from pathlib import Path
from typing import List, Mapping, Optional

from src.domain.shared_kernel.addon_contract import (
    AddonConfiguration,
    parse_addon_configuration,
    slugify_addon_name,
)
from src.domain.workspace.topography import WorkspaceTopography

ADDON_CONFIG_TOKEN = "__ADDON_CONFIG_JSON__"


class AddonConfigGenerator:
    def __init__(self, config_factory=None, template_dir: Optional[Path] = None) -> None:
        self.config_factory = config_factory
        self._template_dir = Path(template_dir) if template_dir else None

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    @property
    def template_dir(self) -> Path:
        if self._template_dir is not None:
            return self._template_dir
        src_root = Path(__file__).resolve().parent.parent.parent  # -> src/
        return src_root / "infrastructure" / "templates" / "addons"

    @staticmethod
    def config_dir(project_root: Path, topography: WorkspaceTopography) -> Path:
        """Directory holding the generated scripts.

        Kept under ``scripts/`` (so ``parents[3]`` still resolves to
        ``vfs_local`` and ``env_contract`` stays importable) but out of
        ``startup/``/``modules/`` so Blender does not auto-import them.
        """
        return (
            Path(project_root)
            / topography.vfs_local
            / "blender_data"
            / "scripts"
            / "openstudio"
        )

    @staticmethod
    def legacy_startup_dir(project_root: Path, topography: WorkspaceTopography) -> Path:
        return (
            Path(project_root)
            / topography.vfs_local
            / "blender_data"
            / "scripts"
            / "startup"
        )

    @staticmethod
    def _safe_name(addon_name: str) -> str:
        return slugify_addon_name(addon_name)

    def _resolve_template(self, addon_name: str) -> Optional[Path]:
        candidate = self.template_dir / f"cfg_{self._safe_name(addon_name)}.py.template"
        return candidate if candidate.exists() else None

    def _deploy_support_modules(self, project_root: Path, topography: WorkspaceTopography) -> None:
        """Ship the DCC-side support modules next to ``bootstrap.py``.

        The generated scripts import ``env_contract`` at runtime, and
        ``bootstrap``/``headless_builder`` import ``addon_runtime``. Deploying
        them at install time (not only at launch) keeps headless-only flows
        working for projects never opened interactively.
        """
        src_root = self.template_dir.parents[2]  # addons -> templates -> infrastructure -> src
        support_files = {
            src_root / "domain" / "shared_kernel" / "env_contract.py": "env_contract.py",
            self.template_dir.parent / "addon_runtime.py": "addon_runtime.py",
        }
        destination_dir = Path(project_root) / topography.vfs_local
        destination_dir.mkdir(parents=True, exist_ok=True)
        for source, target_name in support_files.items():
            if source.exists():
                shutil.copy2(source, destination_dir / target_name)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(
        self,
        project_root: Path,
        addon_configuration: Optional[Mapping[str, AddonConfiguration]],
        topography: WorkspaceTopography,
        status_callback=None,
    ) -> List[Path]:
        """Write a ``cfg_<addon>.py`` script for every enabled add-on.

        Disabled add-ons have their previously generated script removed so a
        project downgrade does not leave stale behavior behind.
        """
        configs = parse_addon_configuration(addon_configuration or {})
        config_dir = self.config_dir(project_root, topography)
        generated: List[Path] = []

        # Migration: Blender auto-registers scripts in `startup/`, which ran
        # add-on activation before the extension system was ready. Drop any
        # legacy scripts the Hub generated there.
        self._remove_legacy_startup_scripts(project_root, topography)

        if configs:
            self._deploy_support_modules(project_root, topography)

        for addon_name, config in configs.items():
            if not config.enabled:
                self.remove(project_root, topography, addon_name)
                continue

            template = self._resolve_template(addon_name)
            if template is None:
                if status_callback:
                    status_callback(
                        f"Addon '{addon_name}' has no config template; skipping.", "white"
                    )
                continue

            config_dir.mkdir(parents=True, exist_ok=True)
            # Python literal (not JSON) so the generated module is directly valid
            # Python: JSON uses true/false/null which are not Python names.
            payload = repr(config.to_dict())
            rendered = template.read_text(encoding="utf-8").replace(ADDON_CONFIG_TOKEN, payload)

            destination = config_dir / f"cfg_{self._safe_name(addon_name)}.py"
            destination.write_text(rendered, encoding="utf-8")
            generated.append(destination)

            if status_callback:
                status_callback(f"Generated add-on config: {destination.name}", "green")

        return generated

    def remove(self, project_root: Path, topography: WorkspaceTopography, addon_name: str) -> None:
        script_name = f"cfg_{self._safe_name(addon_name)}.py"
        for directory in (
            self.config_dir(project_root, topography),
            self.legacy_startup_dir(project_root, topography),
        ):
            destination = directory / script_name
            if destination.exists():
                destination.unlink()

    def _remove_legacy_startup_scripts(self, project_root: Path, topography: WorkspaceTopography) -> None:
        """Delete Hub-generated ``cfg_*.py`` left in ``scripts/startup/``.

        Blender auto-imports and registers those modules before the extension
        repositories exist, so they must not live there anymore.
        """
        legacy_dir = self.legacy_startup_dir(project_root, topography)
        if not legacy_dir.exists():
            return
        for legacy_script in legacy_dir.glob("cfg_*.py"):
            legacy_script.unlink()
        # Drop stale bytecode so Blender cannot resurrect a removed module.
        cache_dir = legacy_dir / "__pycache__"
        if cache_dir.is_dir():
            for cached in cache_dir.glob("cfg_*.pyc"):
                cached.unlink()
