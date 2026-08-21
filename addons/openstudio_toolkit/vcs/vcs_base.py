class AbstractVCSManager:
    def __init__(self, workspace_root: str, username: str, password: str):
        self.workspace_root = workspace_root
        self.username = username
        self.password = password

    def commit(self, message: str, filepath: str) -> bool:
        raise NotImplementedError

    def update(self) -> bool:
        raise NotImplementedError
