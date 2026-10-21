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
        self.lock_error = None
        self.entries = None
        self.resolve_calls = []
        self.resolve_error = None
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

    def get_status_entries(self):
        return self.entries

    def resolve(self, path, accept="working"):
        self.resolve_calls.append((path, accept))
        if self.resolve_error is not None:
            raise self.resolve_error
        return True

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
        if self.lock_error is not None:
            raise self.lock_error
        return True

    def unlock(self, path, username=None, password=None, force=False):
        self.unlock_calls.append((path, username, password, force))
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
    assert adapter.unlock_calls == [("pro/a.blend", "artist", "secret", False)]


def test_get_task_file_lock_returns_owner(tmp_path):
    service, adapter = _service(tmp_path, {})
    adapter.lock_info = {"owner": "ana@studio.com", "token": "opaquelocktoken:abc"}

    info = service.get_task_file_lock(tmp_path / "p", "pro/a.blend")

    assert info["owner"] == "ana@studio.com"


def test_get_task_file_lock_returns_none_when_unlocked(tmp_path):
    service, _ = _service(tmp_path, {})

    assert service.get_task_file_lock(tmp_path / "p", "pro/a.blend") is None


def test_get_task_file_lock_returns_none_when_vcs_disabled(tmp_path):
    service, adapter = _service(tmp_path, {}, vcs_type="none")
    adapter.lock_info = {"owner": "ana@studio.com"}

    assert service.get_task_file_lock(tmp_path / "p", "pro/a.blend") is None


def test_get_task_file_lock_returns_none_without_path(tmp_path):
    service, adapter = _service(tmp_path, {})
    adapter.lock_info = {"owner": "ana@studio.com"}

    assert service.get_task_file_lock(tmp_path / "p", "") is None


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


def test_lock_task_file_accepts_stale_lock_from_same_user(tmp_path):
    from src.infrastructure.vcs.svn_errors import SvnAlreadyLockedError

    service, adapter = _service(tmp_path, {})
    adapter.lock_error = SvnAlreadyLockedError(
        "already locked", owner="artist", path="pro/a.blend"
    )

    ok, message = service.lock_task_file(tmp_path / "p", "pro/a.blend", "artist", "secret")

    assert ok is True
    assert "Already locked" in message


def test_lock_task_file_blocks_foreign_stale_lock(tmp_path):
    from src.infrastructure.vcs.svn_errors import SvnAlreadyLockedError

    service, adapter = _service(tmp_path, {})
    adapter.lock_error = SvnAlreadyLockedError(
        "already locked", owner="other@studio.com", path="pro/a.blend"
    )

    ok, message = service.lock_task_file(tmp_path / "p", "pro/a.blend", "artist", "secret")

    assert ok is False
    assert "other@studio.com" in message


def test_lock_task_file_is_fail_closed_when_adapter_cannot_be_built(tmp_path, monkeypatch):
    service, _adapter = _service(tmp_path, {})

    def boom(_project_root):
        raise RuntimeError("bad configuration")

    monkeypatch.setattr(service, "_build_adapter", boom)

    ok, message = service.lock_task_file(tmp_path / "p", "pro/a.blend", "artist", "secret")

    assert ok is False
    assert "Could not initialize" in message


def test_scan_uses_structured_status_for_conflicts(tmp_path):
    from src.infrastructure.vcs.svn_xml import SvnStatusEntry

    service, adapter = _service(tmp_path, {})
    adapter.entries = [
        SvnStatusEntry(
            path="pro/a.blend",
            item="modified",
            props="conflicted",
            tree_conflicted=False,
        ),
        SvnStatusEntry(
            path="pro/b.blend",
            item="modified",
            props="none",
            tree_conflicted=True,
        ),
    ]

    changes = service.scan_local_changes(tmp_path / "project")

    assert len(changes) == 2
    assert changes[0].status == "C"
    assert changes[0].property_conflicted is True
    assert changes[0].is_conflicted is True
    assert changes[1].tree_conflicted is True
    assert changes[1].is_conflicted is True


def test_resolve_conflict_delegates_to_adapter(tmp_path):
    service, adapter = _service(tmp_path, {})

    ok, message = service.resolve_conflict(
        tmp_path / "project", "pro/a.blend", "theirs-full"
    )

    assert ok is True
    assert "resolved" in message.lower()
    assert adapter.resolve_calls == [("pro/a.blend", "theirs-full")]


def test_resolve_conflict_surfaces_adapter_error(tmp_path):
    service, adapter = _service(tmp_path, {})
    adapter.resolve_error = RuntimeError("not conflicted")

    ok, message = service.resolve_conflict(tmp_path / "project", "pro/a.blend")

    assert ok is False
    assert "not conflicted" in message


def test_update_working_copy_detailed_reports_obstructions(tmp_path):
    from src.infrastructure.vcs.svn_xml import SvnStatusEntry

    service, adapter = _service(tmp_path, {})
    adapter.entries = [
        SvnStatusEntry(path="pro/a.blend", item="obstructed"),
        SvnStatusEntry(path="pro/b.blend", item="modified", props="conflicted"),
    ]

    report = service.update_working_copy_detailed(tmp_path / "p", "artist", "secret")

    assert report.ok is False
    assert len(report.issues) == 2
    assert {issue.status for issue in report.issues} == {"~", "C"}


def test_move_path_aside_moves_file_and_adds_local_ignore(tmp_path):
    service, _adapter = _service(tmp_path, {})
    workspace = service.workspace_root(tmp_path / "p")
    source = workspace / "pro" / "cache.tmp"
    source.parent.mkdir(parents=True)
    source.write_text("cache", encoding="utf-8")

    ok, message = service.move_path_aside(tmp_path / "p", "pro/cache.tmp")

    assert ok is True
    assert "moved" in message.lower()
    assert source.exists() is False
    assert list(workspace.glob(".openstudio_aside/*/pro/cache.tmp"))
    assert ".openstudio_aside" in service.load_local_ignores(tmp_path / "p")


def test_local_ignore_roundtrip(tmp_path):
    service, _adapter = _service(tmp_path, {})

    ok, _ = service.add_local_ignore(tmp_path / "p", "pro/cache.tmp")
    ok2, _ = service.add_local_ignore(tmp_path / "p", "pro/cache.tmp")

    assert ok is True and ok2 is True
    assert service.load_local_ignores(tmp_path / "p") == ["cache.tmp"]
