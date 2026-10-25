"""Unit tests for the ProjectListViewModel (Qt-backed)."""

import json
import os
from pathlib import Path

from src.application.services.installation_service import InstallationService
from src.domain.identity.value_objects import Role
from src.interfaces.qt.viewmodels.project_list_viewmodel import ProjectListViewModel


class FakeProductionService:
    def list_open_projects(self):
        return []

    def download_project_thumbnail(self, *args):
        return None


class FakeAuthService:
    def current_role(self):
        return Role.ARTIST

    def access_token(self):
        return ""

    @property
    def host(self):
        return ""


class FakeConfigFactory:
    def __init__(self, nas_dir):
        self._nas_dir = nas_dir

    def get_vfs_local_name(self):
        return "local"

    def get_vfs_svn_name(self):
        return "svn"

    def get_workspace_root(self):
        return self._nas_dir

    def get_raw_config(self):
        return {}


class DummyHealth:
    def __init__(self, is_nas=False, has_kitsu=True, has_bp=False, has_valid_bp=None, is_local=False) -> None:
        self.is_accessible_on_nas = is_nas
        self.has_kitsu_project = has_kitsu
        self.has_blueprint = has_bp
        self.has_valid_blueprint = has_bp if has_valid_bp is None else has_valid_bp
        self.is_installed_locally = is_local

class DummyBlueprint:
    def __init__(self, version="Blender"):
        self.blender_version = version

class DummyHubProject:
    def __init__(self, health, blueprint=None):
        self.health = health
        self.blueprint = blueprint

class FakeAuditService:
    def audit_project(self, project_name: str, kitsu_id: str = ""):
        if project_name == "Neon":
            health = DummyHealth(is_nas=True, has_kitsu=True, has_bp=True, is_local=True)
            return DummyHubProject(health, DummyBlueprint("5.1.2"))

        return DummyHubProject(DummyHealth(is_nas=False, has_kitsu=True, has_bp=False, is_local=False))

def _make_vm(tmp_path):
    nas_dir = tmp_path / "workspace"
    nas_dir.mkdir(exist_ok=True)
    installation_service = InstallationService(FakeConfigFactory(nas_dir), nas_dir / "vault")
    return ProjectListViewModel(
        production_service=FakeProductionService(),
        auth_service=FakeAuthService(),
        config_factory=FakeConfigFactory(nas_dir),
        installation_service=installation_service,
        audit_service=FakeAuditService(),
        read_vcs_credentials=True,
        nas_dir=nas_dir,
        open_kitsu_callback=lambda url: None,
        open_watchtower_callback=lambda project_dir: None,
        instance_lock_callback=lambda active: None,
    )


def test_compute_status_not_mounted(tmp_path, qapp):
    vm = _make_vm(tmp_path)
    status = vm.compute_status({"name": "Ghost Project"})

    assert status["project_dir"] is None
    assert status["is_installed"] is False
    assert status["is_corrupted"] is True
    assert status["badge_text"] == "Not Mounted"


def test_compute_status_installed(tmp_path, qapp):
    nas_dir = tmp_path / "workspace"
    project = nas_dir / "Neon"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text("{}")
    (project / "svn").mkdir()
    (project / "pipeline").mkdir()
    (project / "pipeline" / "project_init.json").write_text('{"blender_version": "5.1.2"}')

    vm = _make_vm(tmp_path)
    status = vm.compute_status({"name": "Neon"})

    assert status["is_installed"] is True
    assert status["is_corrupted"] is False
    assert status["badge_text"] == "5.1.2"
    assert status["project_dir"] == project


def test_compute_status_missing_blueprint(tmp_path, qapp):
    from src.domain.workspace.entities import ERROR_MISSING_BLUEPRINT

    nas_dir = tmp_path / "workspace"
    nas_dir.mkdir(exist_ok=True)

    class MissingBlueprintAuditService:
        def audit_project(self, project_name: str, kitsu_id: str = ""):
            return DummyHubProject(
                DummyHealth(is_nas=True, has_kitsu=True, has_bp=False, is_local=False)
            )

    vm = ProjectListViewModel(
        production_service=FakeProductionService(),
        auth_service=FakeAuthService(),
        config_factory=FakeConfigFactory(nas_dir),
        installation_service=InstallationService(FakeConfigFactory(nas_dir), nas_dir / "vault"),
        audit_service=MissingBlueprintAuditService(),
        read_vcs_credentials=True,
        nas_dir=nas_dir,
        open_kitsu_callback=lambda url: None,
        open_watchtower_callback=lambda project_dir: None,
        instance_lock_callback=lambda active: None,
    )

    status = vm.compute_status({"name": "Broken", "id": "p1"})

    assert status["is_corrupted"] is True
    assert status["error_code"] == ERROR_MISSING_BLUEPRINT


def test_compute_status_invalid_blueprint(tmp_path, qapp):
    from src.domain.workspace.entities import ERROR_INVALID_BLUEPRINT

    nas_dir = tmp_path / "workspace"
    nas_dir.mkdir(exist_ok=True)

    class InvalidBlueprintAuditService:
        def audit_project(self, project_name: str, kitsu_id: str = ""):
            return DummyHubProject(
                DummyHealth(is_nas=True, has_kitsu=True, has_bp=True, has_valid_bp=False, is_local=False)
            )

    vm = ProjectListViewModel(
        production_service=FakeProductionService(),
        auth_service=FakeAuthService(),
        config_factory=FakeConfigFactory(nas_dir),
        installation_service=InstallationService(FakeConfigFactory(nas_dir), nas_dir / "vault"),
        audit_service=InvalidBlueprintAuditService(),
        read_vcs_credentials=True,
        nas_dir=nas_dir,
        open_kitsu_callback=lambda url: None,
        open_watchtower_callback=lambda project_dir: None,
        instance_lock_callback=lambda active: None,
    )

    status = vm.compute_status({"name": "Broken", "id": "p1"})

    assert status["is_corrupted"] is True
    assert status["error_code"] == ERROR_INVALID_BLUEPRINT


def _write_blueprint(project_dir, payload: dict) -> None:
    pipeline = project_dir / "pipeline"
    pipeline.mkdir(parents=True, exist_ok=True)
    (pipeline / "project_init.json").write_text(json.dumps(payload))


def test_project_config_reports_blueprint_and_splash(tmp_path, qapp):
    nas_dir = tmp_path / "workspace"
    project = nas_dir / "Neon"
    (project / "pipeline").mkdir(parents=True)
    (project / "pipeline" / "splash.png").write_bytes(b"png")
    _write_blueprint(project, {
        "project_name": "Neon",
        "topography_signature": {"vfs_pipeline": "pipeline", "vfs_local": "local"},
    })

    vm = _make_vm(tmp_path)
    config = vm.project_config("Neon", "p1")

    assert config["is_mounted"] is True
    assert config["bound_server_id"] == ""
    assert config["blueprint"]["project_name"] == "Neon"
    assert config["splash_path"].endswith("pipeline" + os.sep + "splash.png")


def test_save_project_config_updates_blueprint_and_splash(tmp_path, qapp):
    nas_dir = tmp_path / "workspace"
    project = nas_dir / "Neon"
    project.mkdir(parents=True)
    _write_blueprint(project, {
        "project_name": "Neon",
        "kitsu_project_id": "p1",
        "template": "Old",
        "blender_version": "3.6",
        "dependencies": {"templates": {"Old": "1.0"}},
        "topography_signature": {"vfs_pipeline": "pipeline", "vfs_local": "local"},
    })

    splash_source = tmp_path / "new_splash.png"
    splash_source.write_bytes(b"png")

    vm = _make_vm(tmp_path)
    ok, message = vm.save_project_config(project, "p1", {
        "server_id": "",
        "blender_version": "4.2",
        "template": "New",
        "dependencies": {"templates": {"New": "1.0"}},
        "addon_configuration": {},
        "splash_source_path": str(splash_source),
    })

    assert ok is True
    assert "saved" in message.lower()

    saved = json.loads((project / "pipeline" / "project_init.json").read_text())
    assert saved["blender_version"] == "4.2"
    assert saved["template"] == "New"
    assert saved["vcs_server_id"] == ""
    assert (project / "pipeline" / "splash.png").exists()


def test_probe_project_vcs_without_server(tmp_path, qapp):
    vm = _make_vm(tmp_path)
    ok, message = vm.probe_project_vcs("", "Neon")
    assert ok is False
    assert "select a vcs server" in message.lower()


def test_export_without_dump_skips_vcs_precheck(tmp_path, qapp, monkeypatch):
    vm = _make_vm(tmp_path)
    started = []
    monkeypatch.setattr(vm, "export_project", lambda *args: started.append(args))

    vm.request_export("p1", "Neon", "/tmp/out", {"embed_svn_dump": False})

    assert started and started[0][1] == "Neon"


def test_export_precheck_warns_on_uncommitted_files(tmp_path, qapp, monkeypatch):
    vm = _make_vm(tmp_path)
    warned = []
    started = []
    vm.export_uncommitted_found.connect(lambda name, changes: warned.append((name, changes)))
    monkeypatch.setattr(vm, "export_project", lambda *args: started.append(args))

    # No changes: export proceeds.
    vm._pending_export = ("p1", "Neon", "/tmp/out", {"embed_svn_dump": True})
    vm._on_export_precheck("__export__", [])
    assert started and not warned

    # Changes: the UI is asked to publish first.
    started.clear()
    vm._pending_export = ("p1", "Neon", "/tmp/out", {"embed_svn_dump": True})
    vm._on_export_precheck("__export__", [object()])
    assert warned and warned[0][0] == "Neon" and not started

    # "Export anyway" resumes with the pending request.
    vm.export_anyway()
    assert started


def test_publish_scan_ready_emits_changes_or_clean(tmp_path, qapp):
    vm = _make_vm(tmp_path)
    changes = []
    clean = []
    vm.publish_changes_ready.connect(lambda name, items: changes.append((name, items)))
    vm.publish_up_to_date.connect(lambda name: clean.append(name))

    vm._on_publish_scan_ready("Neon", [object()])
    assert changes and changes[-1][0] == "Neon" and not clean

    vm._on_publish_scan_ready("Neon", [])
    assert clean == ["Neon"]


def test_reset_finished_emits_signal(tmp_path, qapp):
    vm = _make_vm(tmp_path)
    received = []
    vm.reset_finished.connect(lambda name, ok, msg: received.append((name, ok, msg)))

    vm._on_reset_finished("Neon", True, "Working copy reset.")

    assert received == [("Neon", True, "Working copy reset.")]


def test_reset_working_copy_worker_removes_then_installs(tmp_path, qapp):
    from src.interfaces.qt.workers.project_list_workers import ResetWorkingCopyWorker

    class FakeInstall:
        def __init__(self):
            self.calls = []

        def instalar_entorno(
            self, project_root, vcs_user, vcs_pwd, status_callback, user_role,
            task_metadata=None, progress_callback=None,
        ):
            self.calls.append((Path(project_root), vcs_user, vcs_pwd, user_role))
            # Simulate the checkout re-materializing the working copy.
            (Path(project_root) / "svn" / "pro").mkdir(parents=True, exist_ok=True)
            return True, "installed"

    project_root = tmp_path / "neon"
    stale = project_root / "svn" / "pro" / "stale.blend"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"x")

    install = FakeInstall()
    worker = ResetWorkingCopyWorker(install, project_root, "svn", "u", "p", "td")
    results = []
    worker.finished_reset.connect(lambda ok, msg: results.append((ok, msg)))

    worker.run()

    assert results == [(True, "installed")]
    assert not stale.exists()
    assert install.calls and install.calls[0][0] == project_root
