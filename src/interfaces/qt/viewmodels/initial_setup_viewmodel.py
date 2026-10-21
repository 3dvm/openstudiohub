# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/viewmodels/initial_setup_viewmodel.py
# Architectural role: MVVM ViewModel / machine initial setup
# =========================================================================================

"""ViewModel for the Seed -> SVN -> Projects initial setup wizard."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal

from src.application.services.initial_setup_service import InitialSetupService, SeedPreview
from src.infrastructure.vcs.svn_client import (
    MANUAL_INSTALL_MESSAGE,
    SvnClientProvisioner,
    SvnClientStatus,
)
from src.interfaces.qt.viewmodels.base_viewmodel import BaseViewModel, StatusSink
from src.interfaces.qt.workers.setup_workers import DetectSvnClientWorker
from src.interfaces.qt.workers.worker_manager import WorkerManager


class InitialSetupViewModel(BaseViewModel):
    seed_validated = Signal(object)  # SeedPreview
    seed_error = Signal(str)
    svn_status_ready = Signal(object)  # SvnClientStatus
    projects_validated = Signal(str)  # absolute path
    projects_error = Signal(str)
    setup_finished = Signal(bool, str)

    def __init__(
        self,
        setup_service: InitialSetupService,
        config_factory=None,
        status_sink: StatusSink | None = None,
        parent=None,
    ) -> None:
        super().__init__(status_sink, parent)
        self.setup_service = setup_service
        self.config_factory = config_factory
        self.workers = WorkerManager(self)
        self.provisioner = SvnClientProvisioner()
        self.seed_path: Optional[Path] = None
        self.seed_preview: Optional[SeedPreview] = None
        self.svn_status: Optional[SvnClientStatus] = None
        self.projects_dir: Optional[Path] = None
        self._resume_mode = False
        self._current_status = None
        self._prepare_resume_mode()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def manual_install_message(self) -> str:
        return self.provisioner.manual_message() or MANUAL_INSTALL_MESSAGE

    def download_available(self) -> bool:
        return self.provisioner.download_available()

    @property
    def resume_mode(self) -> bool:
        """True when the seed is already applied and only local paths need repair."""
        return self._resume_mode

    def _prepare_resume_mode(self) -> None:
        try:
            self._current_status = self.setup_service.status()
        except Exception:  # noqa: BLE001
            self._current_status = None
            return
        if not self._current_status.has_studio_seed or not self._current_status.has_projects_root:
            return
        self._resume_mode = True
        getter = getattr(self.config_factory, "get_workspace_root", None)
        if callable(getter):
            try:
                self.projects_dir = Path(getter())
            except Exception:  # noqa: BLE001
                self.projects_dir = None

    def svn_required(self) -> bool:
        if self._resume_mode and self._current_status is not None:
            return self._current_status.svn_required
        if self.seed_preview is not None:
            return self.seed_preview.svn_required
        return self.setup_service.status().svn_required

    def can_finish(self) -> bool:
        if self._resume_mode:
            if self.projects_dir is None:
                return False
            if self.svn_required() and not (
                self.svn_status is not None and self.svn_status.meets_minimum
            ):
                return False
            return True
        if self.seed_path is None or self.seed_preview is None:
            return False
        if self.projects_dir is None:
            return False
        if self.svn_required() and not (
            self.svn_status is not None and self.svn_status.meets_minimum
        ):
            return False
        return True

    def configured_svn_path(self) -> str:
        getter = getattr(self.config_factory, "get_svn_cli_path", None)
        if callable(getter):
            try:
                return str(getter() or "")
            except Exception:  # noqa: BLE001
                return ""
        return ""

    # ------------------------------------------------------------------
    # Seed
    # ------------------------------------------------------------------
    def validate_seed(self, seed_path: Path) -> bool:
        ok, preview, error = self.setup_service.read_seed(Path(seed_path))
        if not ok or preview is None:
            self.seed_path = None
            self.seed_preview = None
            self.seed_error.emit(error or "The Studio Seed could not be read.")
            return False
        self.seed_path = Path(seed_path)
        self.seed_preview = preview
        self._resume_mode = False
        self.seed_validated.emit(preview)
        return True

    # ------------------------------------------------------------------
    # SVN client
    # ------------------------------------------------------------------
    def check_svn(self) -> None:
        if self.workers.is_running("svn_detect"):
            return
        worker = DetectSvnClientWorker(self.configured_svn_path())
        worker.finished_check.connect(self._on_svn_checked)
        self.workers.start("svn_detect", worker)

    def _on_svn_checked(self, status: SvnClientStatus) -> None:
        self.svn_status = status
        self.svn_status_ready.emit(status)

    def download_and_install_svn(self) -> tuple[bool, str]:
        return self.provisioner.download_and_install()

    # ------------------------------------------------------------------
    # Projects folder
    # ------------------------------------------------------------------
    def validate_projects_dir(self, path: Path, *, create: bool = False) -> bool:
        candidate = Path(path).expanduser()
        if create and not candidate.exists():
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                self.projects_error.emit(f"The projects folder could not be created: {error}")
                return False
        ok, error = self.setup_service.validate_projects_dir(candidate)
        if not ok:
            self.projects_dir = None
            self.projects_error.emit(error)
            return False
        self.projects_dir = candidate
        self.projects_validated.emit(str(candidate))
        return True

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    def finish(self) -> None:
        if not self.can_finish():
            self.setup_finished.emit(False, "Complete the required steps before finishing.")
            return
        svn_path = self.svn_status.path if self.svn_status is not None else ""
        if self._resume_mode:
            ok, message = self.setup_service.apply_existing(
                self.projects_dir,
                svn_path,
            )
        else:
            ok, message = self.setup_service.apply(
                self.seed_path,
                self.projects_dir,
                svn_path,
            )
        if ok:
            self.report_status(message, "green")
        else:
            self.report_status(message, "red")
        self.setup_finished.emit(ok, message)
