# =====================================================================================
# OPENSTUDIOHUB
# Module: tests/test_kitsu_export_service.py
# =====================================================================================

"""Unit tests for KitsuExportService (gazu fully faked, no network)."""

import json
from pathlib import Path

from src.application.services.kitsu_export_service import (
    ExportOptions,
    KitsuExportService,
)
from src.application.services.oshproject_format import OshProjectReader


class FakeTopography:
    vfs_svn = "svn"
    vfs_shared = "shared"
    vfs_local = "local"
    vfs_pipeline = "pipeline"


class FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_root(self):
        return self.root

    def get_topography(self):
        return FakeTopography()

    def get_vfs_svn_name(self):
        return "svn"

    def get_kitsu_api_url(self):
        return "http://localhost:8080"

    def get_server_for_project(self, project_root):
        return None

    def get_default_server(self):
        return None

    def get_server(self, server_id):
        return None


class FakeKitsu:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = []
        self.preview_size = 10
        self.attachment_size = 100

    def _record(self, name, *args):
        self.calls.append(name)

    def get_project(self, project_id):
        return {
            "id": "p1", "name": "Neon", "data": {"genre": "scifi"},
            "project_status_name": "Active",
            "team": [{"id": "u1", "email": "pm@studio.com", "full_name": "PM", "role": "manager"}],
        }

    def all_tasks_for_project(self, project_id):
        # Real Kitsu payload: people are referenced by id, not expanded.
        return [{
            "id": "t1", "name": "main", "task_type_id": "tt1", "task_status_id": "ts1",
            "entity_id": "s1", "data": {"filepath": "pro/shots/sq/s1/main.blend"},
            "assignees": ["u1"], "assigner_id": "u1",
        }]

    def all_comments_for_project(self, project_id):
        return [{"id": "c1", "task_id": "t1", "person_id": "u1",
                 "text": "looks good", "task_status_id": "ts1", "attachment_files": []}]

    def all_preview_files_for_project(self, project_id):
        # Kitsu stores the extension separately from the (extension-less) name.
        return [{"id": "pf1", "task_id": "t1", "extension": "mp4",
                 "original_name": "anim", "file_size": self.preview_size}]

    def get_all_attachment_files_for_project(self, project_id):
        return [{"id": "a1", "original_name": "ref", "extension": "pdf",
                 "size": self.attachment_size}]

    def get_working_files_for_task(self, task):
        return [{"id": "wf1", "name": "main", "mode": "working", "revision": 1,
                 "person_id": "u1"}]

    def get_time_spent(self, task, date=None):
        return {"u1": {"duration": 30, "date": "2026-09-01"}}

    def all_episodes_for_project(self, project_id):
        return []

    def all_sequences_for_project(self, project_id):
        return [{"id": "seq1", "name": "SQ01"}]

    def all_shots_for_project(self, project_id):
        return [{"id": "s1", "name": "s1", "parent_id": "seq1", "nb_frames": 24}]

    def all_assets_for_project(self, project_id):
        return [{"id": "as1", "name": "hero", "entity_type_id": "at1"}]

    def all_edits_for_project(self, project_id):
        return [{"id": "e1", "name": "Main Edit"}]

    def get_project_shots_casting(self, project_id):
        return {"s1": {"at1": ["as1"]}}

    def all_entity_links_for_project(self, project_id):
        return [{"entity_id": "s1", "asset_id": "as1", "nb_occurences": 1}]

    def all_task_types(self):
        return [{"id": "tt1", "name": "Animation", "color": "#fff", "for_entity": "Shot"}]

    def all_task_statuses_for_project(self, project_id):
        return [{"id": "ts1", "name": "WIP", "short_name": "wip", "color": "#f00"}]

    def all_asset_types(self):
        return [{"id": "at1", "name": "Character"}]

    def all_departments(self):
        return [{"id": "dep1", "name": "3D"}]

    def all_project_status(self):
        return [{"id": "ps1", "name": "Active"}]

    def all_persons(self):
        return [{"id": "u1", "email": "pm@studio.com", "full_name": "PM", "role": "manager"}]

    # Downloads write a small local file.
    def download_preview_movie(self, preview, file_path, progress_callback=None):
        self._record("download_preview_movie")
        Path(file_path).write_bytes(b"MOVIE" * 10)

    def download_preview_lowdef_movie(self, preview, file_path, progress_callback=None):
        self._record("download_preview_lowdef_movie")
        Path(file_path).write_bytes(b"LOW")

    def download_preview_file(self, preview, file_path, progress_callback=None):
        self._record("download_preview_file")
        Path(file_path).write_bytes(b"IMG")

    def download_preview_file_thumbnail(self, preview, file_path, progress_callback=None):
        self._record("download_preview_file_thumbnail")
        Path(file_path).write_bytes(b"THUMB")

    def download_attachment_file(self, attachment, file_path, progress_callback=None):
        self._record("download_attachment_file")
        Path(file_path).write_bytes(b"ATT")


def _make_project(root: Path) -> Path:
    project_root = root / "neon"
    (project_root / "pipeline").mkdir(parents=True)
    (project_root / "pipeline" / "project_init.json").write_text(json.dumps({
        "project_name": "Neon", "kitsu_project_id": "p1", "blender_version": "4.2",
        "template": "Standard", "dependencies": {},
        "topography_signature": {"vfs_svn": "svn", "vfs_shared": "shared",
                                  "vfs_local": "local", "vfs_pipeline": "pipeline",
                                  "custom_dirs": ["renders"]},
    }))
    (project_root / "pipeline" / "notes.txt").write_text("pipeline note")
    (project_root / "shared").mkdir()
    (project_root / "shared" / "shared.txt").write_text("shared data")
    (project_root / "renders").mkdir()
    (project_root / "renders" / "render.txt").write_text("rendered")
    (project_root / "local").mkdir()
    (project_root / "local" / "secret.txt").write_text("machine only")
    return project_root


def _make_service(tmp_path, kitsu):
    return KitsuExportService(kitsu, config_factory=FakeConfig(tmp_path), app_version="0.7.0")


def test_export_manifest_counts_and_persons(tmp_path):
    _make_project(tmp_path)
    kitsu = FakeKitsu(tmp_path)
    service = _make_service(tmp_path, kitsu)

    dest = tmp_path / "out"
    outcome = service.export("p1", "Neon", dest)
    assert outcome.success, outcome.message

    with OshProjectReader(outcome.archive_path) as reader:
        manifest = reader.read_manifest()
        names = reader.names()
        assert manifest["format_version"] == 1
        assert manifest["project"]["name"] == "Neon"
        assert manifest["counts"]["tasks"] == 1
        assert manifest["counts"]["persons"] == 1
        assert manifest["vcs"] == {}
        assert not any(name.startswith("files/local") for name in names)
        assert not any(name.startswith("files/shared") for name in names)
        assert any(name.startswith("files/pipeline") for name in names)
        assert "kitsu/persons.json" in names
        ok, mismatches = reader.verify_checksums()
        assert ok, mismatches
        persons = reader.read_json("kitsu/persons.json")
        assert persons[0]["email"] == "pm@studio.com"


def test_export_shared_optional(tmp_path):
    _make_project(tmp_path)
    kitsu = FakeKitsu(tmp_path)
    service = _make_service(tmp_path, kitsu)

    outcome = service.export(
        "p1", "Neon", tmp_path / "out", ExportOptions(include_shared=True)
    )
    assert outcome.success, outcome.message
    with OshProjectReader(outcome.archive_path) as reader:
        assert any(name.startswith("files/shared") for name in reader.names())


def test_export_media_cap_uses_lowdef_and_skips_oversize_attachment(tmp_path):
    _make_project(tmp_path)
    kitsu = FakeKitsu(tmp_path)
    kitsu.preview_size = 300 * 1024 * 1024  # > cap
    kitsu.attachment_size = 300 * 1024 * 1024
    service = _make_service(tmp_path, kitsu)

    outcome = service.export(
        "p1", "Neon", tmp_path / "out", ExportOptions(media_cap_mb=200)
    )
    assert outcome.success, outcome.message
    assert "download_preview_lowdef_movie" in kitsu.calls
    assert "download_attachment_file" not in kitsu.calls
    assert outcome.skipped_media


def test_collect_persons_resolves_id_based_references():
    service = KitsuExportService(None)
    data = {
        "all_persons": [
            {"id": "u1", "email": "pm@studio.com", "full_name": "PM", "role": "manager"},
            {"id": "u2", "email": "artist@studio.com", "full_name": "Artist", "role": "user"},
            {"id": "u9", "email": "unused@studio.com", "full_name": "Unused", "role": "user"},
        ],
        "project": {"team": []},
        "tasks": [{"id": "t1", "assignees": ["u2"], "assigner_id": "u1"}],
        "comments": [{"id": "c1", "person_id": "u1"}],
        "working_files_by_task": {"t1": [{"id": "wf1", "person_id": "u2"}]},
        "time_by_task": {"t1": [{"person_id": "u2", "duration": 30}]},
    }
    persons = service.collect_persons(data)
    emails = sorted(person["email"] for person in persons)
    assert emails == ["artist@studio.com", "pm@studio.com"]
    assert "unused@studio.com" not in emails


def test_collect_persons_keeps_unresolved_referenced_id():
    service = KitsuExportService(None)
    data = {
        "all_persons": [],
        "project": {"team": []},
        "tasks": [{"id": "t1", "assignees": ["ghost"]}],
        "comments": [],
        "working_files_by_task": {},
        "time_by_task": {},
    }
    persons = service.collect_persons(data)
    assert persons == [{
        "id": "ghost", "email": "", "full_name": "",
        "first_name": "", "last_name": "", "role": "user",
    }]


def test_export_packs_custom_dirs(tmp_path):
    _make_project(tmp_path)
    kitsu = FakeKitsu(tmp_path)
    service = _make_service(tmp_path, kitsu)

    outcome = service.export("p1", "Neon", tmp_path / "out")
    assert outcome.success, outcome.message
    with OshProjectReader(outcome.archive_path) as reader:
        names = reader.names()
    assert any(name.startswith("files/custom/renders/") for name in names)


def test_export_media_names_keep_extensions(tmp_path):
    _make_project(tmp_path)
    kitsu = FakeKitsu(tmp_path)
    service = _make_service(tmp_path, kitsu)

    outcome = service.export("p1", "Neon", tmp_path / "out")
    assert outcome.success, outcome.message
    with OshProjectReader(outcome.archive_path) as reader:
        names = reader.names()
    assert any(name.endswith("pf1_anim.mp4") for name in names)
    assert any(name.endswith("a1_ref.pdf") for name in names)


def test_estimate_returns_approximate_sizes(tmp_path):
    _make_project(tmp_path)
    kitsu = FakeKitsu(tmp_path)
    service = _make_service(tmp_path, kitsu)
    sizes = service.estimate("p1", "Neon", ExportOptions())
    assert sizes["approximate"] is True
    assert sizes["files_pipeline"] > 0
    assert sizes["total"] >= sizes["files_pipeline"]
