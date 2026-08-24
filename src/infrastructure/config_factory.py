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
import base64
import zlib
from pathlib import Path

class ConfigFactory:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._config = {}
        self._volatile_identity = {}  # Volatile RAM cache for Kitsu identity
        self._load_config()

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

    def exportar_semilla(self, payload: dict, destino_dir: Path) -> tuple[bool, str]:
        """
        Packages, compresses, and obfuscates global configuration into a .seed file.
        Dynamically generates filename based on studio identity.
        """
        try:
            # 1. Dynamic Naming and Sanitization
            studio_name = payload.get("studio_profile", {}).get("name", "").strip()
            if not studio_name:
                studio_name = "openstudio"
            
            safe_name = "".join(c if c.isalnum() else "_" for c in studio_name).lower()
            
            import re
            safe_name = re.sub(r'_+', '_', safe_name).strip('_')
            
            seed_filename = f"{safe_name}.seed"
            seed_path = destino_dir / seed_filename

            # 2. Serialize and Obfuscate (JSON -> ZLIB -> BASE64)
            json_str = json.dumps(payload)
            compressed_bytes = zlib.compress(json_str.encode('utf-8'))
            encoded_str = base64.b64encode(compressed_bytes).decode('utf-8')

            # 3. Isolated Atomic Write
            with open(seed_path, 'w', encoding='utf-8') as f:
                f.write(encoded_str)

            return True, str(seed_path)
            
        except Exception as e:
            error_msg = f"Failed to export seed: {e}"
            print(f"[SEED ENGINE ERROR] {error_msg}")
            return False, error_msg

    def importar_semilla(self, seed_path: Path) -> bool:
        """
        Reads, decodes, and decompresses a .seed file, injecting it into local environment.
        This is the dispatcher called by the Login view on Day 0.
        """
        try:
            if not seed_path.exists():
                return False
            
            with open(seed_path, 'r', encoding='utf-8') as f:
                encoded_str = f.read()

            # Reverse Flow: BASE64 -> ZLIB -> JSON
            compressed_bytes = base64.b64decode(encoded_str)
            json_str = zlib.decompress(compressed_bytes).decode('utf-8')
            payload = json.loads(json_str)

            # Persist automatically using native CRUD
            return self.guardar_configuracion(payload, from_seed=True)
            
        except Exception as e:
            print(f"[SEED ENGINE ERROR] Integrity failure during seed import: {e}")
            return False

    def purgar_configuracion_local(self) -> bool:
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

    def guardar_configuracion(self, datos_dict: dict, from_seed: bool = False) -> bool:
        """
        Public API: Receives a structured payload, injects semantic validations,
        and atomically writes data to disk.
        """
        if not datos_dict:
            return False

        try:
            # 1. Extraction and Normalization
            kitsu_url = datos_dict.get("kitsu_production", {}).get("api_url", "").strip()
            
            vcs_data = datos_dict.get("vcs_engine", {})
            vcs_sys = vcs_data.get("active_adapter", "svn").strip()
            vendor_sparse = bool(vcs_data.get("enable_vendor_sparse_checkout", True))
            repo_url = vcs_data.get("repository_url", "").strip()
            
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
                self._config["infrastructure_topology"]["vault_path"] = infra_data.get("vault_path", "")

            # Parametric Adapter Selection
            vcs_clean = vcs_sys.lower()
            if "svn" in vcs_clean and "git" in vcs_clean:
                self._config["vcs_engine"]["active_adapter"] = "git-svn"
            elif "git" in vcs_clean:
                self._config["vcs_engine"]["active_adapter"] = "git-lfs"
            else:
                self._config["vcs_engine"]["active_adapter"] = "svn"

            self._config["vcs_engine"]["enable_vendor_sparse_checkout"] = vendor_sparse
            self._config["vcs_engine"]["repository_url"] = repo_url

            # 4. Atomic Disk Write
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=4, ensure_ascii=False)

            self._load_config()
            return True

        except Exception as e:
            print(f"[CONFIG FACTORY ERROR] Critical error during atomic write: {e}")
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
        elif system == "darwin": return "darwin"
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
        Calculates dynamic fallback based on workspace_root if unconfigured.
        """
        vault_str = self._config.get("infrastructure_topology", {}).get("vault_path", "")
        if vault_str:
            return Path(vault_str)
            
        # Fallback dinámico
        return self.get_workspace_root() / "openstudio_vault"

    def get_vcs_adapter_type(self) -> str:
        return self._config.get("vcs_engine", {}).get("active_adapter", "svn")

    def get_vcs_repository_url(self) -> str:
        return self._config.get("vcs_engine", {}).get("repository_url", "")

    def is_vendor_sparse_enabled(self) -> bool:
        return self._config.get("vcs_engine", {}).get("enable_vendor_sparse_checkout", True)

    def get_kitsu_api_url(self) -> str:
        return self._config.get("kitsu_production", {}).get("api_url", "")

    # --- TOPOGRAPHY ENGINE ---

    def get_vfs_svn_name(self) -> str:
        return self._config.get("project_topography", {}).get("vfs_svn", "svn")

    def get_vfs_shared_name(self) -> str:
        return self._config.get("project_topography", {}).get("vfs_shared", "shared")

    def get_vfs_local_name(self) -> str:
        return self._config.get("project_topography", {}).get("vfs_local", "local")

    def get_vfs_pipeline_name(self) -> str:
        return self._config.get("project_topography", {}).get("vfs_pipeline", "pipeline")

    def get_custom_dirs(self) -> list:
        return self._config.get("project_topography", {}).get("custom_dirs", [])

    def get_production_folder_name(self) -> str:
        """DEPRECATED ALIAS: Routes to get_vfs_svn_name() to prevent breaking legacy components."""
        return self.get_vfs_svn_name()
