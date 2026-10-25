# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/pm_task_card.py
# Architectural role: UI Component / PM-TD task card
# =========================================================================================

"""Compact task card for the PM/TD board (thumbnail, status, assignees, comments)."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.interfaces.qt.components.task_card import resolve_task_status


def _comment_icon(color: str) -> QIcon:
    icon_path = Path("assets/icons/comment.svg")
    if not icon_path.exists():
        return QIcon()
    try:
        pixmap = QIcon(str(icon_path)).pixmap(16, 16)
        if pixmap.isNull():
            return QIcon(str(icon_path))
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color))
        painter.end()
        return QIcon(pixmap)
    except Exception:  # noqa: BLE001
        return QIcon(str(icon_path))


class PmTaskCard(QFrame):
    comments_requested = Signal()
    assignees_requested = Signal()
    kitsu_requested = Signal()

    def __init__(
        self,
        parent,
        task: dict,
        thumbnail: bytes | None = None,
        can_assign: bool = False,
    ) -> None:
        super().__init__(parent)
        self.task = task
        self._thumbnail = thumbnail
        self._can_assign = can_assign
        self._comment_count = int(task.get("_comment_count", 0) or 0)
        self._unread_count = int(task.get("_unread_count", 0) or 0)

        self.setObjectName("FloatingCard")
        self.setFixedSize(320, 340)
        self._build_ui()
        self._render_comment_badge()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)

        header = QHBoxLayout()
        entity = self.task.get("entity_name") or self.task.get("name") or "Task"
        task_type = self.task.get("task_type_name") or "Task"
        title = QLabel(f"{entity} - {task_type}")
        title.setObjectName("BoardName")
        header.addWidget(title, stretch=1)

        status_name, status_color = resolve_task_status(self.task)
        badge = QLabel(status_name.upper())
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedHeight(20)
        badge.setStyleSheet(
            f"background-color: {status_color}; color: white; border-radius: 10px;"
            " font-size: 9px; font-weight: bold; padding: 0 8px;"
        )
        header.addWidget(badge)
        layout.addLayout(header)

        self.thumb_stack = QStackedWidget()
        self.thumb_stack.setFixedHeight(140)
        self.thumb_stack.setObjectName("ThumbnailFrame")
        self.placeholder = QLabel(self.tr("NO PREVIEW"))
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setObjectName("PlaceholderText")
        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_stack.addWidget(self.placeholder)
        self.thumb_stack.addWidget(self.thumb_label)

        self.thumb_container = QWidget()
        overlay = QGridLayout(self.thumb_container)
        overlay.setContentsMargins(0, 0, 0, 0)
        overlay.setSpacing(0)
        overlay.addWidget(self.thumb_stack, 0, 0)

        self.comment_badge = QToolButton(self.thumb_container)
        self.comment_badge.setCursor(Qt.PointingHandCursor)
        self.comment_badge.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.comment_badge.setIconSize(QSize(13, 13))
        self.comment_badge.setFixedHeight(20)
        self.comment_badge.clicked.connect(self.comments_requested.emit)
        overlay.addWidget(self.comment_badge, 0, 0, Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.thumb_container)

        project = QLabel(self.task.get("project_name") or "")
        project.setObjectName("MutedLabel")
        layout.addWidget(project)

        assignees_row = QHBoxLayout()
        self.lbl_assignees = QLabel("")
        self.lbl_assignees.setObjectName("BoardCell")
        assignees_row.addWidget(self.lbl_assignees, stretch=1)
        self.btn_assignees = QToolButton()
        self.btn_assignees.setText(self.tr("Edit"))
        self.btn_assignees.setCursor(Qt.PointingHandCursor)
        self.btn_assignees.setObjectName("BoardActionButton")
        self.btn_assignees.clicked.connect(self.assignees_requested.emit)
        self.btn_assignees.setVisible(self._can_assign)
        assignees_row.addWidget(self.btn_assignees)

        self.btn_kitsu = QToolButton()
        self.btn_kitsu.setText(self.tr("Kitsu"))
        self.btn_kitsu.setCursor(Qt.PointingHandCursor)
        self.btn_kitsu.setObjectName("BoardKitsuButton")
        self.btn_kitsu.clicked.connect(self.kitsu_requested.emit)
        assignees_row.addWidget(self.btn_kitsu)
        layout.addLayout(assignees_row)

        self._render_assignees()
        if self._thumbnail:
            self.set_thumbnail(self._thumbnail)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _assignee_names(self) -> list:
        names = []
        for person in self.task.get("assignees") or []:
            if isinstance(person, dict):
                name = person.get("full_name") or person.get("email")
            else:
                name = str(person)
            if name:
                names.append(str(name))
        return names

    def _render_assignees(self) -> None:
        names = self._assignee_names()
        text = ", ".join(names) if names else self.tr("Unassigned")
        self.lbl_assignees.setText(self.tr(f"👤 {text}"))

    def set_thumbnail(self, data: bytes) -> None:
        if not data:
            return
        image = QImage.fromData(data)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        pixmap = pixmap.scaled(
            self.thumb_stack.width(),
            self.thumb_stack.height(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.thumb_label.setPixmap(pixmap)
        self.thumb_stack.setCurrentIndex(1)

    def set_comment_counts(self, total: int, unread: int) -> None:
        self._comment_count = max(0, int(total or 0))
        self._unread_count = max(0, int(unread or 0))
        self._render_comment_badge()

    def _render_comment_badge(self) -> None:
        unread = self._unread_count > 0
        color = "#FFFFFF" if unread else "#CBD5E1"
        self.comment_badge.setText(str(self._comment_count))
        self.comment_badge.setIcon(_comment_icon(color))
        background, border = ("#F97316", "#FB923C") if unread else ("rgba(15,23,42,0.88)", "#334155")
        self.comment_badge.setStyleSheet(
            f"QToolButton {{ background-color: {background}; color: {color};"
            f" border: 1px solid {border}; border-radius: 10px; padding: 0 6px;"
            " font-size: 10px; font-weight: bold; }"
        )
        self.comment_badge.setToolTip(
            self.tr(f"{self._comment_count} comment(s), {self._unread_count} new")
        )
