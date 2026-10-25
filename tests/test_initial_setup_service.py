"""Unit tests for the machine initial setup service."""

from pathlib import Path
from types import SimpleNamespace

from src.application.services.initial_setup_service import InitialSetupService
from src.infrastructure.vcs.svn_client import SvnClientStatus


class FakeConfig:
    def __init__(
        self,
        *,
        kitsu_url: str = "https://kitsu.example.com",
        has_root: bool = True,
        adapter: str = "svn",
        svn_path: str = "",
        seed_payload: dict | None = None,
        apply_ok: bool = True,
    ) -> None:
        self.kitsu_url = kitsu_url
        self.has_root = has_root
        self.adapter = adapter
        self.svn_path = svn_path
        self.seed_payload = seed_payload or {
            "studio_profile": {"name": "Studio"},
            "kitsu_production": {"api_url": kitsu_url},
            "vcs_engine": {"servers": [{"id": "svn", "adapter": adapter}]},
        }
        self.apply_ok = apply_ok
        self.applied = None

    def get_kitsu_api_url(self) -> str:
        return self.kitsu_url

    def has_local_workspace_root(self) -> bool:
        return self.has_root

    def get_vcs_servers(self):
        return SimpleNamespace(
            servers=[SimpleNamespace(is_enabled=True, adapter=self.adapter)]
        )

    def get_raw_config(self) -> dict:
        return {"vcs_engine": {"active_adapter": self.adapter}}

    def get_svn_cli_path(self) -> str:
        return self.svn_path

    def read_seed_payload(self, _path):
        return True, self.seed_payload, ""

    def apply_initial_setup(self, seed_path, projects_dir, svn_cli_path=""):
        self.applied = (Path(seed_path), Path(projects_dir), svn_cli_path)
        return self.apply_ok, "saved" if self.apply_ok else "failed"

    def apply_local_paths(self, projects_dir, svn_cli_path=""):
        self.applied = (None, Path(projects_dir), svn_cli_path)
        return self.apply_ok


def _status(meets_minimum: bool = True) -> SvnClientStatus:
    return SvnClientStatus(
        found=True,
        path="/usr/bin/svn",
        version=(1, 14, 5),
        version_text="1.14.5",
        meets_minimum=meets_minimum,
        message="ok" if meets_minimum else "Subversion 1.8 is too old.",
    )


def test_status_requires_setup_when_svn_is_missing(tmp_path):
    config = FakeConfig()
    service = InitialSetupService(config, svn_detector=lambda _path="": _status(False))

    status = service.status()

    assert status.has_studio_seed is True
    assert status.has_projects_root is True
    assert status.svn_required is True
    assert status.needs_setup is True
    assert any("too old" in reason for reason in status.reasons)


def test_status_is_complete_when_everything_is_present():
    config = FakeConfig()
    service = InitialSetupService(config, svn_detector=lambda _path="": _status(True))

    status = service.status()

    assert status.needs_setup is False
    assert status.reasons == ()


def test_status_does_not_require_svn_when_vcs_is_disabled():
    config = FakeConfig(adapter="none")
    service = InitialSetupService(config, svn_detector=lambda _path="": _status(False))

    status = service.status()

    assert status.svn_required is False
    assert status.needs_setup is False


def test_svn_required_for_payload_handles_servers_and_legacy_keys():
    assert InitialSetupService.svn_required_for_payload(
        {"vcs_engine": {"servers": [{"adapter": "svn"}]}}
    ) is True
    assert InitialSetupService.svn_required_for_payload(
        {"vcs_engine": {"servers": [{"adapter": "none"}]}}
    ) is False
    assert InitialSetupService.svn_required_for_payload(
        {"vcs_engine": {"active_adapter": "svn"}}
    ) is True


def test_validate_projects_dir_checks_existence_and_writability(tmp_path):
    service = InitialSetupService(FakeConfig(), svn_detector=lambda _path="": _status(True))

    ok, _ = service.validate_projects_dir(tmp_path)
    assert ok is True

    missing = tmp_path / "missing"
    ok, message = service.validate_projects_dir(missing)
    assert ok is False
    assert "does not exist" in message


def test_apply_blocks_when_svn_is_required_but_missing(tmp_path):
    config = FakeConfig()
    service = InitialSetupService(config, svn_detector=lambda _path="": _status(False))

    ok, message = service.apply(tmp_path / "seed.seed", tmp_path)

    assert ok is False
    assert "too old" in message
    assert config.applied is None


def test_apply_delegates_to_config_factory(tmp_path):
    config = FakeConfig(adapter="none")
    service = InitialSetupService(config, svn_detector=lambda _path="": _status(True))
    seed = tmp_path / "studio.seed"
    seed.write_text("seed", encoding="utf-8")

    ok, message = service.apply(seed, tmp_path, "/usr/bin/svn")

    assert ok is True
    assert "successfully" in message
    assert config.applied == (seed, tmp_path, "/usr/bin/svn")


def test_apply_existing_updates_paths_without_a_seed(tmp_path):
    config = FakeConfig()
    service = InitialSetupService(config, svn_detector=lambda _path="": _status(True))

    ok, message = service.apply_existing(tmp_path, "/usr/bin/svn")

    assert ok is True
    assert "successfully" in message
    assert config.applied == (None, tmp_path, "/usr/bin/svn")
