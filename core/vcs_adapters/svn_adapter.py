# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/vcs_adapters/svn_adapter.py
# Rol Arquitectónico: Adaptador VCS / Capa de Abstracción
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.5.0
# =========================================================================================

"""
Concrete adapter for Subversion (SVN) operations via CLI.
Implements the Sparse Checkout mechanism to orchestrate Vendor Jailing.
Anchored to English standard.
"""

import subprocess
from typing import List, Dict, Optional
from pathlib import Path
from .abstract_vcs import AbstractVCS

class SVNAdapter(AbstractVCS):
    """Concrete adapter for Subversion (SVN) operations via CLI."""

    def _build_auth_args(self, username: Optional[str], password: Optional[str]) -> List[str]:
        """Builds authentication arguments without caching them on disk."""
        args = ["--non-interactive", "--trust-server-cert"]

        # =========================================================
        # BYPASS TEMPORAL: Forzar credenciales Dummy en Localhost
        # =========================================================
        if "localhost" in self.repo_url:
            username = "admin"
            password = "admin123"
            print("[SVNAdapter] BYPASS: Inyectando credenciales locales de SVN (admin)...")
        # =========================================================

        if username and password:
            args.extend(["--username", username, "--password", password, "--no-auth-cache"])
        return args

    def _run_subprocess(self, cmd: List[str], cwd: Optional[Path] = None) -> str:
        """Secure wrapper to execute subprocesses and capture errors."""
        cwd_path = str(cwd) if cwd else None
        
        # === DEBUG MODE: Security mask to avoid printing the password in the console ===
        safe_cmd = []
        skip_next = False
        for token in cmd:
            if skip_next:
                safe_cmd.append("********")
                skip_next = False
            elif token == "--password":
                safe_cmd.append(token)
                skip_next = True
            else:
                safe_cmd.append(token)
                
        print(f"\n[SVN DEBUG] Executing (CWD: {cwd_path or 'Current'}):")
        print(f" -> {' '.join(safe_cmd)}")
        # ==============================================================================

        try:
            result = subprocess.run(
                cmd, 
                cwd=cwd_path, 
                check=True, 
                capture_output=True, 
                text=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            # Captures the real stderr from SVN (e.g., Incorrect Password) to pass it to the UI/Console
            error_msg = e.stderr.strip() if e.stderr else str(e)
            print(f"[SVN FATAL ERROR] Code {e.returncode}: {error_msg}\n")
            raise RuntimeError(f"SVN Failure: {error_msg}")

    def full_pull(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        # If the folder already exists and is an SVN repo, perform an update
        if (self.workspace_dir / ".svn").exists():
            cmd = ["svn", "update"]
            cmd.extend(self._build_auth_args(username, password))
            self._run_subprocess(cmd, cwd=self.workspace_dir)
        else:
            # Otherwise, perform a full checkout
            cmd = ["svn", "checkout", self.repo_url, str(self.workspace_dir)]
            cmd.extend(self._build_auth_args(username, password))
            self._run_subprocess(cmd)
        return True

    def sparse_pull(self, paths: List[str], username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Restrictive download (Jailing) for Vendors."""
        # 1. Empty checkout (Fetches only structure, no files)
        if not (self.workspace_dir / ".svn").exists():
            cmd_co = ["svn", "checkout", "--depth", "empty", self.repo_url, str(self.workspace_dir)]
            cmd_co.extend(self._build_auth_args(username, password))
            self._run_subprocess(cmd_co)
        
        # 2. Download only the approved directories in the paths list
        for path in paths:
            # FIX: Added the --parents flag to build the mandatory empty hierarchy
            cmd_up = ["svn", "update", "--set-depth", "infinity", "--parents", path]
            cmd_up.extend(self._build_auth_args(username, password))
            self._run_subprocess(cmd_up, cwd=self.workspace_dir)
            
        return True

    def commit(self, message: str, paths: Optional[List[str]] = None, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        cmd = ["svn", "commit", "-m", message]
        if paths:
            cmd.extend(paths)
        cmd.extend(self._build_auth_args(username, password))
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def lock(self, path: str, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        cmd = ["svn", "lock", path]
        cmd.extend(self._build_auth_args(username, password))
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def unlock(self, path: str, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        cmd = ["svn", "unlock", path]
        cmd.extend(self._build_auth_args(username, password))
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def revert(self, path: str) -> bool:
        cmd = ["svn", "revert", "-R", path]
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def get_status(self) -> Dict[str, str]:
        cmd = ["svn", "status"]
        output = self._run_subprocess(cmd, cwd=self.workspace_dir)
        # Raw parsing to return dict: {'A': 'path/file.blend', 'M': 'path/other.blend'}
        status_dict = {}
        for line in output.splitlines():
            if len(line) > 8:
                state = line[0]
                file_path = line[8:].strip()
                status_dict[file_path] = state
        return status_dict

    def set_needs_lock(self, path: str) -> bool:
        """
        Applies the svn:needs-lock property to the specified file.
        Forces the VCS to keep the file in 'Read-Only' mode until an authorized user locks it.
        """
        cmd = ["svn", "propset", "svn:needs-lock", "*", path]
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def cleanup(self) -> bool:
        """
        Sanitizes the local internal VCS database to resolve local locks
        caused by abrupt power outages, network drops, or forced closures.
        """
        if self.workspace_dir.exists():
            cmd = ["svn", "cleanup"]
            self._run_subprocess(cmd, cwd=self.workspace_dir)
            return True
        return False

    def setup_ignore(self, patterns: List[str]) -> bool:
        """Aplica la propiedad svn:ignore sobre la raíz del workspace."""
        if not (self.workspace_dir / ".svn").exists():
            return False
            
        # Escribimos un archivo temporal con los patrones
        ignore_file = self.workspace_dir / ".svn_ignore_temp"
        with open(ignore_file, "w", encoding="utf-8") as f:
            f.write("\n".join(patterns) + "\n")
        
        # Aplicamos la propiedad de SVN leyendo el archivo
        cmd = ["svn", "propset", "svn:ignore", "-F", str(ignore_file), "."]
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        
        # Limpieza del temporal
        ignore_file.unlink(missing_ok=True)
        return True

    def add_all(self, path: str = ".") -> bool:
        """Registra archivos forzando la recursividad, ignorando los no-versionados por regla."""
        cmd = ["svn", "add", "--force", path]
        self._run_subprocess(cmd, cwd=self.workspace_dir)
        return True

    def create_server_repository(self, project_name: str, vfs_svn: str) -> bool:
        """Crea el repositorio SVN en el servidor (Soporta Docker local para desarrollo)."""
        if "localhost" not in self.repo_url:
            # Hay que implementar la creación del repositorio en servers remotos con SSH.
            print("[SVNAdapter] Remote repository detected, assuming that the repository already exists.")
            return True # Si es un server real, asumimos que el admin ya creó el repo o se hace vía API
            
        try:
            import subprocess
            # Creación del repositorio en el contenedor Docker
            subprocess.run(["docker", "exec", "openstudio_local_svn", "svnadmin", "create", f"/home/svn/{project_name}"], check=True, capture_output=True)
            
            # Configuración de permisos
            conf_cmd = (
                f"echo '[general]' > /home/svn/{project_name}/conf/svnserve.conf && "
                f"echo 'anon-access = none' >> /home/svn/{project_name}/conf/svnserve.conf && "
                f"echo 'auth-access = write' >> /home/svn/{project_name}/conf/svnserve.conf && "
                f"echo 'password-db = passwd' >> /home/svn/{project_name}/conf/svnserve.conf"
            )
            subprocess.run(["docker", "exec", "openstudio_local_svn", "sh", "-c", conf_cmd], check=True, capture_output=True)
            
            # Creación del usuario admin default para localhost
            pwd_cmd = f"echo '[users]' > /home/svn/{project_name}/conf/passwd && echo 'admin = admin123' >> /home/svn/{project_name}/conf/passwd"
            subprocess.run(["docker", "exec", "openstudio_local_svn", "sh", "-c", pwd_cmd], check=True, capture_output=True)
            
            # Inyección de la topología VFS base
            mkdir_cmd = f"svn mkdir file:///home/svn/{project_name}/{vfs_svn} -m 'Init Hub Topology'"
            subprocess.run(["docker", "exec", "openstudio_local_svn", "sh", "-c", mkdir_cmd], check=True, capture_output=True)
            
            print(f"[SVNAdapter] ✓ Local repository '{project_name}' created succesfully on Docker.")
            return True
        except Exception as e:
            print(f"[SVNAdapter] WARNING: Failed to configure SVN Docker: {e}")
            return False
