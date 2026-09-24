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
        self.lock_calls = []
        self.unlock_calls = []
        self.full_pull_calls = []
        self.pull_error = None
        self.lock_info = None

    def full_pull(self, username=None, password=None):
        self.full_pull_calls.append((username, password))
        if self.pull_error is not None:
            raise self.pull_error
        return True

    def get_status(self, path=None):
        return dict(self._status)

    def add(self, paths):
        self.add_calls.append(list(paths))
        return True

    def commit(self, message, paths=None, username=None, password=None):
        self.commit_calls.append((message, list(paths or []), username, password))
        return True

    def get_lock_info(self, path):
        return self.lock_info

    def lock(self, path, username=None, password=None):
        self.lock_calls.append((path, username, password))
        return True

    def unlock(self, path, username=None, password=None):
        self.unlock_calls.append((path, username, password))
        return True


class FakeRouter:
    adapter = None
    last = None

    def __init__(self, vcs_type, repo_url, workspace_dir, server_profile=None) -> None:
        self.vcs_type = vcs_type
        self.repo_url = repo_url
        self.workspace_dir = workspace_dir
        self.server_profile = server_profile
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


def test_lock_task_file_acquires_lock(tmp_path):
    service, adapter = _service(tmp_path, {})

    ok, message = service.lock_task_file(tmp_path / "p", "pro/a.blend", "artist", "secret")

    assert ok is True
    assert adapter.lock_calls == [("pro/a.blend", "artist", "secret")]


def test_lock_task_file_reports_foreign_owner(tmp_path):
    service, adapter = _service(tmp_path, {})
    adapter.lock_info = {"owner": "other@studio.com"}

    ok, message = service.lock_task_file(tmp_path / "p", "pro/a.blend", "artist", "secret")

    assert ok is False
    assert "locked by" in message.lower()
    assert adapter.lock_calls == []


def test_unlock_task_file_releases_lock(tmp_path):
    service, adapter = _service(tmp_path, {})

    ok, _ = service.unlock_task_file(tmp_path / "p", "pro/a.blend", "artist", "secret")

    assert ok is True
    assert adapter.unlock_calls == [("pro/a.blend", "artist", "secret")]


def test_update_working_copy_pulls_with_credentials(tmp_path):
    service, adapter = _service(tmp_path, {})

    ok, message = service.update_working_copy(tmp_path / "p", "artist", "secret")

    assert ok is True
    assert "updated" in message.lower()
    assert adapter.full_pull_calls == [("artist", "secret")]


def test_update_working_copy_rejected_when_vcs_disabled(tmp_path):
    service, adapter = _service(tmp_path, {}, vcs_type="none")

    ok, message = service.update_working_copy(tmp_path / "p", "artist", "secret")

    assert ok is False
    assert "disabled" in message.lower()
    assert adapter.full_pull_calls == []


def test_update_working_copy_surfaces_adapter_error(tmp_path):
    service, adapter = _service(tmp_path, {})
    adapter.pull_error = RuntimeError("SVN Failure: out of date")

    ok, message = service.update_working_copy(tmp_path / "p", "artist", "secret")

    assert ok is False
    assert "out of date" in message
