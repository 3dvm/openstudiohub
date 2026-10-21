"""Unit tests for the initial setup wizard ViewModel."""

from pathlib import Path

from src.application.services.initial_setup_service import SeedPreview
from src.infrastructure.vcs.svn_client import SvnClientStatus
from src.interfaces.qt.viewmodels.initial_setup_viewmodel import InitialSetupViewModel


class FakeSetupService:
    def __init__(self, *, svn_required: bool = True, apply_ok: bool = True) -> None:
        self.svn_required = svn_required
        self.apply_ok = apply_ok
        self.applied = None
        self.applied_existing = None
        self.payload = {
            "studio_profile": {"name": "Studio"},
            "kitsu_production": {"api_url": "https://kitsu.example.com"},
            "infrastructure_topology": {"vault_dir": "openstudio_vault"},
            "vcs_engine": {"servers": [{"adapter": "svn" if svn_required else "none"}]},
        }

    def read_seed(self, _path):
        preview = SeedPreview(
            payload=self.payload,
            studio_name="Studio",
            kitsu_url="https://kitsu.example.com",
            vcs_servers=1,
            topography={},
            svn_required=self.svn_required,
        )
        return True, preview, ""

    def validate_projects_dir(self, path):
        if Path(path).is_dir():
            return True, ""
        return False, "The selected projects folder does not exist."

    def apply(self, seed_path, projects_dir, svn_cli_path=""):
        self.applied = (Path(seed_path), Path(projects_dir), svn_cli_path)
        return self.apply_ok, "saved" if self.apply_ok else "failed"

    def apply_existing(self, projects_dir, svn_cli_path=""):
        self.applied_existing = (Path(projects_dir), svn_cli_path)
        return self.apply_ok, "saved" if self.apply_ok else "failed"

    def status(self):
        return type(
            "Status",
            (),
            {
                "svn_required": self.svn_required,
                "needs_setup": True,
                "has_studio_seed": True,
                "has_projects_root": True,
            },
        )()


class FakeConfig:
    def get_svn_cli_path(self) -> str:
        return ""

    def get_workspace_root(self) -> Path:
        return Path("/tmp/projects")

    def has_local_workspace_root(self) -> bool:
        return True

    def get_vault_dir(self) -> str:
        return "openstudio_vault"


def test_validate_seed_emits_preview(tmp_path, qapp):
    vm = InitialSetupViewModel(FakeSetupService(), FakeConfig())
    received = []
    vm.seed_validated.connect(received.append)
    seed = tmp_path / "studio.seed"
    seed.write_text("seed", encoding="utf-8")

    assert vm.validate_seed(seed) is True
    assert received
    assert received[0].studio_name == "Studio"
    assert vm.seed_path == seed


def test_finish_requires_svn_when_seed_uses_it(tmp_path, qapp):
    vm = InitialSetupViewModel(FakeSetupService(svn_required=True), FakeConfig())
    seed = tmp_path / "studio.seed"
    seed.write_text("seed", encoding="utf-8")
    vm.validate_seed(seed)
    vm.validate_projects_dir(tmp_path)
    received = []
    vm.setup_finished.connect(lambda ok, message: received.append((ok, message)))

    vm.finish()

    assert received == [(False, "Complete the required steps before finishing.")]
    assert vm.can_finish() is False


def test_finish_applies_when_all_requirements_are_met(tmp_path, qapp):
    service = FakeSetupService(svn_required=True)
    vm = InitialSetupViewModel(service, FakeConfig())
    seed = tmp_path / "studio.seed"
    seed.write_text("seed", encoding="utf-8")
    vm.validate_seed(seed)
    vm.validate_projects_dir(tmp_path)
    vm._on_svn_checked(
        SvnClientStatus(
            found=True,
            path="/usr/bin/svn",
            version=(1, 14, 5),
            version_text="1.14.5",
            meets_minimum=True,
            message="ok",
        )
    )
    received = []
    vm.setup_finished.connect(lambda ok, message: received.append((ok, message)))

    assert vm.can_finish() is True
    vm.finish()

    assert received == [(True, "saved")]
    assert service.applied == (seed, tmp_path, "/usr/bin/svn")


def test_validate_projects_dir_creates_folder_when_requested(tmp_path, qapp):
    vm = InitialSetupViewModel(FakeSetupService(svn_required=False), FakeConfig())
    target = tmp_path / "new_projects"
    received = []
    vm.projects_validated.connect(received.append)

    assert vm.validate_projects_dir(target, create=True) is True
    assert target.is_dir()
    assert received == [str(target)]


def test_resume_mode_only_repairs_local_paths(tmp_path, qapp):
    service = FakeSetupService(svn_required=True)
    vm = InitialSetupViewModel(service, FakeConfig())
    assert vm.resume_mode is True
    vm._on_svn_checked(
        SvnClientStatus(
            found=True,
            path="/usr/bin/svn",
            version=(1, 14, 5),
            version_text="1.14.5",
            meets_minimum=True,
            message="ok",
        )
    )
    received = []
    vm.setup_finished.connect(lambda ok, message: received.append((ok, message)))

    vm.finish()

    assert received == [(True, "saved")]
    assert service.applied_existing == (Path("/tmp/projects"), "/usr/bin/svn")
    assert service.applied is None
