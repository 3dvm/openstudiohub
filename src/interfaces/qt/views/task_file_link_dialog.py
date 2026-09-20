# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/views/task_file_link_dialog.py
# Architectural role: UI View / Link a Kitsu task to a physical .blend file
# =========================================================================================

"""Modal dialog to inspect, link, edit, or create the file of a Kitsu task.

All I/O is delegated to ``BlendBuilderViewModel`` (which runs it on a worker);
this view only collects the target path and reflects the result.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from src.domain.production.entities import Task


class TaskFileLinkDialog(QDialog):
    def __init__(
        self,
        parent,
        viewmodel,
        task: Task,
        project_root: Path,
        entity_label: str,
        task_type_name: str,
        suggested_path: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Link Task to File"))
        self.setFixedSize(560, 300)
        self.setModal(True)

        self.vm = viewmodel
        self.task = task
        self.project_root = Path(project_root)
        self.entity_label = entity_label
        self.task_type_name = task_type_name
        self._busy = False

        self.setObjectName("ViewLoginBase")
        self._build_ui(suggested_path)
        self.vm.task_file_finished.connect(self._on_finished)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self, suggested_path: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(12)

        title = QLabel(self.tr("Task File Mapping"))
        title.setObjectName("CardTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        info = QLabel(f"{self.entity_label}  •  {self.task_type_name}")
        info.setStyleSheet("color: #94A3B8; font-weight: bold;")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        layout.addWidget(QLabel(self.tr("Physical file (relative to the production folder):")))
        self.input_path = QLineEdit(suggested_path)
        self.input_path.setObjectName("FormInput")
        self.input_path.setFixedHeight(40)
        layout.addWidget(self.input_path)

        actions = QHBoxLayout()
        self.btn_suggest = QPushButton(self.tr("Suggest"))
        self.btn_suggest.setObjectName("SecondaryButton")
        self.btn_suggest.clicked.connect(lambda: self.input_path.setText(self._suggested_path()))
        actions.addWidget(self.btn_suggest)

        self.btn_browse = QPushButton(self.tr("Browse existing..."))
        self.btn_browse.setObjectName("SecondaryButton")
        self.btn_browse.clicked.connect(self._browse)
        actions.addWidget(self.btn_browse)

        self.btn_create = QPushButton(self.tr("Create empty .blend"))
        self.btn_create.setObjectName("SecondaryButton")
        self.btn_create.clicked.connect(self._create_empty)
        actions.addWidget(self.btn_create)
        actions.addStretch()
        layout.addLayout(actions)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)
        layout.addStretch()

        footer = QHBoxLayout()
        self.btn_unlink = QPushButton(self.tr("Remove link"))
        self.btn_unlink.setObjectName("LinkButton")
        self.btn_unlink.clicked.connect(self._unlink)
        footer.addWidget(self.btn_unlink)
        footer.addStretch()

        self.btn_cancel = QPushButton(self.tr("Cancel"))
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.clicked.connect(self.reject)
        footer.addWidget(self.btn_cancel)

        self.btn_save = QPushButton(self.tr("Save"))
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self._save)
        footer.addWidget(self.btn_save)
        layout.addLayout(footer)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _suggested_path(self) -> str:
        try:
            return self.vm.suggest_task_file_path(self.task)
        except Exception:  # noqa: BLE001
            return ""

    def _vfs_root(self) -> Path:
        return self.project_root / self.vm.config_factory.get_vfs_svn_name()

    def _browse(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select .blend file"), str(self._vfs_root()), self.tr("Blender Files (*.blend)")
        )
        if not selected:
            return
        try:
            relative = Path(selected).resolve().relative_to(self._vfs_root().resolve()).as_posix()
        except ValueError:
            self._show_status("Selected file is outside the project production folder.", error=True)
            return
        self.input_path.setText(relative)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.btn_save, self.btn_create, self.btn_unlink, self.btn_suggest, self.btn_browse):
            widget.setEnabled(not busy)

    def _show_status(self, message: str, error: bool = False) -> None:
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet("color: #EF4444;" if error else "color: #10B981;")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _save(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.vm.link_task_file(self.task, self.input_path.text().strip())

    def _create_empty(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.vm.create_empty_task_file(self.task, self.project_root, self.input_path.text().strip())

    def _unlink(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.vm.unlink_task_file(self.task)

    def _on_finished(self, success: bool, message: str) -> None:
        self._set_busy(False)
        if success:
            self._show_status(message)
            self.accept()
        else:
            self._show_status(message, error=True)
