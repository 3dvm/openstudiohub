# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/vcs_migration_dialog.py
# Architectural role: UI Component / VCS migration target chooser (PySide6)
# =========================================================================================

"""Modal that asks which VCS server a project repository should migrate to.

The source is fixed to the project's current server (shown read-only); only the
target is selectable, limited to eligible SVN servers other than the source.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class MigrationServerDialog(QDialog):
    def __init__(
        self,
        parent,
        project_name: str,
        source_server: dict,
        target_servers: list,
        default_target_id: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Migrate VCS Repository"))
        self.setFixedSize(480, 330)
        self.setModal(True)
        self.setObjectName("FloatingCard")
        self._target_servers = list(target_servers)
        self._build_ui(project_name, source_server, default_target_id)

    def _build_ui(self, project_name: str, source_server: dict, default_target_id: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(15)

        title = QLabel(self.tr("Migrate VCS Repository"))
        title.setObjectName("H2Title")
        layout.addWidget(title)

        lbl_project = QLabel(self.tr(f"Project: {project_name}"))
        lbl_project.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(lbl_project)

        notice = QLabel(
            self.tr(
                "History is preserved and the local working copy is repointed. "
                "Pick the SVN server this project should be migrated to."
            )
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(notice)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        source_label = QLabel(self.tr("Source:"))
        source_label.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 12px;")
        source_value = QLabel(
            self.tr(f"{source_server.get('name', 'Unknown')}  ({source_server.get('repository_url', '')})")
        )
        source_value.setStyleSheet("color: #F8FAFC; font-weight: bold; font-size: 13px;")

        target_label = QLabel(self.tr("Target:"))
        target_label.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 12px;")
        self.combo_target = QComboBox()
        self.combo_target.setObjectName("FormInput")
        self.combo_target.setFixedHeight(35)
        for server in self._target_servers:
            label = server.get("name", server.get("id", "Server"))
            if server.get("repository_url"):
                label += f"  ({server['repository_url']})"
            self.combo_target.addItem(label, server.get("id", ""))
        index = self.combo_target.findData(default_target_id)
        if index >= 0:
            self.combo_target.setCurrentIndex(index)

        form.addRow(source_label, source_value)
        form.addRow(target_label, self.combo_target)
        layout.addLayout(form)

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()

        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setObjectName("SecondaryButton")
        btn_cancel.setFixedHeight(35)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)

        self.btn_migrate = QPushButton(self.tr("Migrate"))
        self.btn_migrate.setObjectName("PrimaryButton")
        self.btn_migrate.setFixedHeight(35)
        self.btn_migrate.setCursor(Qt.PointingHandCursor)
        self.btn_migrate.setEnabled(self.combo_target.count() > 0)
        self.btn_migrate.clicked.connect(self.accept)

        buttons.addWidget(btn_cancel)
        buttons.addWidget(self.btn_migrate)
        layout.addLayout(buttons)

    def selected_target_id(self) -> str:
        return self.combo_target.currentData() or ""
