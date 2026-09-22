"""Unit tests for the VCS task-file sync service."""

from pathlib import Path

from src.application.services.task_file_sync_service import TaskFileSyncService


class FakeConfig:
    def __init__(self, vcs_type: str = "svn", base_url: str = "svn://localhost/repos") -> None:
        self._vcs_type = vcs_type
        self._base_url = base_url

    def get_vcs_adapter_type(self) -> str:
        return self._vcs_type

    def get_vcs_repository_url(self) -> str:
        return self._base_url

    def get_vfs_svn_name(self) -> str:
        return "svn"


class FakeAdapter:
    def __init__(self, status: dict) -> None:
        self._status = status
        self.add_calls = []
        self.commit_calls = []

    def get_status(self, path=None):
        return dict(self._status)

    def add(self, paths):
        self.add_calls.append(list(paths))
        return True

    def commit(self, message, paths=None, username=None, password=None):
        self.commit_calls.append((message, list(paths or []), username, password))
        return True


class FakeRouter:
    adapter = None
    last = None

    def __init__(self, vcs_type, repo_url, workspace_dir) -> None:
        self.vcs_type = vcs_type
        self.repo_url = repo_url
        self.workspace_dir = workspace_dir
        FakeRouter.last = self

    def get_adapter(self):
        return FakeRouter.adapter


def _service(tmp_path: Path, status: dict, vcs_type: str = "svn"):
    adapter = FakeAdapter(status)
    FakeRouter.adapter = adapter
    config = FakeConfig(vcs_type=vcs_type)
    return TaskFileSyncService(config, router_factory=FakeRouter), adapter


def test_is_vcs_enabled_reflects_adapter_type():
    enabled = TaskFileSyncService(FakeConfig("svn"), router_factory=FakeRouter)
    disabled = TaskFileSyncService(FakeConfig("none"), router_factory=FakeRouter)
    empty = TaskFileSyncService(FakeConfig(""), router_factory=FakeRouter)

    assert enabled.is_vcs_enabled() is True
    assert disabled.is_vcs_enabled() is False
    assert empty.is_vcs_enabled() is False


def test_scan_filters_junk_and_orders_blend_first(tmp_path):
    status = {
        "pro/assets/monkey/monkey-model.blend": "M",
        "pro/assets/monkey/monkey-model.blend1": "?",
        "pro/assets/monkey/__pycache__/cache.pyc": "?",
        "pro/assets/monkey/readme.txt": "M",
        "pro/assets/monkey/tex/new.png": "?",
    }
    service, _ = _service(tmp_path, status)

    changes = service.scan_local_changes(tmp_path / "my-project")

    assert [c.relative_path for c in changes] == [
        "pro/assets/monkey/monkey-model.blend",
        "pro/assets/monkey/readme.txt",
        "pro/assets/monkey/tex/new.png",
    ]
    assert changes[2].is_unversioned is True


def test_scan_builds_repo_url_and_workspace(tmp_path):
    service, _ = _service(tmp_path, {})
    project_root = tmp_path / "My_Project"

    service.scan_local_changes(project_root)

    assert FakeRouter.last.vcs_type == "svn"
    assert FakeRouter.last.repo_url == "svn://localhost/repos/My_Project/svn"
    assert FakeRouter.last.workspace_dir == project_root / "svn"


def test_scan_returns_empty_when_vcs_disabled(tmp_path):
    service, adapter = _service(tmp_path, {"pro/a.blend": "M"}, vcs_type="none")

    assert service.scan_local_changes(tmp_path / "p") == []
    assert adapter.add_calls == []


def test_publish_adds_unversioned_then_commits(tmp_path):
    service, adapter = _service(tmp_path, {})
    project_root = tmp_path / "My_Project"

    ok, message = service.publish(
        project_root=project_root,
        selected_paths=["pro/a.blend", "pro/tex/new.png"],
        unversioned_paths=["pro/tex/new.png"],
        username="artist",
        password="secret",
        message="Publish from session.",
    )

    assert ok is True
    assert "Published 2 file(s)" in message
    assert adapter.add_calls == [["pro/tex/new.png"]]
    assert adapter.commit_calls == [
        ("Publish from session.", ["pro/a.blend", "pro/tex/new.png"], "artist", "secret")
    ]


def test_publish_without_selection_is_rejected(tmp_path):
    service, adapter = _service(tmp_path, {})

    ok, message = service.publish(project_root=tmp_path / "p", selected_paths=[])

    assert ok is False
    assert "No files selected" in message
    assert adapter.commit_calls == []
