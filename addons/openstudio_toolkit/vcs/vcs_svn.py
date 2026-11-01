import subprocess

from .vcs_base import AbstractVCSManager


class SVNManager(AbstractVCSManager):
    def commit(self, message: str, filepath: str) -> bool:
        # Track new files anywhere in the workspace. This catches the .blend,
        # newly generated textures and dependency folders.
        try:
            subprocess.run(
                ["svn", "add", "--force", "."],
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as error:
            print(f"[SVN ADD ERROR] {error.stderr.decode('utf-8', errors='ignore')}")

        cmd = [
            "svn",
            "commit",
            "-m",
            message,
            "--non-interactive",
            "--trust-server-cert",
            "--username",
            self.username,
            "--no-auth-cache",
            "--password-from-stdin",
        ]

        try:
            subprocess.run(
                cmd,
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
                input=self.password or "",
                text=True,
            )
            return True
        except subprocess.CalledProcessError as error:
            stderr = error.stderr.decode("utf-8", errors="ignore") if isinstance(error.stderr, bytes) else (error.stderr or "")
            print(f"[SVN ERROR] {stderr}")
            return False
