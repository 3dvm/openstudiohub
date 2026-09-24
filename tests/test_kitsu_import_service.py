# =====================================================================================
# OPENSTUDIOHUB
# Module: tests/test_kitsu_import_service.py
# =====================================================================================

"""Unit tests for KitsuImportService (gazu fully faked, no network)."""

import json
import queue
import subprocess
from pathlib import Path

from src.application.services.kitsu_import_service import (
    ImportOptions,
    KitsuImportService,
)
from src.domain.workspace.blueprint import ProjectBlueprint
from src.application.services.oshproject_format import (
    OshProjectWriter,
    build_manifest,
)
from src.domain.workspace.topography import WorkspaceTopography
from src.domain.workspace.vcs_server import VCSServer
from src.domain.workspace.vcs_server_profile import VCSServerProfile


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
def FakeTopography():
    # The TARGET machine uses a different pipeline folder than the source archive.
    return WorkspaceTopography(
        vfs_svn="svn", vfs_shared="shared", vfs_local="local",
        vfs_pipeline="05_config_estudio",
    )


class FakeServer:
    def __init__(self, server_id: str = "vps") -> None:
        self.id = server_id
        self.name = "VPS"
        self.repository_url = "svn://target"
        self.adapter = "svn"
        self.profile = VCSServerProfile()


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
        return "http://target:8080"

    def get_server(self, server_id):
        return FakeServer(server_id or "vps")

    def get_default_server(self):
        return FakeServer("vps")

    def get_server_for_project(self, project_root):
        return FakeServer("vps")


class FakeNas:
    def __init__(self, base: Path) -> None:
        self.base_dir = base

    def resolve_project_dir(self, project_name):
        return None


class FakeKitsu:
    def __init__(self) -> None:
        self.calls = []
        self.existing_project = None
        self.existing_task_types = [{"id": "tt1", "name": "Animation", "color": "#fff", "for_entity": "Shot"}]
        self.existing_task_statuses = [{"id": "ts1", "name": "WIP", "short_name": "wip", "color": "#f00"}]
        self.existing_asset_types = [{"id": "at1", "name": "Character"}]
        self.existing_departments = []
        self.new_persons_created = []
        self._counter = 0

    def _id(self, prefix):
        self._counter += 1
        return f"new-{prefix}-{self._counter}"

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def _names(self):
        return [name for name, _a, _k in self.calls]

    # -- project ---------------------------------------------------------
    def get_project_by_name(self, name):
        return self.existing_project

    def create_project(self, name):
        self._record("create_project", name)
        return True, "ok", {"id": "new-project", "name": name}

    def update_project_data(self, project, data):
        self._record("update_project_data", data)
        return project

    def update_project(self, project):
        self._record("update_project", project)
        return project

    def get_project_status_by_name(self, name):
        return {"id": "ps1", "name": name}

    def delete_project(self, project_id):
        self._record("delete_project", project_id)
        return True, "deleted"

    def upload_project_splash(self, project_id, image_path):
        self._record("upload_project_splash", project_id, Path(image_path).name)
        return True

    # -- people ----------------------------------------------------------
    def all_persons(self):
        return []

    def new_person(self, first_name, last_name, email, role="user", password=None, departments=None, active=True):
        self._record("new_person", email, role, password)
        person = {"id": self._id("person"), "email": email, "full_name": f"{first_name} {last_name}".strip(), "role": role}
        self.new_persons_created.append(person)
        return person

    def add_person_to_team(self, project, person, role=None):
        self._record("add_person_to_team", person.get("id"), role)
        return person

    # -- studio ----------------------------------------------------------
    def all_task_statuses(self):
        return list(self.existing_task_statuses)

    def all_task_types(self):
        return list(self.existing_task_types)

    def all_asset_types(self):
        return list(self.existing_asset_types)

    def all_departments(self):
        return list(self.existing_departments)

    def all_task_statuses_for_project(self, project):
        return list(self.existing_task_statuses)

    def all_project_status(self):
        return [{"id": "ps1", "name": "Active"}]

    def new_task_status(self, name, short_name="", color="#000000"):
        self._record("new_task_status", name)
        return {"id": self._id("status"), "name": name, "short_name": short_name, "color": color}

    def new_task_type(self, name, color="#000000", for_entity="Asset"):
        self._record("new_task_type", name)
        return {"id": self._id("ttype"), "name": name, "color": color, "for_entity": for_entity}

    def new_asset_type(self, name):
        self._record("new_asset_type", name)
        return {"id": self._id("atype"), "name": name}

    def new_department(self, name, color=""):
        self._record("new_department", name)
        return {"id": self._id("dept"), "name": name}

    # -- entities --------------------------------------------------------
    def get_episode_by_name(self, project, name):
        return None

    def get_sequence_by_name(self, project, name, episode=None):
        return None

    def get_shot_by_name(self, sequence, name):
        return None

    def get_asset_by_name(self, project, name, asset_type=None):
        return None

    def get_edit_by_name(self, project, name):
        return None

    def new_episode(self, project, name):
        self._record("new_episode", name)
        return {"id": self._id("episode"), "name": name}

    def new_sequence(self, project, name, episode=None):
        self._record("new_sequence", name)
        return {"id": self._id("sequence"), "name": name}

    def new_shot(self, project, sequence, name, nb_frames=None, frame_in=None, frame_out=None, description=None, data=None):
        self._record("new_shot", name)
        return {"id": self._id("shot"), "name": name}

    def new_asset(self, project, asset_type, name, description=None, extra_data=None, episode=None, is_shared=False):
        self._record("new_asset", name)
        return {"id": self._id("asset"), "name": name}

    def new_edit(self, project, name, description=None, data=None, episode=None):
        self._record("new_edit", name)
        return {"id": self._id("edit"), "name": name}

    def update_shot_data(self, shot, data):
        self._record("update_shot_data", data)
        return shot

    def update_asset_data(self, asset, data):
        self._record("update_asset_data", data)
        return asset

    def update_edit_data(self, edit, data):
        self._record("update_edit_data", data)
        return edit

    # -- casting ---------------------------------------------------------
    def cast_asset(self, project, entities, asset, nb_occurences=None, label=None):
        self._record("cast_asset", entities.get("id"), asset.get("id"))
        return {}

    def update_shot_casting(self, project, shot, casting):
        self._record("update_shot_casting", shot.get("id"), casting)
        return {}

    def update_asset_casting(self, project, asset, casting):
        self._record("update_asset_casting", asset.get("id"), casting)
        return {}

    # -- tasks -----------------------------------------------------------
    def new_task(self, entity, task_type, name="main", task_status=None, assigner=None, assignees=None):
        self._record("new_task", entity.get("id"), task_type.get("id"), name, assignees)
        return {"id": self._id("task"), "name": name, "entity_id": entity.get("id")}

    def update_task_data(self, task, data):
        self._record("update_task_data", task.get("id"), data)
        return task

    def update_task(self, task):
        self._record("update_task", task)
        return task

    def assign_task(self, task, person):
        self._record("assign_task", task.get("id"), person.get("id"))
        return task

    def get_software_by_name(self, name):
        return {"id": "sw1", "name": name}

    def new_working_file(self, task, name="main", mode="working", software=None, comment="", person=None, revision=0, sep="/"):
        self._record("new_working_file", task.get("id"), name, revision, person.get("id") if person else None)
        return {"id": self._id("wf")}

    # -- comments / previews --------------------------------------------
    def add_comment(self, task, task_status, comment="", person=None, attachments=None, created_at=None, checklist=None, for_client=False):
        self._record("add_comment", task.get("id"), comment, person.get("id") if person else None)
        return {"id": self._id("comment")}

    def reply_to_comment(self, task, comment, text, person=None):
        self._record("reply_to_comment", comment.get("id"), text)
        return {"id": self._id("reply")}

    def add_attachment_files_to_comment(self, task, comment, attachments):
        self._record("add_attachment_files_to_comment", comment.get("id"), list(attachments))
        return comment

    def publish_preview(self, task, task_status, comment="", person=None, preview_file_path=None, preview_file_url=None, attachments=None, revision=None, set_thumbnail=False):
        self._record("publish_preview", task.get("id"), preview_file_path)
        return {}, {}

    # -- time ------------------------------------------------------------
    def add_time_spent(self, task, person, date, duration):
        self._record("add_time_spent", task.get("id"), person.get("id"), date, duration)
        return {}


# ---------------------------------------------------------------------------
# Archive builder
# ---------------------------------------------------------------------------
def _build_archive(tmp_path: Path, embed: bool = False, source_vfs_svn: str = "svn") -> Path:
    archive = tmp_path / "bundle.oshproject"
    manifest = build_manifest(
        project={"name": "Neon"},
        blueprint={
            "project_name": "Neon", "kitsu_project_id": "p1", "blender_version": "4.2",
            "template": "Standard", "dependencies": {},
            "topography_signature": {"vfs_svn": source_vfs_svn, "vfs_shared": "shared",
                                      "vfs_local": "local", "vfs_pipeline": "pipeline"},
        },
        inclusion={"media": True, "shared": False, "embed_svn_dump": embed},
        vcs={"server_id": "source", "server_url": "svn://source"},
        counts={"tasks": 1},
        source_kitsu_url="http://source:8080",
    )
    with OshProjectWriter(archive) as writer:
        writer.add_json("kitsu/project.json", {"id": "p1", "name": "Neon", "data": {"genre": "scifi"},
                                                "project_status_name": "Active"})
        writer.add_json("kitsu/persons.json", [
            {"id": "u1", "email": "pm@studio.com", "full_name": "PM", "role": "manager"},
            {"id": "u2", "email": "artist@studio.com", "full_name": "Artist", "role": "user"},
        ])
        writer.add_json("kitsu/studio/task_types.json", [
            {"id": "tt1", "name": "Animation", "color": "#fff", "for_entity": "Shot"},
            {"id": "tt2", "name": "Modeling", "color": "#0ff", "for_entity": "Asset"},
        ])
        writer.add_json("kitsu/studio/task_statuses.json", [
            {"id": "ts1", "name": "WIP", "short_name": "wip", "color": "#f00"},
        ])
        writer.add_json("kitsu/studio/asset_types.json", [{"id": "at1", "name": "Character"}])
        writer.add_json("kitsu/studio/departments.json", [{"id": "dep1", "name": "3D"}])
        writer.add_json("kitsu/studio/project_statuses.json", [{"id": "ps1", "name": "Active"}])
        writer.add_json("kitsu/entities/episodes.json", [])
        writer.add_json("kitsu/entities/sequences.json", [{"id": "seq1", "name": "SQ01"}])
        writer.add_json("kitsu/entities/shots.json", [{"id": "s1", "name": "s1", "parent_id": "seq1", "nb_frames": 24}])
        writer.add_json("kitsu/entities/assets.json", [{"id": "as1", "name": "hero", "entity_type_id": "at1"}])
        writer.add_json("kitsu/entities/edits.json", [{"id": "e1", "name": "Main Edit"}])
        writer.add_json("kitsu/casting.json", {
            "shots_casting": {"s1": {"at1": ["as1"]}},
            "entity_links": [{"entity_id": "s1", "asset_id": "as1", "nb_occurences": 1}],
        })
        writer.add_json("kitsu/tasks.json", [{
            "id": "t1", "name": "main", "task_type_id": "tt1", "task_status_id": "ts1",
            "entity_id": "s1", "data": {"filepath": "pro/shots/sq01/s1/main.blend"},
            "assignees": ["u2"], "assigner_id": "u1",
        }])
        writer.add_json("kitsu/comments.json", [
            {"id": "c1", "task_id": "t1", "person_id": "u1",
             "text": "root", "task_status_id": "ts1", "attachment_files": [{"id": "att1"}]},
            {"id": "c2", "task_id": "t1", "person_id": "u2",
             "text": "reply", "parent_id": "c1", "task_status_id": "ts1", "attachment_files": []},
        ])
        writer.add_json("kitsu/working_files.json", [{
            "id": "wf1", "task_id": "t1", "name": "main", "mode": "working", "revision": 2,
            "person_id": "u2",
            "software": {"name": "Blender"},
        }])
        writer.add_json("kitsu/time_spent.json", [{
            "task_id": "t1", "person_id": "u2", "date": "2026-09-01", "duration": 45,
        }])
        writer.add_bytes("media/previews/t1/pf1_anim.mp4", b"MOVIE")
        writer.add_bytes("media/attachments/att1_ref.pdf", b"PDF")
        writer.add_bytes("files/pipeline/splash.png", b"\x89PNG\r\n\x1a\nfake-splash")
        writer.add_text("files/pipeline/notes.txt", "pipeline note")
        writer.add_text("files/shared/shared.txt", "shared data")
        writer.add_text("files/custom/renders/render.txt", "custom content")
        if embed:
            writer.add_bytes("vcs/svn.dump.gz", b"FAKE-DUMP")
        writer.write_manifest(manifest)
    return archive


def _make_service(tmp_path, kitsu, monkeypatch):
    config = FakeConfig(tmp_path / "projects")
    nas = FakeNas(tmp_path / "projects")
    service = KitsuImportService(kitsu, config_factory=config, nas_manager=nas)
    if monkeypatch is not None:
        monkeypatch.setattr(service, "_load_dump", lambda server, name, path: (True, "loaded"))
        # No real VCS server in tests: report the repo as already target-named.
        monkeypatch.setattr(service, "_repo_top_level_dirs", lambda server, path: ["svn"])
    return service


def _person_map():
    return {
        "u1": {"id": "target-u1", "email": "pm@studio.com", "full_name": "PM", "role": "manager"},
        "u2": {"id": "target-u2", "email": "artist@studio.com", "full_name": "Artist", "role": "user"},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_import_aborts_on_existing_project_name(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path)
    kitsu = FakeKitsu()
    kitsu.existing_project = {"id": "clash", "name": "Neon"}
    service = _make_service(tmp_path, kitsu, monkeypatch)

    plan = service.inspect(archive)
    report = service.import_project(plan, _person_map(), ImportOptions())

    assert report.success is False
    assert "already exists" in report.message
    assert "create_project" not in kitsu._names()


def test_person_remap_by_email_uses_target_ids(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path)
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)

    plan = service.inspect(archive)
    report = service.import_project(plan, _person_map(), ImportOptions())
    assert report.success, report.message

    new_task_calls = [call for call in kitsu.calls if call[0] == "new_task"]
    assert new_task_calls, "new_task should have been called"
    assignees = new_task_calls[0][1][3]
    assert assignees and assignees[0]["id"] == "target-u2"
    assert "new_person" not in kitsu._names()
    assert "add_person_to_team" in kitsu._names()


def test_studio_resources_create_or_get_before_tasks(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path)
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)

    plan = service.inspect(archive)
    service.import_project(plan, _person_map(), ImportOptions())

    names = kitsu._names()
    # Existing "Animation" must NOT be recreated; missing "Modeling" must be.
    created_types = [a[0] for n, a, _k in kitsu.calls if n == "new_task_type"]
    assert created_types == ["Modeling"]
    assert names.index("new_task_type") < names.index("new_task")


def test_task_filepath_preserved(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path)
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)

    plan = service.inspect(archive)
    service.import_project(plan, _person_map(), ImportOptions())

    # The status and the custom data must be applied in a single update so the
    # later PUT cannot wipe ``data.filepath``.
    update_calls = [call for call in kitsu.calls if call[0] == "update_task"]
    assert update_calls
    task_payload = update_calls[0][1][0]
    assert task_payload["data"]["filepath"] == "pro/shots/sq01/s1/main.blend"
    assert task_payload["task_status_id"] == "ts1"


def test_comments_replies_and_attachments(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path)
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)

    plan = service.inspect(archive)
    service.import_project(plan, _person_map(), ImportOptions())

    names = kitsu._names()
    assert "add_comment" in names
    assert "reply_to_comment" in names
    assert names.index("add_comment") < names.index("reply_to_comment")

    attachment_calls = [call for call in kitsu.calls if call[0] == "add_attachment_files_to_comment"]
    assert attachment_calls
    attachment_paths = attachment_calls[0][1][1]
    assert attachment_paths and attachment_paths[0].endswith("att1_ref.pdf")
    assert "publish_preview" in names


def test_working_files_and_time_spent_restored(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path)
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)

    plan = service.inspect(archive)
    service.import_project(plan, _person_map(), ImportOptions())

    wf_calls = [call for call in kitsu.calls if call[0] == "new_working_file"]
    assert wf_calls and wf_calls[0][1][2] == 2
    assert wf_calls[0][1][3] == "target-u2"

    time_calls = [call for call in kitsu.calls if call[0] == "add_time_spent"]
    assert time_calls
    assert time_calls[0][1][1] == "target-u2"
    assert time_calls[0][1][3] == 45


def test_non_vcs_recreation_pipeline_and_blueprint(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path, embed=False)
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)

    plan = service.inspect(archive)
    report = service.import_project(plan, _person_map(), ImportOptions(target_vcs_server_id="vps"))
    assert report.success, report.message
    assert report.needs_checkout is True
    assert report.project_root is not None

    # The blueprint is written under the TARGET topography, not the source's.
    blueprint_path = report.project_root / "05_config_estudio" / "project_init.json"
    assert blueprint_path.exists()
    blueprint = json.loads(blueprint_path.read_text())
    assert blueprint["project_name"] == "Neon"
    assert blueprint["kitsu_project_id"] == "new-project"
    assert blueprint["vcs_server_id"] == "vps"

    # Non-VCS payload is restored into the target folders; local/ is never created.
    assert (report.project_root / "05_config_estudio" / "splash.png").exists()
    assert (report.project_root / "05_config_estudio" / "notes.txt").exists()
    assert (report.project_root / "shared" / "shared.txt").exists()
    assert (report.project_root / "renders" / "render.txt").exists()
    # VCS folders are NOT pre-created: the repository owns them and the checkout
    # will materialize them (pre-creating them causes tree conflicts).
    assert not (report.project_root / "svn" / "pro").exists()
    assert not (report.project_root / "local").exists()

    # The splash image is re-uploaded as the project thumbnail.
    splash_calls = [call for call in kitsu.calls if call[0] == "upload_project_splash"]
    assert splash_calls and splash_calls[0][1][1] == "splash.png"


def test_tasks_use_update_task_not_task_status(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path)
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)

    plan = service.inspect(archive)
    service.import_project(plan, _person_map(), ImportOptions())

    names = kitsu._names()
    assert "update_task" in names
    assert "update_task_status" not in names


def test_team_roles_are_sanitized(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path)
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)

    person_map = _person_map()
    person_map["u1"]["role"] = "admin"  # invalid for a project team
    plan = service.inspect(archive)
    service.import_project(plan, person_map, ImportOptions())

    team_calls = [call for call in kitsu.calls if call[0] == "add_person_to_team"]
    assert team_calls
    roles = {call[1][1] for call in team_calls}
    # ``None`` means "inherit the person's global role" (used for global-only
    # roles like admin); the other values are valid project roles.
    assert roles <= {None, "user", "supervisor", "manager", "client", "vendor"}


def test_embedded_dump_creates_empty_and_loads(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path, embed=True)
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)
    loaded = {}

    def fake_load(server, project_name, dump_path):
        loaded["server"] = server.id
        loaded["project"] = project_name
        loaded["dump"] = Path(dump_path).name
        return True, "loaded"

    monkeypatch.setattr(service, "_load_dump", fake_load)

    plan = service.inspect(archive)
    report = service.import_project(plan, _person_map(), ImportOptions(target_vcs_server_id="vps"))
    assert report.success, report.message
    assert report.needs_checkout is False
    assert loaded == {"server": "vps", "project": "Neon", "dump": "svn.dump.gz"}


def test_create_target_person_has_no_password(tmp_path):
    kitsu = FakeKitsu()
    service = KitsuImportService(kitsu)
    person = service.create_target_person(
        {"email": "new@studio.com", "full_name": "New Artist", "role": "user"}
    )
    assert person["email"] == "new@studio.com"
    password_calls = [call for call in kitsu.calls if call[0] == "new_person"]
    assert password_calls
    assert password_calls[0][1][2] is None


def test_preview_person_mapping_matches_by_email(tmp_path):
    kitsu = FakeKitsu()
    kitsu.all_persons = lambda: [{"id": "t1", "email": "PM@studio.com", "full_name": "PM"}]
    service = KitsuImportService(kitsu)
    archive = _build_archive(tmp_path)
    plan = service.inspect(archive)
    rows = service.preview_person_mapping(plan)
    matched = {row.email: row.matched for row in rows}
    assert matched["pm@studio.com"] is True
    assert matched["artist@studio.com"] is False


# ---------------------------------------------------------------------------
# Repository topography reconciliation + step logging
# ---------------------------------------------------------------------------
def _blueprint_with_topography():
    return ProjectBlueprint(
        project_name="Neon",
        kitsu_project_id="p1",
        blender_version="4.2",
        template="Standard",
        topography=WorkspaceTopography(),
    )


def _recording_server_command(recorded):
    def fake(server, inner):
        recorded.append(inner)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    return fake


def test_repo_topology_renamed_and_ignore_rewritten(monkeypatch):
    kitsu = FakeKitsu()
    service = KitsuImportService(kitsu)
    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda server, path: ["svn_src"])
    recorded = []
    monkeypatch.setattr(service, "_server_command", _recording_server_command(recorded))

    server = FakeServer()
    service._map_repo_topography(
        server, "neon", "svn_src", "svn", _blueprint_with_topography(), rename=True
    )

    assert any("svn mv" in inner and "svn_src" in inner and "svn" in inner for inner in recorded)
    assert any("propset svn:ignore" in inner for inner in recorded)


def test_repo_topology_not_touched_when_target_present(monkeypatch):
    kitsu = FakeKitsu()
    service = KitsuImportService(kitsu)
    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda server, path: ["svn"])
    recorded = []
    monkeypatch.setattr(service, "_server_command", _recording_server_command(recorded))

    service._map_repo_topography(FakeServer(), "neon", "svn_src", "svn", _blueprint_with_topography())

    assert not any("svn mv" in inner for inner in recorded)


def test_repo_topology_skipped_when_repo_missing(monkeypatch):
    kitsu = FakeKitsu()
    service = KitsuImportService(kitsu)
    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda server, path: [])
    recorded = []
    monkeypatch.setattr(service, "_server_command", _recording_server_command(recorded))

    service._map_repo_topography(FakeServer(), "neon", "svn_src", "svn", _blueprint_with_topography())

    assert recorded == []


def test_repo_topology_renames_over_empty_target(monkeypatch):
    kitsu = FakeKitsu()
    service = KitsuImportService(kitsu)
    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda server, path: ["svn", "svn_src"])
    # The target folder exists but is empty; the source folder holds the files.
    monkeypatch.setattr(service, "_list_dir_url", lambda server, url: ([], True))
    recorded = []
    monkeypatch.setattr(service, "_server_command", _recording_server_command(recorded))

    service._map_repo_topography(
        FakeServer(), "neon", "svn_src", "svn", _blueprint_with_topography(), rename=True
    )

    assert any("svn rm" in inner for inner in recorded)
    assert any("svn mv" in inner and "svn_src" in inner for inner in recorded)


def test_probe_repository_states(tmp_path, monkeypatch):
    kitsu = FakeKitsu()
    service = KitsuImportService(
        kitsu, config_factory=FakeConfig(tmp_path), nas_manager=FakeNas(tmp_path)
    )
    plan = service.inspect(_build_archive(tmp_path, source_vfs_svn="svn_src"))

    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda s, p: ["svn"])
    assert service.probe_repository(plan, "vps")["state"] == "ok"

    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda s, p: ["svn_src"])
    status = service.probe_repository(plan, "vps")
    assert status["state"] == "rename_needed"
    assert status["source"] == "svn_src"

    # Unknown source name: propose the single root dir.
    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda s, p: ["legacy"])
    status = service.probe_repository(plan, "vps")
    assert status["state"] == "rename_needed"
    assert status["source"] == "legacy"

    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda s, p: [])
    assert service.probe_repository(plan, "vps")["state"] == "missing"


def test_probe_empty_target_folder_offers_rename(tmp_path, monkeypatch):
    service = KitsuImportService(
        FakeKitsu(), config_factory=FakeConfig(tmp_path), nas_manager=FakeNas(tmp_path)
    )
    plan = service.inspect(_build_archive(tmp_path, source_vfs_svn="svn_src"))

    # The target folder already exists on the repo but carries no content: the
    # real files live under the source-named folder, so a rename is needed.
    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda s, p: ["svn", "svn_src"])
    monkeypatch.setattr(service, "_list_dir_url", lambda s, u: ([], True))

    status = service.probe_repository(plan, "vps")
    assert status["state"] == "rename_needed"
    assert status["source"] == "svn_src"
    assert "empty" in status["diagnostics"]["reason"]


def test_reconcile_drops_empty_target_before_move(monkeypatch):
    service = KitsuImportService(FakeKitsu())
    recorded = []
    monkeypatch.setattr(service, "_list_dir_url", lambda s, u: ([], True))
    monkeypatch.setattr(service, "_server_command", _recording_server_command(recorded))

    ok, _message = service._reconcile_repo_topology(FakeServer(), "/srv/svn/neon", "svn_src", "svn")

    assert ok
    assert any("svn rm" in inner for inner in recorded)
    assert any("svn mv" in inner for inner in recorded)


def test_probe_repository_embedded_dump_missing_repo(tmp_path, monkeypatch):
    service = KitsuImportService(
        FakeKitsu(), config_factory=FakeConfig(tmp_path), nas_manager=FakeNas(tmp_path)
    )
    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda s, p: [])

    plan = service.inspect(_build_archive(tmp_path / "a", embed=True, source_vfs_svn="svn_src"))
    status = service.probe_repository(plan, "vps")
    assert status["state"] == "rename_needed"
    assert status["source"] == "svn_src"

    same = service.inspect(_build_archive(tmp_path / "b", embed=True, source_vfs_svn="svn"))
    assert service.probe_repository(same, "vps")["state"] == "ok"


def test_import_aborts_when_rename_not_authorized(tmp_path, monkeypatch):
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)
    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda s, p: ["svn_src"])

    plan = service.inspect(_build_archive(tmp_path, source_vfs_svn="svn_src"))
    report = service.import_project(plan, _person_map(), ImportOptions(target_vcs_server_id="vps"))

    assert report.success is False
    assert "rename" in report.message.lower()
    assert "create_project" not in kitsu._names()


def test_import_renames_when_authorized(tmp_path, monkeypatch):
    kitsu = FakeKitsu()
    service = _make_service(tmp_path, kitsu, monkeypatch)
    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda s, p: ["svn_src"])
    recorded = []
    monkeypatch.setattr(service, "_server_command", _recording_server_command(recorded))

    plan = service.inspect(_build_archive(tmp_path, source_vfs_svn="svn_src"))
    report = service.import_project(
        plan, _person_map(),
        ImportOptions(target_vcs_server_id="vps", rename_repository=True),
    )
    assert report.success, report.message
    assert any("svn mv" in inner for inner in recorded)


def test_import_emits_success_step_logs(tmp_path, monkeypatch):
    archive = _build_archive(tmp_path)
    kitsu = FakeKitsu()
    events: "queue.Queue" = queue.Queue()
    config = FakeConfig(tmp_path / "projects")
    service = KitsuImportService(
        kitsu, config_factory=config, nas_manager=FakeNas(tmp_path / "projects"), event_sink=events
    )
    monkeypatch.setattr(service, "_repo_top_level_dirs", lambda server, path: ["svn"])

    plan = service.inspect(archive)
    report = service.import_project(plan, _person_map(), ImportOptions(target_vcs_server_id="vps"))
    assert report.success, report.message

    logs = []
    while not events.empty():
        kind, payload = events.get_nowait()
        if kind == "log":
            logs.append(str(payload))
    joined = "\n".join(logs)
    for expected in ("Kitsu project", "Studio resources", "Entities", "Tasks ready", "Comments ready", "team"):
        assert expected in joined, expected
    assert report.phases


# ---------------------------------------------------------------------------
# Repository probe diagnostics
# ---------------------------------------------------------------------------
def _fake_server_command(returncode=0, stdout="", stderr=""):
    def fake(server, inner):
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)

    return fake


def test_probe_missing_only_when_directory_absent(tmp_path, monkeypatch):
    service = KitsuImportService(
        FakeKitsu(), config_factory=FakeConfig(tmp_path), nas_manager=FakeNas(tmp_path)
    )
    plan = service.inspect(_build_archive(tmp_path))

    monkeypatch.setattr(service, "_repo_dir_exists", lambda s, p: False)
    assert service.probe_repository(plan, "vps")["state"] == "missing"

    monkeypatch.setattr(service, "_repo_dir_exists", lambda s, p: None)
    status = service.probe_repository(plan, "vps")
    assert status["state"] == "unknown"
    assert "reached" in status["diagnostics"]["reason"]


def test_probe_unreadable_repo_is_unknown_not_missing(tmp_path, monkeypatch):
    service = KitsuImportService(
        FakeKitsu(), config_factory=FakeConfig(tmp_path), nas_manager=FakeNas(tmp_path)
    )
    plan = service.inspect(_build_archive(tmp_path))

    monkeypatch.setattr(service, "_repo_dir_exists", lambda s, p: True)
    monkeypatch.setattr(
        service, "_server_command", _fake_server_command(returncode=1, stderr="svn: E170000")
    )
    status = service.probe_repository(plan, "vps")

    assert status["state"] == "unknown"
    diagnostics = status["diagnostics"]
    assert diagnostics["returncode"] == 1
    assert "svn ls" in diagnostics["command"]
    assert "E170000" in diagnostics["stderr"]
    assert diagnostics["repo_path"].endswith("/neon")
    assert diagnostics["log"]


def test_probe_reports_mode_url_mismatch(tmp_path, monkeypatch):
    service = KitsuImportService(
        FakeKitsu(), config_factory=FakeConfig(tmp_path), nas_manager=FakeNas(tmp_path)
    )
    plan = service.inspect(_build_archive(tmp_path))
    server = VCSServer(id="default", name="Default", repository_url="svn://academia-core")
    monkeypatch.setattr(service, "_target_server", lambda _sid: server)

    status = service.probe_repository(plan, "default")

    assert status["state"] == "unknown"
    diagnostics = status["diagnostics"]
    assert diagnostics["declared_mode"] == "local_docker"
    assert diagnostics["url_mode"] == "remote_ssh"
    assert diagnostics["effective_mode"] == "remote_ssh"
    assert "implies" in diagnostics["mismatch"]
    assert diagnostics["remote"]["host"] == "academia-core"
