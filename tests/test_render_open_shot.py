"""Opening a shot uses the task sandbox and SVN lock/unlock protocol."""

from pathlib import Path

from src.domain.render.models import RenderQuality, RenderShot
from src.interfaces.qt.workers.render_workers import OpenShotBlendWorker


class FakeConfig:
    def get_vfs_local_name(self):
        return "local"

    def get_vfs_svn_name(self):
        return "svn"

    def get_kitsu_api_url(self):
        return "https://kitsu.example"


class FakeSync:
    def __init__(self, lock_ok=True):
        self.lock_ok = lock_ok
        self.lock_calls = []
        self.unlock_calls = []

    def lock_task_file(self, root, path, user, password):
        self.lock_calls.append((root, path, user, password))
        return (self.lock_ok, "locked" if self.lock_ok else "locked by someone else")

    def unlock_task_file(self, root, path, user, password, force=False):
        self.unlock_calls.append((root, path, user, password, force))
        return True, "unlocked"


class FakeLaunch:
    def __init__(self):
        self.calls = []

    def launch(self, **kwargs):
        self.calls.append(kwargs)


def _worker(tmp_path, sync):
    root = tmp_path / "project"
    (root / "local").mkdir(parents=True)
    (root / "local" / "project_config.json").write_text("{}", encoding="utf-8")
    blend = root / "svn" / "pro" / "shots" / "sq010" / "sh010" / "sh010-layout.blend"
    blend.parent.mkdir(parents=True)
    blend.write_bytes(b"")
    shot = RenderShot(
        name="sh010",
        blend_path=blend,
        relative_path="pro/shots/sq010/sh010/sh010-layout.blend",
        sequence="sq010",
        quality=RenderQuality(),
        frame_start=101,
        frame_end=110,
        object_count=20,
        mesh_count=10,
        has_camera=True,
    )
    launch = FakeLaunch()
    worker = OpenShotBlendWorker(
        config_factory=FakeConfig(),
        launch_service=launch,
        sync_service=sync,
        production_service=None,
        project_root=root,
        project_id="p1",
        project_name="Project",
        shot=shot,
        svn_user="artist",
        svn_pwd="secret",
        kitsu_user="artist@example.com",
        kitsu_pwd="kitsu-secret",
        user_role="artist",
    )
    return worker, shot, launch


def test_open_shot_locks_launches_and_unlocks(qapp, tmp_path):
    sync = FakeSync()
    worker, shot, launch = _worker(tmp_path, sync)

    worker.run()

    assert sync.lock_calls and sync.lock_calls[0][1] == shot.relative_path
    assert sync.unlock_calls and sync.unlock_calls[0][1] == shot.relative_path
    assert launch.calls and launch.calls[0]["target_file"] == shot.blend_path
    assert launch.calls[0]["task_data"]["data"]["filepath"] == shot.relative_path


def test_open_shot_does_not_launch_when_lock_fails(qapp, tmp_path):
    sync = FakeSync(lock_ok=False)
    worker, _shot, launch = _worker(tmp_path, sync)

    worker.run()

    assert launch.calls == []
    assert sync.unlock_calls == []
