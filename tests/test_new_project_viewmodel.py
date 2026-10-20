"""Unit tests for the worker lifecycle management (WorkerManager).

Guards the regression where Qt deletes a finished worker's C++ object while the
owner still holds a Python reference, making ``active_workers()`` raise
``RuntimeError: Internal C++ object ... already deleted``.
"""

from pathlib import Path
from types import SimpleNamespace

from src.application.credential_vault import CredentialVault
from src.application.services.project_creation_service import ProjectCreationService
from src.domain.workspace.topography import WorkspaceTopography
from src.interfaces.qt.viewmodels.new_project_viewmodel import NewProjectViewModel
from src.interfaces.qt.workers.worker_manager import WorkerManager


class _DeletedWorker:
    """Mimics a worker whose C++ object was deleted by Qt."""

    def isRunning(self):
        raise RuntimeError("libshiboken: Internal C++ object already deleted.")


class _RunningWorker:
    def __init__(self) -> None:
        self.deleted = False

    def isRunning(self):
        return True

    def deleteLater(self):
        self.deleted = True


class _FakeConfig:
    def get_workspace_root(self):
        return Path("/tmp")

    def get_topography(self):
        return WorkspaceTopography()

    def get_vcs_repository_url(self):
        return ""

    def get_vcs_adapter_type(self):
        return "none"


def _make_vm():
    vault = SimpleNamespace(load_inventory=lambda: {})
    return NewProjectViewModel(_FakeConfig(), production_service=None, vault_service=vault)


def test_active_workers_skips_deleted_cpp_objects():
    vm = _make_vm()
    vm.workers._workers["a"] = _DeletedWorker()
    vm.workers._workers["b"] = _DeletedWorker()

    assert vm.active_workers() == []


def test_active_workers_returns_running_workers():
    vm = _make_vm()
    running = _RunningWorker()
    vm.workers._workers["retry"] = running

    assert vm.active_workers() == [running]


def test_manager_finished_clears_reference_and_deletes():
    manager = WorkerManager()
    worker = _RunningWorker()
    manager._workers["k"] = worker

    manager._on_finished("k", worker)

    assert manager.get("k") is None
    assert worker.deleted is True


def _make_vm_with_vault(vault: CredentialVault):
    stub = SimpleNamespace(load_inventory=lambda: {})
    return NewProjectViewModel(
        _FakeConfig(), production_service=None, vault_service=stub, credential_vault=vault
    )


def test_default_creation_service_shares_credential_vault():
    vault = CredentialVault()
    vm = _make_vm_with_vault(vault)

    assert vm.project_creation_service.credential_vault is vault


def test_passphrase_provider_reads_shared_vault():
    vault = CredentialVault()
    vault.save_ssh_passphrase("default", "topsecret")
    vm = _make_vm_with_vault(vault)

    provider = vm.project_creation_service._ssh_passphrase_provider(
        server=SimpleNamespace(id="default")
    )

    assert provider() == "topsecret"


def test_injected_creation_service_is_reused():
    service = ProjectCreationService(_FakeConfig(), credential_vault=CredentialVault())
    vm = NewProjectViewModel(
        _FakeConfig(),
        production_service=None,
        vault_service=SimpleNamespace(load_inventory=lambda: {}),
        project_creation_service=service,
    )

    assert vm.project_creation_service is service


def test_manager_skips_when_worker_already_running():
    manager = WorkerManager()
    manager._workers["k"] = _RunningWorker()

    class _NeverStarted:
        def __init__(self):
            self.started = False

        def isRunning(self):
            return False

        def finished(self):  # pragma: no cover - not reached when skipped
            raise AssertionError("should not be reached")

    assert manager.start("k", _NeverStarted()) is False
