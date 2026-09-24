# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/config_factory.py
# Rol Arquitectónico: Configuration Manager & Crypto Engine (Bidirectional CRUD)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.9.0 (Encapsulation & Default Fallbacks)
# =========================================================================================

"""
Bidirectional parser and persistent CRUD engine for the settings.json file.
Manages atomic injection of NAS paths, API endpoints, and Semantic Topography.
Implements the B2B Provisioning Engine (Seed Generator/Importer) via zlib and base64.
Strictly encapsulates Fallback logic (Defaults) to keep UI components decoupled.
"""

import json
import platform
from dataclasses import replace
from pathlib import Path
from typing import Optional

from src.domain.workspace.topography import WorkspaceTopography
from src.domain.workspace.vcs_server import (
    VCSServer,
    VCSServerRegistry,
    reconcile_server_mode,
    slugify,
)
from src.domain.workspace.vcs_server_profile import (
    LOCAL_DOCKER,
    REMOTE_SSH,
    VCSServerProfile,
)
from src.infrastructure.seed_engine import StudioSeedService

# Portable vault folder name (resolved relative to each machine's workspace root).
DEFAULT_VAULT_DIR = "openstudio_vault"


class ConfigFactory:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._config = {}
        self._volatile_identity = {}  # Volatile RAM cache for Kitsu identity
        self._seed_service = StudioSeedService(self)
        self._load_config()
        self._migrate_machine_local_paths()

    def _load_config(self):
        """Reads and parses the master B2B file if it exists."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
            except Exception as e:
                print(f"[CONFIG FACTORY ERROR] Corrupted or unreadable file: {e}")
                self._config = {}
        else:
            self._config = {}

    def get_raw_config(self) -> dict:
        """Returns the full dictionary for unmapped queries."""
        return self._config

    # ---------------------------------------------------------
    # PROVISIONING ENGINE (STUDIO SEED)
    # ---------------------------------------------------------

    def export_seed(self, payload: dict, destino_dir: Path) -> tuple[bool, str]:
        """DEPRECATED: delegates to StudioSeedService."""
        return self._seed_service.export_seed(payload, destino_dir)

    def import_seed(self, seed_path: Path) -> bool:
        """DEPRECATED: delegates to StudioSeedService."""
        return self._seed_service.import_seed(seed_path)

    def purge_local_configuration(self) -> bool:
        """Destroys local settings.json returning the Hub to Day 0 state."""
        try:
            if self.config_path.exists():
                self.config_path.unlink()
            self._config = {}
            return True
        except Exception as e:
            print(f"[CONFIG FACTORY ERROR] Failed to purge configuration: {e}")
            return False

    # ---------------------------------------------------------
    # ATOMIC PERSISTENCE (CRUD ENGINE)
    # ---------------------------------------------------------

    def _persist(self) -> None:
        """Atomically write the in-memory config to disk and reload it."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=4, ensure_ascii=False)
        self._load_config()

    def save_configuration(self, datos_dict: dict, from_seed: bool = False) -> bool:
        """
        Public API: Receives a structured payload, injects semantic validations,
        and atomically writes data to disk.
        """
        if not datos_dict:
            return False

        if from_seed:
            # Machine-specific paths (absolute vault, SSH keys) never come from a seed.
            datos_dict = self._seed_service.sanitize_payload(datos_dict)

        try:
            # 1. Extraction and Normalization
            kitsu_url = datos_dict.get("kitsu_production", {}).get("api_url", "").strip()

            vcs_data = datos_dict.get("vcs_engine", {})
            vcs_sys = vcs_data.get("active_adapter", "").strip()
            vendor_sparse = bool(vcs_data.get("enable_vendor_sparse_checkout", True))
            repo_url = vcs_data.get("repository_url", "").strip()
            servers_payload = vcs_data.get("servers")
            default_server_id = (vcs_data.get("default_server_id") or "").strip()

            topo_data = datos_dict.get("project_topography", {})
            infra_data = datos_dict.get("infrastructure_topology", {})

            # 2. B2B Schema Scaffolding
            if "studio_profile" not in self._config: self._config["studio_profile"] = {}
            if "vcs_engine" not in self._config: self._config["vcs_engine"] = {}
            if "kitsu_production" not in self._config: self._config["kitsu_production"] = {}
            if "macuare_services" not in self._config: self._config["macuare_services"] = {}
            if "project_topography" not in self._config: self._config["project_topography"] = {}
            if "infrastructure_topology" not in self._config: self._config["infrastructure_topology"] = {}

            # 3. Semantic Validations & Injection
            if "local_workspace_root" not in self._config["vcs_engine"]:
                self._config["vcs_engine"]["local_workspace_root"] = {}

            # Multi-OS Mapping
            if "local_workspace_root" in vcs_data:
                self._config["vcs_engine"]["local_workspace_root"] = vcs_data["local_workspace_root"]

            if kitsu_url:
                self._config["kitsu_production"]["api_url"] = kitsu_url

            studio_name = datos_dict.get("studio_profile", {}).get("name", "").strip()
            if studio_name:
                self._config["studio_profile"]["name"] = studio_name

            # Topography Mapping
            if topo_data:
                self._config["project_topography"]["vfs_svn"] = topo_data.get("vfs_svn", "svn")
                self._config["project_topography"]["vfs_shared"] = topo_data.get("vfs_shared", "shared")
                self._config["project_topography"]["vfs_local"] = topo_data.get("vfs_local", "local")
                self._config["project_topography"]["vfs_pipeline"] = topo_data.get("vfs_pipeline", "pipeline")
                self._config["project_topography"]["custom_dirs"] = topo_data.get("custom_dirs", [])

            # Infrastructure & Vault Mapping
            if infra_data:
                self._apply_vault_payload(infra_data, from_seed)
                if "vcs_server" in infra_data:
                    profile = VCSServerProfile.from_dict(infra_data.get("vcs_server"))
                    self._config["infrastructure_topology"]["vcs_server"] = profile.to_dict()

            # Parametric Adapter Selection (legacy mirror keys)
            vcs_clean = vcs_sys.lower()
            legacy_adapter = "svn"
            if "svn" in vcs_clean and "git" in vcs_clean:
                legacy_adapter = "git-svn"
            elif "git" in vcs_clean:
                legacy_adapter = "git-lfs"
            elif "none" in vcs_clean:
                legacy_adapter = "none"

            # VCS server registry (multi-server). New payloads carry `servers`;
            # legacy payloads are folded into the default server for compatibility.
            if servers_payload is not None:
                registry = VCSServerRegistry.from_dict({
                    "servers": servers_payload,
                    "default_server_id": default_server_id,
                })
                registry = replace(
                    registry,
                    servers=tuple(reconcile_server_mode(s) for s in registry.servers),
                )
                self._config["vcs_engine"]["servers"] = [s.to_dict() for s in registry.servers]
                self._config["vcs_engine"]["default_server_id"] = registry.default_server_id
            elif vcs_sys or repo_url:
                self._merge_legacy_server(legacy_adapter, repo_url, vendor_sparse)

            # Keep the legacy single-server mirror in sync with the default server.
            self._sync_legacy_vcs_keys()

            if from_seed:
                # Fill local SSH defaults now that the (sanitized) servers exist.
                self._migrate_ssh_paths()

            # 4. Atomic Disk Write
            self._persist()
            return True

        except Exception as e:
            print(f"[CONFIG FACTORY ERROR] Critical error during atomic write: {e}")
            return False

    def set_local_workspace_root(self, path: Path) -> bool:
        """Persist the projects base folder for the CURRENT OS only (per-machine override)."""
        try:
            os_key = self._get_current_os()
            vcs = self._config.setdefault("vcs_engine", {})
            roots = vcs.setdefault("local_workspace_root", {})
            roots[os_key] = str(path)
            self._persist()
            return True
        except Exception as e:
            print(f"[CONFIG FACTORY ERROR] Failed to persist workspace root: {e}")
            return False

    # ---------------------------------------------------------
    # VOLATILE IDENTITY (SSO & B2B Branding)
    # ---------------------------------------------------------

    def set_volatile_studio_identity(self, identity_data: dict):
        self._volatile_identity = identity_data

    def get_studio_name(self) -> str:
        name = self._volatile_identity.get("name") or self._volatile_identity.get("studio_name")
        if name: return name
        return self._config.get("studio_profile", {}).get("name", "OPENSTUDIO HUB")

    def get_user_avatar_path(self) -> str | None:
        return self._volatile_identity.get("avatar_path")

    # ---------------------------------------------------------
    # SYSTEM ROUTING & TOPOGRAPHY GETTERS
    # ---------------------------------------------------------

    def _get_current_os(self) -> str:
        system = platform.system().lower()
        if system == "windows": return "windows"
        elif system == "darwin": return "macos"
        else: return "linux"

    def get_workspace_root(self) -> Path:
        """Returns the base projects directory. Implements Day-0 Fallbacks."""
        os_key = self._get_current_os()
        vcs_config = self._config.get("vcs_engine", {})
        roots = vcs_config.get("local_workspace_root", {})

        root_str = roots.get(os_key)
        if not root_str:
            # Fallback seguro en lugar de romper la app con ValueError
            return Path.home() / "openstudio_projects"

        return Path(root_str)

    def get_vault_path(self) -> Path:
        """
        Returns the absolute path to the Vault.

        The Vault is portable: it is resolved from the *local* workspace root.
        A machine-local absolute override (``vault_path``) is honoured when it
        exists on this machine; otherwise the portable ``vault_dir`` (default
        ``openstudio_vault``) is appended to the workspace root. This keeps
        seeds/devices independent of each other's home folders.
        """
        infra = self._config.get("infrastructure_topology", {})
        local_override = str(infra.get("vault_path") or "").strip()
        if local_override and Path(local_override).exists():
            return Path(local_override)

        vault_dir = str(infra.get("vault_dir") or "").strip() or DEFAULT_VAULT_DIR
        return self.get_workspace_root() / vault_dir

    def get_vault_dir(self) -> str:
        """Return the portable (relative) vault folder name."""
        return str(self._config.get("infrastructure_topology", {}).get("vault_dir") or "").strip() or DEFAULT_VAULT_DIR

    def set_vault_dir(self, vault_dir: str) -> bool:
        """Persist the portable vault folder name (relative to the workspace root)."""
        try:
            infra = self._config.setdefault("infrastructure_topology", {})
            infra["vault_dir"] = (vault_dir or "").strip() or DEFAULT_VAULT_DIR
            infra.pop("vault_path", None)
            self._persist()
            return True
        except Exception as e:
            print(f"[CONFIG FACTORY ERROR] Failed to persist vault dir: {e}")
            return False

    def _apply_vault_payload(self, infra_data: dict, from_seed: bool) -> None:
        """Normalize an incoming vault configuration to portable/local form."""
        infra = self._config.setdefault("infrastructure_topology", {})
        vault_dir = str(infra_data.get("vault_dir") or "").strip()
        vault_path = str(infra_data.get("vault_path") or "").strip()

        if vault_dir:
            infra["vault_dir"] = vault_dir
            infra.pop("vault_path", None)
            return

        # Never adopt a seed's machine-specific absolute path.
        if not vault_path or from_seed:
            return

        workspace = self.get_workspace_root()
        if self._is_under(Path(vault_path), workspace):
            infra["vault_dir"] = Path(vault_path).resolve().relative_to(workspace.resolve()).as_posix()
            infra.pop("vault_path", None)
        else:
            infra["vault_path"] = vault_path

    def portable_vault_config(self, vault_path: str) -> dict:
        """Return portable ``{"vault_dir": ...}`` when under the workspace, else a local override."""
        vault_path = str(vault_path or "").strip()
        if not vault_path:
            return {}
        workspace = self.get_workspace_root()
        if self._is_under(Path(vault_path), workspace):
            return {"vault_dir": Path(vault_path).resolve().relative_to(workspace.resolve()).as_posix()}
        return {"vault_path": vault_path}

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        try:
            Path(path).resolve().relative_to(Path(root).resolve())
            return True
        except (ValueError, OSError):
            return False

    def _migrate_machine_local_paths(self) -> None:
        """Convert machine-specific absolute paths into portable/local ones.

        Runs once at load; only persists when something actually changed.
        """
        changed = False

        infra = self._config.setdefault("infrastructure_topology", {})
        legacy_vault = str(infra.get("vault_path") or "").strip()
        if legacy_vault:
            workspace = self.get_workspace_root()
            default_vault = workspace / DEFAULT_VAULT_DIR
            if self._is_under(Path(legacy_vault), workspace):
                infra["vault_dir"] = Path(legacy_vault).resolve().relative_to(workspace.resolve()).as_posix()
                infra.pop("vault_path", None)
                changed = True
            elif not Path(legacy_vault).exists() and default_vault.exists():
                infra["vault_dir"] = DEFAULT_VAULT_DIR
                infra.pop("vault_path", None)
                changed = True

        changed = self._migrate_ssh_paths() or changed

        if changed:
            self._persist()

    def _migrate_ssh_paths(self) -> bool:
        """Reset machine-specific SSH paths that do not exist on this machine."""
        defaults = {
            "ssh_key_path": Path.home() / ".ssh" / "id_ed25519",
            "ssh_cert_path": None,
            "known_hosts_path": Path.home() / ".ssh" / "known_hosts",
        }
        changed = False

        for server in self.get_vcs_servers().servers:
            profile = server.profile
            remote = profile.remote
            updated = {}

            for field_name, default in defaults.items():
                current = str(getattr(remote, field_name) or "").strip()
                if current and Path(current).exists():
                    continue
                if current:
                    updated[field_name] = str(default) if default and Path(default).exists() else ""
                elif default and field_name == "ssh_key_path" and Path(default).exists():
                    updated[field_name] = str(default)

            if not updated:
                continue

            new_remote = replace(remote, **updated)
            new_profile = replace(profile, remote=new_remote)
            self._store_registry(self.get_vcs_servers().with_server(replace(server, profile=new_profile)))
            changed = True

        return changed

    # ---------------------------------------------------------
    # VCS SERVER REGISTRY (MULTI-SERVER)
    # ---------------------------------------------------------

    def _legacy_registry(self) -> VCSServerRegistry:
        """Build a registry from the pre-multi-server single-server config."""
        vcs = self._config.get("vcs_engine", {})
        profile_data = self._config.get("infrastructure_topology", {}).get("vcs_server")
        has_legacy = bool(
            vcs.get("active_adapter")
            or vcs.get("repository_url")
            or vcs.get("enable_vendor_sparse_checkout") is not None
            or profile_data
        )
        if not has_legacy:
            return VCSServerRegistry()

        profile = VCSServerProfile.from_dict(profile_data)
        server = reconcile_server_mode(VCSServer(
            id="default",
            name="Default",
            adapter=(vcs.get("active_adapter") or "svn"),
            repository_url=vcs.get("repository_url", ""),
            enable_vendor_sparse_checkout=bool(vcs.get("enable_vendor_sparse_checkout", True)),
            profile=profile,
        ))
        return VCSServerRegistry(servers=(server,), default_server_id="default")

    def get_vcs_servers(self) -> VCSServerRegistry:
        """Return the configured servers (synthesizing a legacy default if needed).

        The stored profile mode is reconciled against each repository URL so a
        server saved with a remote URL and the local default mode is treated as
        remote (the URL is what checkout uses).
        """
        vcs = self._config.get("vcs_engine", {})
        if "servers" in vcs:
            registry = VCSServerRegistry.from_dict(vcs)
            return replace(
                registry,
                servers=tuple(reconcile_server_mode(s) for s in registry.servers),
            )
        return self._legacy_registry()

    def _store_registry(self, registry: VCSServerRegistry) -> None:
        vcs = self._config.setdefault("vcs_engine", {})
        vcs["servers"] = [server.to_dict() for server in registry.servers]
        vcs["default_server_id"] = registry.default_server_id
        self._sync_legacy_vcs_keys()

    def _sync_legacy_vcs_keys(self) -> None:
        """Mirror the default server into the legacy single-server keys."""
        default = self.get_vcs_servers().default()
        vcs = self._config.setdefault("vcs_engine", {})
        vcs["active_adapter"] = default.adapter if default else "none"
        vcs["repository_url"] = default.repository_url if default else ""
        vcs["enable_vendor_sparse_checkout"] = (
            default.enable_vendor_sparse_checkout if default else True
        )

    def _merge_legacy_server(self, adapter: str, repo_url: str, vendor_sparse: bool) -> None:
        """Fold legacy payload keys into the default server entry."""
        registry = self.get_vcs_servers()
        current = registry.default()
        if current is None:
            server = VCSServer(
                id="default",
                name="Default",
                adapter=adapter or "svn",
                repository_url=repo_url,
                enable_vendor_sparse_checkout=vendor_sparse,
            )
        else:
            server = replace(
                current,
                adapter=adapter or current.adapter,
                repository_url=repo_url or current.repository_url,
                enable_vendor_sparse_checkout=vendor_sparse,
            )
        self._store_registry(registry.with_server(server))

    def get_server(self, server_id: str) -> Optional[VCSServer]:
        return self.get_vcs_servers().get(server_id)

    def get_default_server(self) -> Optional[VCSServer]:
        return self.get_vcs_servers().default()

    def get_server_for_project(self, project_root) -> Optional[VCSServer]:
        """Resolve the server a project is bound to (blueprint id -> URL -> default)."""
        registry = self.get_vcs_servers()
        try:
            project_root = Path(project_root)
            meta_files = list(project_root.glob("*/project_init.json"))
            if meta_files:
                data = json.loads(meta_files[0].read_text(encoding="utf-8"))
                server = registry.resolve(
                    data.get("vcs_server_id", ""),
                    data.get("vcs_base_url", ""),
                )
                if server:
                    return server
        except Exception as error:  # noqa: BLE001
            print(f"[CONFIG FACTORY] Projects server resolution fallback: {error}")
        return registry.default()

    def save_vcs_server(self, server_data: dict) -> bool:
        """Create or update a server entry, then persist."""
        try:
            server = reconcile_server_mode(VCSServer.from_dict(server_data))
            self._store_registry(self.get_vcs_servers().with_server(server))
            self._persist()
            return True
        except Exception as e:
            print(f"[CONFIG FACTORY ERROR] Failed to save VCS server: {e}")
            return False

    def remove_vcs_server(self, server_id: str) -> bool:
        try:
            self._store_registry(self.get_vcs_servers().without_server(server_id))
            self._persist()
            return True
        except Exception as e:
            print(f"[CONFIG FACTORY ERROR] Failed to remove VCS server: {e}")
            return False

    def set_default_server(self, server_id: str) -> bool:
        try:
            registry = self.get_vcs_servers()
            if registry.get(server_id) is None:
                return False
            self._store_registry(replace(registry, default_server_id=server_id))
            self._persist()
            return True
        except Exception as e:
            print(f"[CONFIG FACTORY ERROR] Failed to set default VCS server: {e}")
            return False

    def make_server_id(self, name: str) -> str:
        """Unique, human-readable slug for a new server name."""
        base = slugify(name)
        existing = {server.id for server in self.get_vcs_servers().servers}
        candidate = base
        index = 2
        while candidate in existing:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    # ---------------------------------------------------------
    # LEGACY SINGLE-SERVER SHIMS (delegate to the default server)
    # ---------------------------------------------------------

    def get_vcs_adapter_type(self) -> str:
        default = self.get_default_server()
        return default.adapter if default else "svn"

    def get_vcs_repository_url(self) -> str:
        default = self.get_default_server()
        return default.repository_url if default else ""

    def set_repository_url(self, url: str) -> bool:
        """Legacy shim: update the default server's repository URL."""
        default = self.get_default_server()
        if default is None:
            return False
        return self.save_vcs_server(replace(default, repository_url=(url or "").strip()).to_dict())

    def get_vcs_server_profile(self) -> VCSServerProfile:
        default = self.get_default_server()
        return default.profile if default else VCSServerProfile()

    def get_server_mode(self) -> str:
        return self.get_vcs_server_profile().mode

    def is_remote_server(self) -> bool:
        return self.get_vcs_server_profile().mode == REMOTE_SSH

    def set_vcs_server_profile(self, data: dict) -> bool:
        """Legacy shim: update the default server's admin topology."""
        default = self.get_default_server()
        profile = VCSServerProfile.from_dict(data)
        if default is None:
            return self.save_vcs_server(
                VCSServer(id="default", name="Default", profile=profile).to_dict()
            )
        return self.save_vcs_server(replace(default, profile=profile).to_dict())

    def is_vendor_sparse_enabled(self) -> bool:
        default = self.get_default_server()
        return default.enable_vendor_sparse_checkout if default else True

    def get_kitsu_api_url(self) -> str:
        return self._config.get("kitsu_production", {}).get("api_url", "")

    # --- TOPOGRAPHY ENGINE ---

    def get_topography(self) -> WorkspaceTopography:
        """Return the semantic VFS topography as a domain value object."""
        return WorkspaceTopography.from_dict(self._config.get("project_topography", {}))

    def get_vfs_svn_name(self) -> str:
        return self.get_topography().vfs_svn

    def get_vfs_shared_name(self) -> str:
        return self.get_topography().vfs_shared

    def get_vfs_local_name(self) -> str:
        return self.get_topography().vfs_local

    def get_vfs_pipeline_name(self) -> str:
        return self.get_topography().vfs_pipeline

    def get_custom_dirs(self) -> list:
        return list(self.get_topography().custom_dirs)

    def get_production_folder_name(self) -> str:
        """DEPRECATED ALIAS: Routes to get_vfs_svn_name() to prevent breaking legacy components."""
        return self.get_vfs_svn_name()
