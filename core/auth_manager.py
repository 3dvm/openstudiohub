# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/auth_manager.py
# Rol Arquitectónico: Adapter / API Gateway (Gazu/Kitsu)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.7.0
# =========================================================================================

"""
Manages authentication, role resolution (RBAC), and the extraction
of studio and user metadata. Anchored to English standard.
"""

import json
import gazu
from pathlib import Path
from typing import Tuple, Dict, List, Optional

OPENSTUDIO_CONFIG_DIR = Path.home() / ".openstudio"
SESSION_FILE = OPENSTUDIO_CONFIG_DIR / "session.json"

class AuthManager:
    def __init__(self):
        self.kitsu_host = None
        self.user_data = None
        
        if not OPENSTUDIO_CONFIG_DIR.exists():
            OPENSTUDIO_CONFIG_DIR.mkdir(parents=True)

    def set_host(self, host_url: str) -> None:
        if not host_url.endswith("/api"):
            host_url = f"{host_url.rstrip('/')}/api"
        self.kitsu_host = host_url
        gazu.client.set_host(self.kitsu_host)

    def login_with_credentials(self, email: str, password: str, host_url: str) -> Tuple[bool, str]:
        try:
            self.set_host(host_url)
            tokens = gazu.log_in(email, password)
            self.user_data = gazu.client.get_current_user()
            self._save_session(tokens)
            return True, "Login successful."
        except gazu.exception.AuthFailedException:
            return False, "Invalid credentials."
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    def login_with_saved_session(self) -> bool:
        if not SESSION_FILE.exists():
            return False
        try:
            with open(SESSION_FILE, 'r') as f:
                data = json.load(f)
            self.set_host(data["host"])
            gazu.client.set_tokens(data["tokens"])
            self.user_data = gazu.client.get_current_user()
            return True
        except Exception:
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()
            return False

    def logout(self) -> None:
        gazu.log_out()
        self.user_data = None
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()

    def get_user_role(self) -> str:
        if not self.user_data:
            return "guest"
        kitsu_role = self.user_data.get("role", "").lower()
        kitsu_position = self.user_data.get("position", "").lower()
        
        if kitsu_role == "admin": return "td"
        elif kitsu_role == "supervisor": return "supervisor"
        elif kitsu_role == "manager": return "manager"
        elif kitsu_role == "vendor": return "vendor"
        elif kitsu_role == "client": return "client"
        elif kitsu_role == "user":
            if kitsu_position == "lead": return "lead"
            return "artist"
        return "artist"

    def get_user_position(self) -> str:
        if not self.user_data: return ""
        return self.user_data.get("position", "").lower()

    def get_current_token(self) -> str:
        if hasattr(gazu.client, "tokens") and isinstance(gazu.client.tokens, dict):
            return gazu.client.tokens.get("access_token", "")
            
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE, 'r') as f:
                    data = json.load(f)
                return data.get("tokens", {}).get("access_token", "")
            except Exception:
                pass
        return ""

    def _save_session(self, tokens) -> None:
        data = {"host": self.kitsu_host, "tokens": tokens}
        with open(SESSION_FILE, 'w') as f:
            json.dump(data, f)

    # =========================================================================
    # KITSU API ENDPOINTS (SSoT)
    # =========================================================================

    def sync_studio_identity(self) -> dict:
        """
        Dynamically downloads the main studio identity from Kitsu.
        Designed to be explicitly triggered by the TD via the Settings Panel.
        """
        identity = {}
        try:
            org = gazu.person.get_organisation()
            if isinstance(org, dict) and "name" in org:
                identity["name"] = org["name"]
        except Exception as e:
            print(f"[AuthManager] Info: Failed to fetch Organisation from server ({e})")
            
        return identity

    def obtener_proyectos_activos(self) -> Dict[str, str]:
        proyectos = {}
        try:
            for p in gazu.project.all_open_projects():
                proyectos[p["name"].lower()] = p["id"]
        except Exception as e:
            print(f"[AuthManager] Error fetching active projects: {e}")
        return proyectos

    def get_task_metadata(self, task_id: str) -> Optional[Dict[str, str]]:
        try:
            return gazu.task.get_task(task_id)
        except Exception:
            return None

    def get_assigned_tasks(self) -> List[dict]:
        try:
            return gazu.user.all_tasks_to_do()
        except Exception as e:
            print(f"[AuthManager] Error fetching assigned tasks: {e}")
            return []

    def get_recent_activity(self, limit: int=15) -> List[dict]:
        return []

    def acknowledge_activity(self, task_id: str, comment_id: str) -> bool:
        return True
