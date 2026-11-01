"""Tests for the VCS backfill of files spawned before tracking existed."""

from src.interfaces.qt.workers.project_list_workers import BackfillSpawnedFilesWorker


class FakeConfig:
    def get_vfs_svn_name(self):
        return "svn"


class FakeKitsu:
    def all_tasks_for_project(self, project_id):
        return [
            {
                "id": "t1",
                "entity_type_name": "Shot",
                "entity_name": "sh010",
                "sequence_name": "sq010",
                "task_type_name": "Layout",
                "data": {"filepath": "pro/shots/sq010/sh010/sh010-layout.blend"},
            }
        ]


class FakeProduction:
    def __init__(self):
        self.kitsu = FakeKitsu()


class FakeSync:
    config_factory = FakeConfig()

    def __init__(self):
        self.calls = []

    def commit_spawned_files(self, root, paths, user, pwd, message):
        self.calls.append((root, list(paths), user, pwd, message))
        return True, "Committed 1 spawned file(s) to the VCS."


def test_backfill_worker_resolves_linked_files_and_commits_once(tmp_path, qapp):
    project_root = tmp_path / "p0005"
    target = project_root / "svn" / "pro" / "shots" / "sq010" / "sh010" / "sh010-layout.blend"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")

    sync = FakeSync()
    worker = BackfillSpawnedFilesWorker(
        sync,
        FakeProduction(),
        "p1",
        project_root,
        "artist",
        "secret",
    )
    results = []
    worker.finished_backfill.connect(lambda pid, ok, msg: results.append((pid, ok, msg)))

    worker.run()

    assert results == [("p1", True, "Committed 1 spawned file(s) to the VCS.")]
    assert len(sync.calls) == 1
    root, paths, user, pwd, message = sync.calls[0]
    assert root == project_root
    assert paths == ["pro/shots/sq010/sh010/sh010-layout.blend"]
    assert user == "artist"
    assert pwd == "secret"
    assert message.startswith("OpenStudioHub: first spawn backfill (1 file(s))")
