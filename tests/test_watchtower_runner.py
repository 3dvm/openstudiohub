"""Unit tests for the watchtower_pipeline compatibility shim."""

import types
from dataclasses import dataclass

from src.infrastructure.watchtower_runner import (
    patch_casting_guard,
    patch_edit_guard,
    safe_get_env_data_as_dict,
)


def test_password_with_equals_is_preserved(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "KITSU_DATA_SOURCE_URL=http://host/api\n"
        "KITSU_DATA_SOURCE_USER_EMAIL=artist@studio.com\n"
        "KITSU_DATA_SOURCE_USER_PASSWORD=YapiCv8BsSZi6B3uXM3Sg4bAtqPZ8LMuQfVg1fF=0YyA==\n",
        encoding="utf-8",
    )

    env_vars = safe_get_env_data_as_dict(str(env_file))

    assert env_vars == {
        "KITSU_DATA_SOURCE_URL": "http://host/api",
        "KITSU_DATA_SOURCE_USER_EMAIL": "artist@studio.com",
        "KITSU_DATA_SOURCE_USER_PASSWORD": "YapiCv8BsSZi6B3uXM3Sg4bAtqPZ8LMuQfVg1fF=0YyA==",
    }


def test_blank_and_comment_lines_are_ignored(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "# Kitsu credentials\n"
        "\n"
        "KITSU_DATA_SOURCE_URL=http://host/api\n"
        "   \n"
        "KITSU_DATA_SOURCE_USER_EMAIL=artist@studio.com\n"
        "KITSU_DATA_SOURCE_USER_PASSWORD=s3cr3t\n",
        encoding="utf-8",
    )

    env_vars = safe_get_env_data_as_dict(str(env_file))

    assert env_vars["KITSU_DATA_SOURCE_USER_PASSWORD"] == "s3cr3t"
    assert len(env_vars) == 3


@dataclass
class _FakeEdit:
    project: object
    totalFrames: int
    frameOffset: int


class _FakeModels:
    Edit = _FakeEdit


def _project():
    return types.SimpleNamespace(name="proj", id="p1")


def test_edit_guard_passes_through_normal_result():
    class Writer:
        def get_project_edit(self, project):
            return ("edit", project)

    kitsu = types.SimpleNamespace(KitsuProjectWriter=Writer)
    patch_edit_guard(kitsu, _FakeModels)

    assert Writer().get_project_edit(_project()) == ("edit", _project())


def test_edit_guard_degrades_missing_preview_type_error():
    calls = []

    class Writer:
        def get_project_edit(self, project):
            calls.append(project)
            raise TypeError("'NoneType' object is not subscriptable")

    kitsu = types.SimpleNamespace(KitsuProjectWriter=Writer)
    patch_edit_guard(kitsu, _FakeModels)

    result = Writer().get_project_edit(_project())

    assert calls, "original method should have been attempted"
    assert isinstance(result, _FakeEdit)
    assert result.totalFrames == 0
    assert result.frameOffset == 0
    assert result.project.id == "p1"


def test_edit_guard_degrades_empty_preview_index_error():
    class Writer:
        def get_project_edit(self, project):
            raise IndexError("list index out of range")

    kitsu = types.SimpleNamespace(KitsuProjectWriter=Writer)
    patch_edit_guard(kitsu, _FakeModels)

    result = Writer().get_project_edit(_project())

    assert isinstance(result, _FakeEdit)
    assert result.totalFrames == 0


def test_edit_guard_is_idempotent():
    class Writer:
        def get_project_edit(self, project):
            raise TypeError("boom")

    kitsu = types.SimpleNamespace(KitsuProjectWriter=Writer)
    patch_edit_guard(kitsu, _FakeModels)
    patched = Writer.get_project_edit
    patch_edit_guard(kitsu, _FakeModels)

    assert Writer.get_project_edit is patched
    assert Writer().get_project_edit(_project()).totalFrames == 0


@dataclass
class _FakeCasting:
    shot: object
    assets: list


def _asset(asset_id):
    return types.SimpleNamespace(id=asset_id)


def _shot(shot_id):
    return types.SimpleNamespace(id=shot_id)


def test_casting_guard_drops_missing_shot():
    dropped = _FakeCasting(shot=None, assets=[_asset("a1")])
    kept = _FakeCasting(shot=_shot("s1"), assets=[_asset("a1")])

    class Writer:
        def get_project_casting(self, project, sequences, shots, assets):
            return [dropped, kept]

    kitsu = types.SimpleNamespace(KitsuProjectWriter=Writer)
    patch_casting_guard(kitsu)

    result = Writer().get_project_casting(_project(), [], [], [])

    assert result == [kept]


def test_casting_guard_filters_none_assets():
    casting = _FakeCasting(shot=_shot("s1"), assets=[_asset("a1"), None, _asset("a2")])

    class Writer:
        def get_project_casting(self, project, sequences, shots, assets):
            return [casting]

    kitsu = types.SimpleNamespace(KitsuProjectWriter=Writer)
    patch_casting_guard(kitsu)

    result = Writer().get_project_casting(_project(), [], [], [])

    assert [a.id for a in result[0].assets] == ["a1", "a2"]


def test_casting_guard_passes_through_valid_castings():
    castings = [
        _FakeCasting(shot=_shot("s1"), assets=[_asset("a1")]),
        _FakeCasting(shot=_shot("s2"), assets=[_asset("a2")]),
    ]

    class Writer:
        def get_project_casting(self, project, sequences, shots, assets):
            return castings

    kitsu = types.SimpleNamespace(KitsuProjectWriter=Writer)
    patch_casting_guard(kitsu)

    assert Writer().get_project_casting(_project(), [], [], []) == castings


def test_casting_guard_is_idempotent():
    class Writer:
        def get_project_casting(self, project, sequences, shots, assets):
            return [_FakeCasting(shot=None, assets=[None])]

    kitsu = types.SimpleNamespace(KitsuProjectWriter=Writer)
    patch_casting_guard(kitsu)
    patched = Writer.get_project_casting
    patch_casting_guard(kitsu)

    assert Writer.get_project_casting is patched
    assert Writer().get_project_casting(_project(), [], [], []) == []


