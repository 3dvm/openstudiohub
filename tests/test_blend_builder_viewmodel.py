"""Unit tests for the BlendBuilderViewModel install gate."""

from src.interfaces.qt.viewmodels.blend_builder_viewmodel import BlendBuilderViewModel


class FakeConfigFactory:
    def __init__(self, root):
        self._root = root

    def get_workspace_root(self):
        return self._root

    def get_vault_path(self):
        return self._root / "vault"

    def get_vfs_local_name(self):
        return "local"

    def get_vfs_svn_name(self):
        return "svn"

    def get_vfs_pipeline_name(self):
        return "pipeline"

    def get_vfs_shared_name(self):
        return "shared"


class FakeInstallationService:
    def __init__(self, installed: bool) -> None:
        self.installed = installed
        self.checked = []

    def verify_installation(self, project_root):
        self.checked.append(project_root)
        return self.installed


def _make_vm(tmp_path, installed: bool):
    installation = FakeInstallationService(installed)
    vm = BlendBuilderViewModel(
        production_service=None,
        config_factory=FakeConfigFactory(tmp_path),
        credential_vault=None,
        installation_service=installation,
    )
    vm.project_map = {"MIDEQ_promo": "p1"}
    return vm, installation


def test_gate_false_without_project(tmp_path, qapp):
    vm, _ = _make_vm(tmp_path, installed=False)
    assert vm.is_current_project_installed() is False


def test_gate_reflects_installation_state(tmp_path, qapp):
    vm, installation = _make_vm(tmp_path, installed=False)
    vm.select_project("MIDEQ_promo")

    assert vm.is_current_project_installed() is False
    assert installation.checked[-1] == tmp_path / "mideq_promo"

    installation.installed = True
    assert vm.is_current_project_installed() is True


def test_gate_defaults_to_true_without_service(tmp_path, qapp):
    vm = BlendBuilderViewModel(
        production_service=None,
        config_factory=FakeConfigFactory(tmp_path),
        credential_vault=None,
    )
    vm.project_map = {"MIDEQ_promo": "p1"}
    vm.select_project("MIDEQ_promo")

    assert vm.is_current_project_installed() is True


def test_select_project_is_case_insensitive(tmp_path, qapp):
    vm, _ = _make_vm(tmp_path, installed=True)
    vm.select_project("mideq_promo")

    assert vm.current_project_id == "p1"
    assert vm.current_project_name == "MIDEQ_promo"


def test_publish_scan_emits_dialog_or_clean(tmp_path, qapp):
    vm, _ = _make_vm(tmp_path, installed=True)
    counts = []
    requested = []
    clean = []
    vm.project_changes_ready.connect(lambda changes: counts.append(len(changes)))
    vm.project_publish_dialog_requested.connect(lambda changes: requested.append(changes))
    vm.project_publish_up_to_date.connect(lambda: clean.append(True))

    # Non-interactive scan only updates the count.
    vm._on_project_changes_ready("__project__", [object()])
    assert counts[-1] == 1
    assert not requested

    # Interactive with changes → dialog requested.
    vm._publish_scan_interactive = True
    vm._on_project_changes_ready("__project__", [object(), object()])
    assert counts[-1] == 2
    assert requested and len(requested[-1]) == 2

    # Interactive clean → up-to-date notification.
    vm._publish_scan_interactive = True
    vm._on_project_changes_ready("__project__", [])
    assert clean


def test_publish_scan_clean_is_silent_when_not_notifying(tmp_path, qapp):
    vm, _ = _make_vm(tmp_path, installed=True)
    clean = []
    vm.project_publish_up_to_date.connect(lambda: clean.append(True))

    vm._publish_scan_interactive = True
    vm._publish_scan_notify_clean = False
    vm._on_project_changes_ready("__project__", [])

    assert not clean


def test_select_project_clears_state_when_missing(tmp_path, qapp):
    vm, _ = _make_vm(tmp_path, installed=True)
    vm.select_project("MIDEQ_promo")
    vm.select_project("does-not-exist")

    assert vm.current_project_id is None
    assert vm.current_project_name == ""
