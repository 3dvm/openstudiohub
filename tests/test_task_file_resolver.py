"""Unit tests for the task file resolver."""

from src.application.services.task_file_resolver import TaskFileResolver


class FakeConfig:
    def get_vfs_svn_name(self):
        return "svn"


def _shot_task(**overrides):
    data = {
        "entity_type_name": "Shot",
        "entity_name": "SHO01",
        "sequence_name": "SQ03",
        "task_type_name": "Layout",
        "task_type_short_name": "layout",
        "data": {},
    }
    data.update(overrides)
    return data


def test_resolver_prefers_the_linked_file(tmp_path):
    target = tmp_path / "svn" / "pro" / "shots" / "SQ03" / "SHO01" / "SHO01-layout.blend"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")

    task = _shot_task(data={"filepath": "pro/shots/SQ03/SHO01/SHO01-layout.blend"})
    resolved = TaskFileResolver(FakeConfig()).resolve(tmp_path, task)

    assert resolved is not None
    assert resolved.absolute_path == target
    assert resolved.relative_path == "pro/shots/SQ03/SHO01/SHO01-layout.blend"


def test_resolver_handles_case_sensitive_directories_without_a_link(tmp_path):
    target = tmp_path / "svn" / "pro" / "shots" / "SQ03" / "SHO01" / "SHO01-layout.blend"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")

    resolved = TaskFileResolver(FakeConfig()).resolve(tmp_path, _shot_task())

    assert resolved is not None
    assert resolved.absolute_path == target


def test_resolver_picks_the_newest_manual_version(tmp_path):
    folder = tmp_path / "svn" / "pro" / "shots" / "SQ03" / "SHO01"
    folder.mkdir(parents=True)
    (folder / "SHO01-layout.blend").write_bytes(b"")
    (folder / "SHO01-layout_v2.blend").write_bytes(b"newer")

    resolved = TaskFileResolver(FakeConfig()).resolve(tmp_path, _shot_task())

    assert resolved is not None
    assert resolved.absolute_path.name == "SHO01-layout_v2.blend"


def test_resolver_handles_a_different_shot_folder_prefix(tmp_path):
    folder = tmp_path / "svn" / "pro" / "shots" / "SQ010" / "SH010_0020"
    folder.mkdir(parents=True)
    target = folder / "010_0020-layout.blend"
    target.write_bytes(b"")

    task = _shot_task(entity_name="010_0020", sequence_name="SQ010")
    resolved = TaskFileResolver(FakeConfig()).resolve(tmp_path, task)

    assert resolved is not None
    assert resolved.absolute_path == target


def test_resolver_returns_none_when_the_file_is_missing(tmp_path):
    (tmp_path / "svn" / "pro" / "shots").mkdir(parents=True)

    assert TaskFileResolver(FakeConfig()).resolve(tmp_path, _shot_task()) is None


def test_launch_target_is_none_when_the_file_is_missing(tmp_path):
    from src.application.services.launch_service import LaunchService

    (tmp_path / "svn").mkdir()

    assert (
        LaunchService._resolve_target_file(tmp_path, "svn", _shot_task(), None) is None
    )
