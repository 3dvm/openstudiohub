"""Unit tests for the InstallationService verification helper."""

from src.application.services.installation_service import InstallationService


class FakeConfigFactory:
    def get_vfs_local_name(self):
        return "local"

    def get_vfs_svn_name(self):
        return "svn"


def _make_service(tmp_path):
    return InstallationService(FakeConfigFactory(), tmp_path / "vault")


def test_verify_installation_true(tmp_path):
    project = tmp_path / "project"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text("{}")
    (project / "svn").mkdir()

    service = _make_service(tmp_path)
    assert service.verify_installation(project) is True


def test_verify_installation_false_when_config_missing(tmp_path):
    project = tmp_path / "project"
    (project / "svn").mkdir(parents=True)

    service = _make_service(tmp_path)
    assert service.verify_installation(project) is False


def test_verify_installation_false_when_vcs_missing(tmp_path):
    project = tmp_path / "project"
    (project / "local").mkdir(parents=True)
    (project / "local" / "project_config.json").write_text("{}")

    service = _make_service(tmp_path)
    assert service.verify_installation(project) is False


def test_get_os_info_shape():
    os_name, ext = InstallationService._get_os_info()
    assert os_name in {"linux", "windows", "macos"}
    assert ext in {"tar.xz", "zip", "dmg"}
