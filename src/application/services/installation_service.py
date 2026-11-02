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

import hashlib
import json
import platform
import re
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.application.services.addon_config_generator import AddonConfigGenerator
from src.application.sparse_manager import SparseManager
from src.domain.vault.addon import AddonMetadata, parse_directory, parse_zip
from src.domain.vault.compatibility import CompatibilityPolicy
from src.domain.vault.integrity import slugify
from src.domain.workspace.blueprint import ProjectBlueprint
from src.infrastructure.sandbox.blender_locator import BlenderLocator
from src.infrastructure.vault_manifest_repository import FileVaultManifestRepository
from src.infrastructure.vcs.vcs_router import VCSRouter


class InstallationService:
    def __init__(self, config_factory, vault_root: Path, credential_vault=None) -> None:
        self.config_factory = config_factory
        self._vault_root = vault_root
        self.credential_vault = credential_vault

    @property
    def vault_root(self) -> Path:
        """Resolve the vault path dynamically so it follows config changes (seed import)."""
        getter = getattr(self.config_factory, "get_vault_path", None)
        if callable(getter):
            resolved = getter()
            if resolved is not None:
                return resolved
        return Path(self._vault_root)

    @property
    def boveda_addons(self) -> Path:
        return self.vault_root / "addons"

    @property
    def boveda_blender(self) -> Path:
        return self.vault_root / "blender_versions"

    @property
    def boveda_templates(self) -> Path:
        return self.vault_root / "project_templates"

    @staticmethod
    def _get_os_info() -> Tuple[str, str]:
        system = platform.system().lower()
        if system == "linux":
            return "linux", "tar.xz"
        if system == "windows":
            return "windows", "zip"
        return "macos", "dmg"

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def local_config_path(self, project_root: Path) -> Path:
        return (
            Path(project_root)
            / self.config_factory.get_vfs_local_name()
            / "project_config.json"
        )

    def load_local_config(self, project_root: Path) -> dict:
        return self._read_json(self.local_config_path(project_root))

    def load_project_blueprint(self, project_root: Path) -> dict:
        try:
            candidates = sorted(Path(project_root).glob("*/project_init.json"))
        except OSError:
            return {}
        for candidate in candidates:
            data = self._read_json(candidate)
            if data:
                return data
        return {}

    def workspace_needs_update(self, project_root: Path) -> bool:
        """True when project_init.json changed after the workspace was installed."""
        local = self.load_local_config(project_root)
        if not local:
            return False
        if bool(local.get("workspace_update_required")):
            return True

        blueprint = self.load_project_blueprint(project_root)
        if not blueprint:
            return False

        local_version = str(local.get("blender_version") or "")
        blueprint_version = str(blueprint.get("blender_version") or "")
        if local_version and blueprint_version and local_version != blueprint_version:
            return True
        return self.addons_need_update(project_root)

    def verify_installation(self, project_root: Path) -> bool:
        """Return True when the local workspace matches the project blueprint.

        A project is considered installed only when the local configuration
        exists, the VCS checkout is present, the workspace has no pending
        project_init.json changes, and the exact Blender version declared by
        the configuration is available. This prevents silently launching a
        stale workspace after the project version or components changed.
        """
        vfs_local = self.config_factory.get_vfs_local_name()
        vfs_svn = self.config_factory.get_vfs_svn_name()

        project_root = Path(project_root)
        config_local = project_root / vfs_local / "project_config.json"
        vcs_dir = project_root / vfs_svn
        if not (config_local.exists() and vcs_dir.exists()):
            return False

        if self.workspace_needs_update(project_root):
            return False

        local_config = self._read_json(config_local)
        version = str(local_config.get("blender_version") or "")
        if not version:
            version = str(self.load_project_blueprint(project_root).get("blender_version") or "")

        try:
            BlenderLocator.resolve(
                project_root / vfs_local / "blender-build",
                version=version or None,
            )
        except FileNotFoundError:
            return False
        return True

    def instalar_entorno(
        self,
        project_root: Path,
        vcs_user: str,
        vcs_pwd: str,
        status_callback,
        user_role: str = "artist",
        task_metadata: Optional[Dict[str, str]] = None,
        progress_callback=None,
    ) -> Tuple[bool, str]:
        progress = progress_callback or (lambda _percent: None)
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

            blueprint = ProjectBlueprint.from_dict(init_data)
            project_name = blueprint.project_name or project_root.name
            blender_version = blueprint.blender_version or "4.2.0"
            dependencies = blueprint.dependencies
            template_name = blueprint.template
            addon_configuration = blueprint.addon_configuration
            topography = blueprint.topography

            server = self._resolve_server(project_root)
            if server is not None:
                vcs_type = server.adapter
                profile = server.profile
                vcs_base_url = init_data.get("vcs_base_url") or server.repository_url
                sparse_enabled = server.enable_vendor_sparse_checkout
            else:
                vcs_type = self.config_factory.get_vcs_adapter_type()
                vcs_base_url = init_data.get("vcs_base_url") or self.config_factory.get_vcs_repository_url()
                profile = getattr(self.config_factory, "get_vcs_server_profile", lambda: None)()
                sparse_enabled = getattr(self.config_factory, "is_vendor_sparse_enabled", lambda: True)()

            progress(5)
            checkout_ok = self._gestionar_vcs(
                project_root, vfs_svn, vcs_user, vcs_pwd, status_callback, user_role, task_metadata,
                base_repo_url=vcs_base_url, vcs_type=vcs_type, profile=profile, sparse_enabled=sparse_enabled,
                server=server,
            )
            if not checkout_ok:
                return False, "VCS Synchronization aborted."
            progress(55)

            progress(58)
            self._instalar_blender(project_root, vfs_local, blender_version, status_callback)
            progress(78)

            if template_name:
                progress(80)
                self._instalar_template(project_root, vfs_local, template_name, blender_version, status_callback)
                progress(84)

            status_callback("Deploying project extensions...", "yellow")
            progress(86)
            self._sincronizar_addons(
                project_root, vfs_local, dependencies, status_callback, blender_version
            )
            progress(92)

            status_callback("Generating add-on startup configuration...", "yellow")
            progress(93)
            AddonConfigGenerator(self.config_factory).generate(
                project_root,
                addon_configuration,
                topography,
                status_callback=status_callback,
            )
            self._install_preferences_template(
                project_root, vfs_local, topography.vfs_pipeline, status_callback
            )
            progress(95)

            status_callback("Configuring production VFS symlinks...", "yellow")
            progress(96)
            self._crear_symlinks(project_path=project_root, vfs_svn=vfs_svn, vfs_shared=vfs_shared)

            status_callback("Generating local workspace configuration...", "yellow")
            progress(98)
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

            progress(100)
            return True, "Local workspace installed and verified successfully."

        except Exception as error:  # noqa: BLE001
            return False, f"Critical error during local installation: {str(error)}"

    def _resolve_server(self, project_root):
        getter = getattr(self.config_factory, "get_server_for_project", None)
        if not callable(getter):
            return None
        try:
            return getter(project_root)
        except Exception:  # noqa: BLE001
            return None

    def _gestionar_vcs(self, project_root, vfs_svn, vcs_user, vcs_pwd, status_callback, user_role, task_metadata, base_repo_url=None, vcs_type=None, profile=None, sparse_enabled=None, server=None) -> bool:
        vcs_root = project_root / vfs_svn
        if vcs_type is None:
            vcs_type = self.config_factory.get_vcs_adapter_type()

        if not base_repo_url:
            base_repo_url = self.config_factory.get_vcs_repository_url()
        final_repo_url = f"{base_repo_url}/{project_root.name}/{vfs_svn}"

        if profile is None:
            profile = getattr(self.config_factory, "get_vcs_server_profile", lambda: None)()
        provider = None
        if self.credential_vault is not None:
            server_id = server.id if server is not None else ""
            provider = lambda: self.credential_vault.get_ssh_passphrase(server_id)

        router = VCSRouter(
            vcs_type=vcs_type,
            repo_url=final_repo_url,
            workspace_dir=vcs_root,
            server_profile=profile,
            ssh_passphrase_provider=provider,
        )
        is_sparse_enabled = sparse_enabled
        if is_sparse_enabled is None:
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

    @staticmethod
    def _addon_name_keys(name: str) -> set[str]:
        normalized = slugify(name)
        return {
            key
            for key in (normalized, re.sub(r"[^a-z0-9]+", "", normalized))
            if key
        }

    @staticmethod
    def _zip_digest(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _vault_addon_entries(self, blender_version: str) -> Dict[str, dict]:
        manifest = FileVaultManifestRepository(self.vault_root).load()
        return manifest.get_addons(blender_version) or {}

    def _addon_zip_index(self) -> List[dict]:
        entries = []
        if self.boveda_addons.exists():
            for path in sorted(self.boveda_addons.rglob("*.zip")):
                meta = parse_zip(path)
                entries.append({"path": path, "meta": meta})
        return entries

    def _resolve_addon_zip(
        self,
        addon_name: str,
        addon_version: str,
        entry: Optional[dict],
        zip_index: List[dict],
        strict_version: bool,
    ) -> Tuple[Optional[Path], Optional[AddonMetadata]]:
        entry = entry or {}
        declared_path = entry.get("path")
        if declared_path:
            candidate = self.vault_root / str(declared_path)
            if candidate.exists():
                meta = parse_zip(candidate)
                if not strict_version or not addon_version or meta.version == str(addon_version):
                    return candidate, meta

        keys = self._addon_name_keys(addon_name)
        matches = []
        for item in zip_index:
            meta = item["meta"]
            if not meta.is_valid:
                continue
            if not (keys & self._addon_name_keys(meta.name)):
                continue
            if strict_version and addon_version and meta.version != str(addon_version):
                continue
            matches.append(item)
        if not matches:
            return None, None

        def rank(item):
            meta = item["meta"]
            exact = 0 if (addon_version and meta.version == str(addon_version)) else 1
            try:
                mtime = item["path"].stat().st_mtime
            except OSError:
                mtime = 0.0
            return (exact, -mtime)

        selected = sorted(matches, key=rank)[0]
        return selected["path"], selected["meta"]

    def _resolve_desired_addons(
        self, blender_version: str, dependencies: dict
    ) -> List[dict]:
        if isinstance(dependencies, str):
            try:
                dependencies = json.loads(dependencies)
            except Exception:
                dependencies = {}
        dependencies = dependencies or {}
        addons = dependencies.get("addons", {}) if isinstance(dependencies, dict) else {}
        manifest_addons = self._vault_addon_entries(blender_version)
        zip_index = self._addon_zip_index()

        manifest_by_key = {}
        for name, entry in manifest_addons.items():
            if isinstance(entry, dict):
                for key in self._addon_name_keys(name):
                    manifest_by_key.setdefault(key, (name, entry))

        desired = []
        for addon_name, dependency_version in (addons or {}).items():
            keys = self._addon_name_keys(addon_name)
            matched = next((manifest_by_key[key] for key in keys if key in manifest_by_key), None)
            entry = matched[1] if matched else None
            desired_version = str(entry.get("version") or dependency_version or "") if entry else str(dependency_version or "")
            zip_path, meta = self._resolve_addon_zip(
                addon_name,
                desired_version,
                entry,
                zip_index,
                strict_version=entry is not None,
            )

            error = ""
            if zip_path is None or meta is None or not meta.is_valid:
                error = (
                    f"declared version {desired_version or '?'} is not available in the vault"
                    if entry is not None
                    else "no compatible archive was found in the vault"
                )
            elif not CompatibilityPolicy.is_compatible(
                meta.min_blender_version, blender_version or "0.0.0"
            ):
                error = (
                    f"version {meta.version} requires Blender {meta.min_blender_version} "
                    f"(project uses {blender_version})"
                )

            desired.append(
                {
                    "name": str(addon_name),
                    "folder": slugify(addon_name),
                    "version": str(desired_version),
                    "zip": zip_path,
                    "meta": meta,
                    "error": error,
                    "declared_in_manifest": entry is not None,
                }
            )
        return desired

    def _installed_addon_metadata(self, destino: Path) -> AddonMetadata:
        if not destino.exists():
            return AddonMetadata()
        return parse_directory(destino)

    def _source_marker(self, destino: Path) -> Path:
        return destino / ".openstudio_addon_source.json"

    def _marker_digest(self, destino: Path) -> str:
        marker = self._source_marker(destino)
        if not marker.exists():
            return ""
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        return str(data.get("sha256", "") or "")

    def _install_addon_zip(
        self,
        zip_path: Path,
        destino: Path,
        expected_version: str,
        blender_version: str,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix=f".{destino.name}-", dir=str(destino.parent)
        ) as temp_dir:
            extract_root = Path(temp_dir) / "payload"
            extract_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_root)

            root = extract_root
            if not (root / "blender_manifest.toml").exists():
                manifests = list(root.rglob("blender_manifest.toml"))
                if len(manifests) != 1:
                    raise RuntimeError("archive does not contain a single add-on root")
                root = manifests[0].parent

            meta = parse_directory(root)
            if not meta.is_valid:
                raise RuntimeError("archive does not contain a valid blender_manifest.toml")
            if expected_version and meta.version != expected_version:
                raise RuntimeError(
                    f"archive version {meta.version} does not match manifest {expected_version}"
                )
            if not CompatibilityPolicy.is_compatible(meta.min_blender_version, blender_version):
                raise RuntimeError(
                    f"add-on requires Blender {meta.min_blender_version}, project uses {blender_version}"
                )

            if destino.exists():
                shutil.rmtree(destino)
            shutil.move(str(root), str(destino))
            self._source_marker(destino).write_text(
                json.dumps(
                    {
                        "source": zip_path.name,
                        "sha256": self._zip_digest(zip_path),
                        "version": meta.version,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    def addons_need_update(self, project_root: Path) -> bool:
        """True when a configured add-on is missing, stale, or not available."""
        project_root = Path(project_root)
        local = self.load_local_config(project_root)
        blueprint = self.load_project_blueprint(project_root)
        blender_version = str(
            local.get("blender_version") or blueprint.get("blender_version") or ""
        )
        dependencies = local.get("dependencies") or blueprint.get("dependencies") or {}
        if not blender_version or not dependencies:
            return False

        addons = dependencies.get("addons") if isinstance(dependencies, dict) else {}
        if not addons:
            return False

        vfs_local = str(
            local.get("vfs_local")
            or (blueprint.get("topography_signature") or {}).get("vfs_local")
            or getattr(self.config_factory, "get_vfs_local_name", lambda: "local")()
        )
        extensions = project_root / vfs_local / "blender_data" / "extensions" / "user_default"
        for item in self._resolve_desired_addons(blender_version, dependencies):
            destino = extensions / item["folder"]
            installed = self._installed_addon_metadata(destino)
            if item["error"]:
                return True
            if not installed.is_valid or installed.version != item["version"]:
                return True
            if item["zip"] is not None and self._marker_digest(destino) != self._zip_digest(item["zip"]):
                return True
        return False

    def _sincronizar_addons(
        self,
        project_root,
        vfs_local,
        dependencies,
        status_callback,
        blender_version: str = "",
    ):
        extensions_dir = project_root / vfs_local / "blender_data" / "extensions" / "user_default"
        extensions_dir.mkdir(parents=True, exist_ok=True)

        desired = self._resolve_desired_addons(blender_version, dependencies)
        for item in desired:
            addon_name = item["name"]
            version = item["version"]
            if item["error"]:
                status_callback(
                    f"Add-on '{addon_name}' skipped: {item['error']}.", "red"
                )
                continue

            zip_path = item["zip"]
            destino = extensions_dir / item["folder"]
            installed = self._installed_addon_metadata(destino)
            digest = self._zip_digest(zip_path)
            up_to_date = (
                installed.is_valid
                and installed.version == version
                and self._marker_digest(destino) == digest
            )
            if up_to_date:
                status_callback(
                    f"Add-on '{addon_name}' v{version} is up to date.", "green"
                )
                continue

            status_callback(
                f"Updating add-on '{addon_name}' to v{version}...", "yellow"
            )
            try:
                self._install_addon_zip(zip_path, destino, version, blender_version)
            except Exception as error:  # noqa: BLE001
                status_callback(
                    f"Could not update add-on '{addon_name}': {error}", "red"
                )
                continue
            status_callback(
                f"Add-on '{addon_name}' v{version} deployed.", "green"
            )

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

    def _install_preferences_template(
        self, project_root: Path, vfs_local: str, vfs_pipeline: str, status_callback
    ) -> None:
        """Seed a new local sandbox from the project's optional userpref template."""
        source = Path(project_root) / vfs_pipeline / "blender_preferences.blend"
        destination = (
            Path(project_root) / vfs_local / "blender_data" / "config" / "userpref.blend"
        )
        if not source.is_file() or destination.exists():
            return
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            status_callback("Blender preferences template installed.", "green")
        except OSError as error:
            status_callback(f"Could not install Blender preferences template: {error}", "red")

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
