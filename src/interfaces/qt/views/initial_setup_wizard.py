# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/initial_setup_wizard.py
# Architectural role: UI View / machine initial setup wizard (PySide6)
# =========================================================================================

"""Wizard that configures a machine before the Hub can operate.

The wizard covers the Studio Seed, the Subversion client and the local projects
folder. Nothing is persisted until the user presses Finish, so cancelling never
leaves a half-configured machine behind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.application.services.initial_setup_service import SeedPreview
from src.infrastructure.vcs.svn_client import SvnClientStatus
from src.interfaces.qt.viewmodels.initial_setup_viewmodel import InitialSetupViewModel

STEP_TITLES = (
    "Welcome",
    "Studio Seed",
    "SVN Client",
    "Projects Folder",
    "Summary",
)


class InitialSetupWizard(QDialog):
    def __init__(
        self,
        parent,
        viewmodel: InitialSetupViewModel,
        on_finished: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.vm = viewmodel
        self._on_finished = on_finished
        self._step_labels: list[QLabel] = []

        self.setWindowTitle(self.tr("Initial Configuration"))
        self.setObjectName("ViewLoginBase")
        self.setModal(True)
        self.setFixedSize(820, 640)

        self._build_ui()
        self._connect_signals()
        if self.vm.resume_mode:
            self._prepare_projects_page()
            self._set_step(2)
            self.vm.check_svn()
        else:
            self._set_step(0)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("QFrame { background-color: #1F2531; border-right: 1px solid #141820; }")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(24, 28, 24, 28)
        side_layout.setSpacing(14)

        title = QLabel(self.tr("This Machine"))
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #F8FAFC;")
        side_layout.addWidget(title)

        subtitle = QLabel(self.tr("Set up the local configuration required to work with the studio."))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #94A3B8; font-size: 12px;")
        side_layout.addWidget(subtitle)
        side_layout.addSpacing(10)

        for index, title_text in enumerate(STEP_TITLES):
            label = QLabel(f"{index + 1}.  {title_text}")
            label.setStyleSheet("color: #64748B; font-size: 13px; padding: 6px 0;")
            self._step_labels.append(label)
            side_layout.addWidget(label)

        side_layout.addStretch()
        root.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(36, 28, 36, 24)
        content_layout.setSpacing(16)
        root.addWidget(content, stretch=1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_welcome_page())
        self.stack.addWidget(self._build_seed_page())
        self.stack.addWidget(self._build_svn_page())
        self.stack.addWidget(self._build_projects_page())
        self.stack.addWidget(self._build_summary_page())
        content_layout.addWidget(self.stack, stretch=1)

        self.lbl_error = QLabel("")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setStyleSheet("color: #EF4444; font-weight: bold;")
        self.lbl_error.hide()
        content_layout.addWidget(self.lbl_error)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.btn_cancel = QPushButton(self.tr("Cancel"))
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.clicked.connect(self.reject)
        footer.addWidget(self.btn_cancel)
        footer.addStretch()

        self.btn_back = QPushButton(self.tr("Back"))
        self.btn_back.setObjectName("SecondaryButton")
        self.btn_back.clicked.connect(self._go_back)
        footer.addWidget(self.btn_back)

        self.btn_next = QPushButton(self.tr("Next"))
        self.btn_next.setObjectName("PrimaryButton")
        self.btn_next.clicked.connect(self._go_next)
        footer.addWidget(self.btn_next)
        content_layout.addLayout(footer)

    def _page(self, title: str, description: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("CardTitle")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(description)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(lbl_desc)
        return page, layout

    def _build_welcome_page(self) -> QWidget:
        page, layout = self._page(
            self.tr("Initial Configuration"),
            self.tr(
                "This wizard configures this computer. It imports the Studio Seed, "
                "verifies the Subversion client and selects the local projects folder."
            ),
        )

        items = QLabel(
            self.tr(
                "You will need:\n"
                "  •  The Studio Seed file (.seed) provided by the studio.\n"
                "  •  Subversion 1.14 or newer installed on this machine.\n"
                "  •  The local path of the studio projects folder."
            )
        )
        items.setWordWrap(True)
        items.setStyleSheet(
            "background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; "
            "padding: 14px; color: #E2E8F0;"
        )
        layout.addWidget(items)
        layout.addStretch()
        return page

    def _build_seed_page(self) -> QWidget:
        page, layout = self._page(
            self.tr("Studio Seed"),
            self.tr("Select the Studio Seed file. The configuration is only applied when you finish."),
        )

        row = QHBoxLayout()
        self.entry_seed = QLineEdit()
        self.entry_seed.setObjectName("FormInput")
        self.entry_seed.setPlaceholderText(self.tr("Path to the .seed file"))
        self.entry_seed.setFixedHeight(42)
        row.addWidget(self.entry_seed, stretch=1)

        btn_browse = QPushButton(self.tr("Browse..."))
        btn_browse.setObjectName("SecondaryButton")
        btn_browse.clicked.connect(self._browse_seed)
        row.addWidget(btn_browse)
        layout.addLayout(row)

        self.lbl_seed_summary = QLabel("")
        self.lbl_seed_summary.setWordWrap(True)
        self.lbl_seed_summary.setStyleSheet(
            "background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; "
            "padding: 14px; color: #E2E8F0;"
        )
        self.lbl_seed_summary.hide()
        layout.addWidget(self.lbl_seed_summary)
        layout.addStretch()
        return page

    def _build_svn_page(self) -> QWidget:
        page, layout = self._page(
            self.tr("SVN Client"),
            self.tr(
                "The Hub uses the Subversion command-line client. "
                "Subversion 1.14 or newer is required."
            ),
        )

        self.lbl_svn_status = QLabel(self.tr("Checking the local Subversion client..."))
        self.lbl_svn_status.setWordWrap(True)
        self.lbl_svn_status.setStyleSheet(
            "background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; "
            "padding: 14px; color: #E2E8F0;"
        )
        layout.addWidget(self.lbl_svn_status)

        self.lbl_svn_manual = QLabel("")
        self.lbl_svn_manual.setWordWrap(True)
        self.lbl_svn_manual.setStyleSheet("color: #F59E0B; font-size: 12px;")
        self.lbl_svn_manual.hide()
        layout.addWidget(self.lbl_svn_manual)

        actions = QHBoxLayout()
        self.btn_check_svn = QPushButton(self.tr("Check Again"))
        self.btn_check_svn.setObjectName("SecondaryButton")
        self.btn_check_svn.clicked.connect(self.vm.check_svn)
        actions.addWidget(self.btn_check_svn)

        self.btn_download_svn = QPushButton(self.tr("Download and Install in the Hub"))
        self.btn_download_svn.setObjectName("PrimaryButton")
        self.btn_download_svn.clicked.connect(self._download_svn)
        self.btn_download_svn.setVisible(self.vm.download_available())
        actions.addWidget(self.btn_download_svn)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        return page

    def _build_projects_page(self) -> QWidget:
        page, layout = self._page(
            self.tr("Projects Folder"),
            self.tr(
                "Choose the folder where the Hub will create and update project workspaces "
                "on this computer. It must be the local studio projects share (NAS, network "
                "drive or a synced folder), not the SVN server URL."
            ),
        )

        row = QHBoxLayout()
        self.entry_projects = QLineEdit()
        self.entry_projects.setObjectName("FormInput")
        self.entry_projects.setPlaceholderText(self.tr("e.g. /studio/projects or Z:/studio/projects"))
        self.entry_projects.setFixedHeight(42)
        self.entry_projects.textChanged.connect(self._update_vault_label)
        row.addWidget(self.entry_projects, stretch=1)

        btn_browse = QPushButton(self.tr("Browse..."))
        btn_browse.setObjectName("SecondaryButton")
        btn_browse.clicked.connect(self._browse_projects)
        row.addWidget(btn_browse)
        layout.addLayout(row)

        self.lbl_vault = QLabel("")
        self.lbl_vault.setWordWrap(True)
        self.lbl_vault.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(self.lbl_vault)
        layout.addStretch()
        return page

    def _build_summary_page(self) -> QWidget:
        page, layout = self._page(
            self.tr("Summary"),
            self.tr("Review the configuration before applying it to this computer."),
        )

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(
            "background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; "
            "padding: 16px; color: #E2E8F0; line-height: 1.5;"
        )
        layout.addWidget(self.lbl_summary)
        layout.addStretch()
        return page

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        self.vm.seed_validated.connect(self._on_seed_validated)
        self.vm.seed_error.connect(self._show_error)
        self.vm.svn_status_ready.connect(self._on_svn_status)
        self.vm.projects_validated.connect(self._on_projects_validated)
        self.vm.projects_error.connect(self._show_error)
        self.vm.setup_finished.connect(self._on_setup_finished)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _browse_seed(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Studio Seed File"),
            "",
            self.tr("Seed Files (*.seed);;All Files (*)"),
        )
        if not file_path:
            return
        self.entry_seed.setText(file_path)
        self._validate_current_seed()

    def _validate_current_seed(self) -> bool:
        path = self.entry_seed.text().strip()
        if not path:
            self._show_error(self.tr("Select a Studio Seed file."))
            return False
        return self.vm.validate_seed(Path(path))

    def _browse_projects(self) -> None:
        start = self.entry_projects.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Projects Folder"),
            start,
        )
        if directory:
            self.entry_projects.setText(directory)
            self._update_vault_label()

    def _update_vault_label(self) -> None:
        path = self.entry_projects.text().strip()
        if not path:
            self.lbl_vault.setText("")
            return
        vault_dir = "openstudio_vault"
        if self.vm.seed_preview is not None:
            vault_dir = str(
                (self.vm.seed_preview.payload.get("infrastructure_topology") or {}).get(
                    "vault_dir"
                )
                or vault_dir
            )
        else:
            getter = getattr(self.vm.config_factory, "get_vault_dir", None)
            if callable(getter):
                try:
                    vault_dir = str(getter() or vault_dir)
                except Exception:  # noqa: BLE001
                    pass
        self.lbl_vault.setText(
            self.tr("The studio vault will be stored at: {0}").format(
                Path(path) / vault_dir
            )
        )

    def _download_svn(self) -> None:
        ok, message = self.vm.download_and_install_svn()
        if not ok:
            self._show_error(message)

    def _go_back(self) -> None:
        if self.stack.currentIndex() > 0:
            self._set_step(self.stack.currentIndex() - 1)

    def _go_next(self) -> None:
        index = self.stack.currentIndex()
        self._clear_error()

        if index == 0:
            self._set_step(1)
            return

        if index == 1:
            if self.vm.resume_mode and not self.entry_seed.text().strip():
                self._set_step(2)
                self.vm.check_svn()
                return
            if not self._validate_current_seed():
                return
            self._set_step(2)
            self.vm.check_svn()
            return

        if index == 2:
            if self.vm.svn_required() and not (
                self.vm.svn_status is not None and self.vm.svn_status.meets_minimum
            ):
                self._show_error(
                    self.vm.manual_install_message()
                    if self.vm.svn_status is None or not self.vm.svn_status.meets_minimum
                    else self.tr("Subversion 1.14 or newer is required.")
                )
                return
            self._prepare_projects_page()
            self._set_step(3)
            return

        if index == 3:
            if not self._validate_projects():
                return
            self._update_summary()
            self._set_step(4)
            return

        if index == 4:
            self.vm.finish()

    def _prepare_projects_page(self) -> None:
        if self.entry_projects.text().strip():
            self._update_vault_label()
            return
        getter = getattr(self.vm.config_factory, "get_workspace_root", None)
        if callable(getter):
            try:
                configured = getter()
                if configured and getattr(self.vm.config_factory, "has_local_workspace_root", lambda: False)():
                    self.entry_projects.setText(str(configured))
            except Exception:  # noqa: BLE001
                pass
        self._update_vault_label()

    def _validate_projects(self) -> bool:
        path = self.entry_projects.text().strip()
        if not path:
            self._show_error(self.tr("Select the projects folder for this machine."))
            return False
        candidate = Path(path).expanduser()
        if not candidate.exists():
            reply = QMessageBox.question(
                self,
                self.tr("Create Projects Folder"),
                self.tr("The folder does not exist. Create it now?\n\n{0}").format(candidate),
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return False
        return self.vm.validate_projects_dir(candidate, create=True)

    def _update_summary(self) -> None:
        preview = self.vm.seed_preview
        svn_status = self.vm.svn_status
        if preview is not None:
            seed_line = preview.studio_name or self.tr("Studio Seed")
            seed_line = f"{seed_line} ({preview.kitsu_url})"
        elif self.vm.resume_mode:
            seed_line = self.tr("Current machine configuration (Studio Seed already applied)")
        else:
            seed_line = self.tr("Studio Seed")
        svn_line = self.tr("Not required")
        if self.vm.svn_required() and svn_status is not None:
            svn_line = f"{svn_status.version_label} — {svn_status.path}"
        projects_line = str(self.vm.projects_dir or "")
        vault_dir = "openstudio_vault"
        if preview is not None:
            vault_dir = str(
                (preview.payload.get("infrastructure_topology") or {}).get("vault_dir")
                or vault_dir
            )
        else:
            getter = getattr(self.vm.config_factory, "get_vault_dir", None)
            if callable(getter):
                try:
                    vault_dir = str(getter() or vault_dir)
                except Exception:  # noqa: BLE001
                    pass
        vault_line = str(Path(projects_line) / vault_dir) if projects_line else ""

        self.lbl_summary.setText(
            self.tr(
                "Studio Seed:\n{0}\n\nSVN Client:\n{1}\n\nProjects Folder:\n{2}\n\nVault:\n{3}"
            ).format(seed_line, svn_line, projects_line, vault_line)
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _set_step(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for position, label in enumerate(self._step_labels):
            if position == index:
                style = "color: #F8FAFC; font-size: 13px; font-weight: bold; padding: 6px 0;"
            elif position < index:
                style = "color: #10B981; font-size: 13px; padding: 6px 0;"
            else:
                style = "color: #64748B; font-size: 13px; padding: 6px 0;"
            label.setStyleSheet(style)

        self.btn_back.setEnabled(index > 0)
        self.btn_next.setText(self.tr("Finish") if index == len(STEP_TITLES) - 1 else self.tr("Next"))
        self.btn_next.setEnabled(
            not (index == 2 and self.vm.svn_required() and self.vm.svn_status is None)
        )
        self._clear_error()

    def _on_seed_validated(self, preview: SeedPreview) -> None:
        self._clear_error()
        self.lbl_seed_summary.setText(
            self.tr(
                "Studio: {0}\nKitsu: {1}\nVCS servers: {2}\nSVN required: {3}"
            ).format(
                preview.studio_name or self.tr("Unnamed studio"),
                preview.kitsu_url or self.tr("Not configured"),
                preview.vcs_servers,
                self.tr("Yes") if preview.svn_required else self.tr("No"),
            )
        )
        self.lbl_seed_summary.show()

    def _on_svn_status(self, status: SvnClientStatus) -> None:
        self._clear_error()
        self.btn_next.setEnabled(True)
        self.lbl_svn_status.setText(
            self.tr("Found Subversion {0}\nPath: {1}").format(
                status.version_label,
                status.path or self.tr("unknown"),
            )
            if status.found
            else self.tr("Subversion was not found on this computer.")
        )
        if not self.vm.svn_required():
            self.lbl_svn_status.setText(
                self.tr("Version control is disabled in this seed. The SVN client is not required.")
            )
            self.lbl_svn_manual.hide()
            return
        if status.meets_minimum:
            self.lbl_svn_manual.hide()
        else:
            self.lbl_svn_manual.setText(self.vm.manual_install_message())
            self.lbl_svn_manual.show()

    def _on_projects_validated(self, path: str) -> None:
        self._clear_error()
        self._update_vault_label()

    def _on_setup_finished(self, ok: bool, message: str) -> None:
        if ok:
            if self._on_finished is not None:
                self._on_finished(True)
            self.accept()
            return
        self._show_error(message)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self.lbl_error.setText(message or self.tr("The operation failed."))
        self.lbl_error.show()

    def _clear_error(self) -> None:
        self.lbl_error.clear()
        self.lbl_error.hide()

    def _shutdown_workers(self) -> None:
        """Wait for the local SVN probe so the QThread is not destroyed while running."""
        try:
            self.vm.workers.shutdown(6000)
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._shutdown_workers()
        super().closeEvent(event)

    def accept(self) -> None:  # noqa: D102 (Qt override)
        self._shutdown_workers()
        super().accept()

    def reject(self) -> None:  # noqa: D102 (Qt override)
        self._shutdown_workers()
        super().reject()
