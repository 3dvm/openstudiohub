import os
import re
import subprocess

from .vcs_base import AbstractVCSManager, VCSLockError

_OWNER_PATTERNS = (
    re.compile(r"already locked by user ['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"already locked by user (\S+)", re.IGNORECASE),
    re.compile(r"locked by user ['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"locked by user (\S+)", re.IGNORECASE),
)


def _lock_owner(stderr: str) -> str:
    for pattern in _OWNER_PATTERNS:
        match = pattern.search(stderr or "")
        if match:
            return match.group(1).strip()
    return ""


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


class SVNManager(AbstractVCSManager):
    def __init__(self, workspace_root: str, username: str, password: str, locale: str = ""):
        super().__init__(workspace_root, username, password)
        self.locale = str(locale or "").strip()

    def _env(self) -> dict:
        """Honor the configured SVN locale; inherit the process env when empty."""
        env = os.environ.copy()
        if self.locale:
            env["LC_ALL"] = self.locale
            env["LANG"] = self.locale
        return env

    def _auth_args(self) -> list:
        args: list = []
        if self.username:
            args.extend(["--username", self.username])
        args.extend(["--no-auth-cache", "--password-from-stdin"])
        return args

    def _run(self, args: list, *, check: bool = True):
        return subprocess.run(
            ["svn", *args],
            cwd=self.workspace_root,
            check=check,
            capture_output=True,
            input=self.password or "",
            text=True,
            env=self._env(),
        )

    def get_lock_info(self, filepath: str) -> dict:
        result = subprocess.run(
            ["svn", "info", filepath],
            cwd=self.workspace_root,
            capture_output=True,
            text=True,
            env=self._env(),
        )
        if result.returncode != 0:
            return {}
        info: dict = {}
        for line in (result.stdout or "").splitlines():
            key, separator, value = line.partition(":")
            if not separator:
                continue
            key = key.strip()
            value = value.strip()
            if key == "Lock Owner":
                info["owner"] = value
            elif key == "Lock Token":
                info["token"] = value
            elif key == "Lock Comment":
                info["comment"] = value
            elif key == "Lock Created":
                info["created"] = value
        return info

    def lock(self, filepath: str) -> bool:
        info = self.get_lock_info(filepath)
        owner = str((info or {}).get("owner", ""))
        if owner:
            if owner == self.username:
                return True
            raise VCSLockError(f"File is locked by '{owner}'.", owner=owner)

        result = self._run(
            [
                "lock",
                filepath,
                "--non-interactive",
                "--trust-server-cert",
                *self._auth_args(),
            ],
            check=False,
        )
        if result.returncode == 0:
            return True

        stderr = result.stderr or ""
        owner = _lock_owner(stderr)
        if ("W160035" in stderr or "E160039" in stderr) and owner == self.username:
            return True
        if owner:
            raise VCSLockError(f"File is locked by '{owner}'.", owner=owner)
        raise VCSLockError(
            f"Could not lock the file: {_first_line(stderr) or 'svn lock failed'}"
        )

    def commit(self, message: str, filepath: str) -> bool:
        # Track new files anywhere in the workspace. This catches the .blend,
        # newly generated textures and dependency folders.
        try:
            subprocess.run(
                ["svn", "add", "--force", "."],
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
                env=self._env(),
            )
        except subprocess.CalledProcessError as error:
            print(f"[SVN ADD ERROR] {error.stderr.decode('utf-8', errors='ignore')}")

        cmd = [
            "commit",
            "--encoding",
            "UTF-8",
            "-m",
            message,
            "--non-interactive",
            "--trust-server-cert",
            *self._auth_args(),
        ]
        result = self._run(cmd, check=False)
        if result.returncode == 0:
            return True
        print(f"[SVN ERROR] {result.stderr or ''}")
        return False
