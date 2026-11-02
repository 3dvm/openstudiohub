# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/render_progress_widget.py
# Architectural role: UI Widget / read-only render progress for artists
# =========================================================================================

"""Read-only render progress for artist dashboards.

The TD/PM render panel writes ``03_render/.render_status.json``. This widget
polls that shared file and shows the current state, frame progress, preview and
review video path. It never rents nodes or starts Blender.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.infrastructure.render.status import RenderStatusStore

ProjectRootResolver = Callable[[str], Optional[Path]]


class RenderProgressWidget(QFrame):
    def __init__(
        self,
        parent,
        project_root_resolver: ProjectRootResolver,
        *,
        poll_seconds: int = 3,
    ) -> None:
        super().__init__(parent)
        self.project_root_resolver = project_root_resolver
        self.projects: list[dict] = []
        self.project_root: Path | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, poll_seconds) * 1000)
        self._timer.timeout.connect(self._refresh_status)
        self.setObjectName("RenderProgressBase")
        self._build_ui()
        self._timer.start()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("InvisibleScrollArea")
        container = QWidget()
        container.setObjectName("TransparentGridContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel(self.tr("Render progress"))
        title.setObjectName("PageTitle")
        header.addWidget(title)
        self.combo_projects = QComboBox()
        self.combo_projects.setObjectName("StandardComboBox")
        self.combo_projects.setFixedSize(260, 34)
        self.combo_projects.currentIndexChanged.connect(self._on_project_changed)
        header.addWidget(self.combo_projects)
        header.addStretch()
        self.btn_refresh = QPushButton(self.tr("⟳ Refresh"))
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.setFixedSize(100, 34)
        self.btn_refresh.clicked.connect(self._refresh_status)
        header.addWidget(self.btn_refresh)
        layout.addLayout(header)

        card = QFrame()
        card.setObjectName("CardFrame")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        self.lbl_status = QLabel(self.tr("No render in progress."))
        self.lbl_status.setObjectName("SectionTitle")
        card_layout.addWidget(self.lbl_status)
        self.lbl_message = QLabel("")
        self.lbl_message.setObjectName("MutedLabel")
        self.lbl_message.setWordWrap(True)
        card_layout.addWidget(self.lbl_message)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        card_layout.addWidget(self.progress)
        self.lbl_detail = QLabel("")
        self.lbl_detail.setObjectName("InfoLabel")
        self.lbl_detail.setWordWrap(True)
        card_layout.addWidget(self.lbl_detail)
        layout.addWidget(card)

        preview_card = QFrame()
        preview_card.setObjectName("CardFrame")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_title = QLabel(self.tr("Latest preview"))
        preview_title.setObjectName("SectionTitle")
        preview_layout.addWidget(preview_title)
        self.preview_label = QLabel(self.tr("No preview available."))
        self.preview_label.setObjectName("MutedLabel")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(260)
        self.preview_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_label)
        layout.addWidget(preview_card)

        video_card = QFrame()
        video_card.setObjectName("CardFrame")
        video_layout = QVBoxLayout(video_card)
        video_layout.setContentsMargins(16, 16, 16, 16)
        video_title = QLabel(self.tr("Review video"))
        video_title.setObjectName("SectionTitle")
        video_layout.addWidget(video_title)
        self.lbl_video = QLabel(self.tr("No review video yet."))
        self.lbl_video.setObjectName("MutedLabel")
        self.lbl_video.setWordWrap(True)
        video_layout.addWidget(self.lbl_video)
        layout.addWidget(video_card)
        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def set_projects(self, projects: list) -> None:
        self.projects = list(projects or [])
        current = self.combo_projects.currentText()
        self.combo_projects.blockSignals(True)
        self.combo_projects.clear()
        for project in self.projects:
            self.combo_projects.addItem(str(project.get("name") or ""), project)
        if current:
            index = self.combo_projects.findText(current)
            if index >= 0:
                self.combo_projects.setCurrentIndex(index)
        self.combo_projects.blockSignals(False)
        if self.combo_projects.count() and self.combo_projects.currentIndex() < 0:
            self.combo_projects.setCurrentIndex(0)
        self._on_project_changed(self.combo_projects.currentIndex())

    def _on_project_changed(self, index: int) -> None:
        if index < 0:
            self.project_root = None
            self._refresh_status()
            return
        project = self.combo_projects.itemData(index) or {}
        name = str(project.get("name") or self.combo_projects.itemText(index))
        try:
            root = self.project_root_resolver(name)
        except Exception:  # noqa: BLE001
            root = None
        self.project_root = Path(root) if root is not None else None
        self._refresh_status()

    def _refresh_status(self) -> None:
        if self.project_root is None:
            self.lbl_status.setText(self.tr("Select a project."))
            self.lbl_message.setText("")
            self.lbl_detail.setText("")
            self.lbl_video.setText("")
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(self.tr("No preview available."))
            return
        data = RenderStatusStore.for_project(self.project_root).read()
        if not data:
            self.lbl_status.setText(self.tr("No render in progress."))
            self.lbl_message.setText("")
            self.lbl_detail.setText("")
            self.lbl_video.setText(self.tr("No review video yet."))
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(self.tr("No preview available."))
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            return
        status = str(data.get("status") or "idle")
        message = str(data.get("message") or "")
        self.lbl_status.setText(status.capitalize())
        self.lbl_message.setText(message)
        expected = int(data.get("frames_expected") or 0)
        done = int(data.get("frames_done") or 0)
        nodes = int(data.get("nodes") or 0)
        cost = float(data.get("cost") or 0.0)
        backend = str(data.get("backend") or "")
        updated = str(data.get("updated_at") or "")
        self.progress.setRange(0, max(1, expected))
        self.progress.setValue(min(done, max(1, expected)))
        self.lbl_detail.setText(
            self.tr(
                "Frames: {0}/{1} · Nodes: {2} · Backend: {3} · Cost: ${4:.2f}<br>"
                "Updated: {5}"
            ).format(done, expected, nodes, backend or "-", cost, updated)
        )
        preview = str(data.get("preview") or "")
        if preview and Path(preview).is_file():
            pixmap = QPixmap(preview)
            if not pixmap.isNull():
                self.preview_label.setText("")
                self.preview_label.setPixmap(
                    pixmap.scaled(600, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
        video = str(data.get("video") or "")
        self.lbl_video.setText(video or self.tr("No review video yet."))
