class VCSLockError(RuntimeError):
    """Raised when a file cannot be locked for editing."""

    def __init__(self, message: str, owner: str = "") -> None:
        super().__init__(message)
        self.owner = owner


class AbstractVCSManager:
    def __init__(self, workspace_root: str, username: str, password: str):
        self.workspace_root = workspace_root
        self.username = username
        self.password = password

    def commit(self, message: str, filepath: str) -> bool:
        raise NotImplementedError

    def update(self) -> bool:
        raise NotImplementedError

    def get_lock_info(self, filepath: str) -> dict:
        raise NotImplementedError

    def lock(self, filepath: str) -> bool:
        raise NotImplementedError
