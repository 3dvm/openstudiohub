import subprocess
from .vcs_base import AbstractVCSManager

class SVNManager(AbstractVCSManager):
    def commit(self, message: str, filepath: str) -> bool:
        # 1. Agregar todo lo nuevo en el workspace (el punto '.' significa directorio actual)
        # Esto atrapará la carpeta del .blend, el .blend mismo, y cualquier carpeta 'textures' generada.
        cmd_add = ["svn", "add", "--force", "."]
        try:
            subprocess.run(cmd_add, cwd=self.workspace_root, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            # Capturamos el error silenciosamente porque SVN a veces se queja si ya todo estaba agregado
            print(f"[SVN ADD ERROR] {e.stderr.decode('utf-8', errors='ignore')}")

        # 2. Ejecutar el Commit sobre TODO el workspace
        # Eliminamos 'filepath' de la lista para que SVN suba todos los cambios pendientes
        cmd_commit = [
            "svn", "commit", "-m", message,
            "--non-interactive", "--trust-server-cert",
            "--username", self.username, "--password", self.password, "--no-auth-cache"
        ]

        try:
            subprocess.run(cmd_commit, cwd=self.workspace_root, check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"[SVN ERROR] {e.stderr.decode('utf-8', errors='ignore')}")
            return False
