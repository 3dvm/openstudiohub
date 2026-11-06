# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/task_card.py
# Architectural role: UI Component / Reusable Task Card (PySide6)
# =========================================================================================

"""Reusable presentational task card for the artist dashboard.

It renders the CTA priority matrix and displays a thumbnail that the dashboard
pre-fetches off the UI thread. All business actions are delegated through the
injected callbacks.
"""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

def resolve_task_status(task_data: dict) -> tuple[str, str]:
    """Resolve a task's display status name and colour.

    Kitsu returns the status nested as ``task_status: {name, color}`` for tasks
    fetched via gazu, while some payloads carry flat ``task_status_name`` /
    ``task_status_color`` keys. Prefer the nested shape, then the flat one.
    """
    status_data = task_data.get("task_status") or {}
    name = (
        status_data.get("name")
        or task_data.get("task_status_name")
        or task_data.get("status_name")
        or task_data.get("status")
        or "TODO"
    )
    color = (
        status_data.get("color")
        or task_data.get("task_status_color")
        or task_data.get("status_color")
        or "#444444"
    )
    return str(name), str(color)


class TaskCard(QFrame):
    release_lock_requested = Signal()
    break_lock_requested = Signal()

    def __init__(
        self,
        parent,
        task_data: dict,
        project_root,
        is_installed: bool,
        can_work: bool,
        blocked_reason: str,
        on_launch_callback,
        on_install_callback,
        pending_change_count: int = 0,
        on_update_callback=None,
        comment_count: int = 0,
        unread_count: int = 0,
        on_comments_callback=None,
        on_kitsu_callback=None,
        on_history_callback=None,
        file_missing: bool = False,
        thumbnail_bytes: bytes | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent, **kwargs)

        self.task_data = task_data
        self.project_root = project_root
        self.is_installed = is_installed
        self.can_work = can_work
        self.blocked_reason = blocked_reason

        self.on_launch_callback = on_launch_callback
        self.on_install_callback = on_install_callback
        self.pending_change_count = max(0, int(pending_change_count or 0))
        self.on_update_callback = on_update_callback
        self.comment_count = max(0, int(comment_count or 0))
        self.unread_count = max(0, int(unread_count or 0))
        self.on_comments_callback = on_comments_callback
        self.on_kitsu_callback = on_kitsu_callback
        self.on_history_callback = on_history_callback
        self.file_missing = bool(file_missing)
        self.allow_break_lock = False
        self._comment_icon_ref = None

        self.setObjectName("FloatingCard")
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setFixedSize(320, 280)

        self._build_ui()
        if thumbnail_bytes:
            self.set_thumbnail(thumbnail_bytes)

    def _get_contrast_text_color(self, hex_color: str) -> str:
        """Compute relative sRGB luminance for badge text contrast."""
        if not hex_color:
            return "white"
        hex_color = hex_color.lstrip("#")
        if len(hex_color) != 6:
            return "white"
        try:
            r, g, b = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            return "#0F172A" if luminance > 0.5 else "#F8FAFC"
        except Exception:  # noqa: BLE001
            return "white"

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        entity_name = self.task_data.get("entity_name", self.task_data.get("name", "Unknown Entity"))
        task_type = self.task_data.get("task_type_name", "Task")
        title_text = f"{entity_name} - {task_type}"

        self.title_label = QLabel(title_text)
        self.title_label.setObjectName("H2Title")
        self.title_label.setObjectName("CardTitleSmall")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        status_name, status_color = resolve_task_status(self.task_data)
        text_color_contrast = self._get_contrast_text_color(status_color)

        self.status_badge = QLabel(status_name.upper())
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setFixedHeight(22)
        self.status_badge.setStyleSheet(f"""
            background-color: {status_color};
            color: {text_color_contrast};
            border-radius: 11px;
            font-size: 10px;
            font-weight: bold;
            padding: 0 10px;
        """)
        header_layout.addWidget(self.status_badge)
        main_layout.addLayout(header_layout)

        self.thumb_stack = QStackedWidget()
        self.thumb_stack.setFixedHeight(140)
        self.thumb_stack.setObjectName("ThumbnailFrame")

        self.page_placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.page_placeholder)
        placeholder_layout.setAlignment(Qt.AlignCenter)
        placeholder_layout.setSpacing(10)

        self.lbl_placeholder_icon = QLabel()
        self.lbl_placeholder_icon.setAlignment(Qt.AlignCenter)

        task_type_key = self.task_data.get("task_type_name", "generic").lower()

        icon_map = {
            "storyboard": "task-storyboard.svg",
            "layout": "task-layout.svg",
            "modeling": "task-modeling.svg",
            "rigging": "task-rigging.svg",
            "animation": "task-animation.svg",
            "lighting": "task-lighting.svg",
            "compositing": "task-compositing.svg",
            "editorial": "task-editorial.svg",
            "edit": "task-editorial.svg",
        }

        svg_filename = icon_map.get(task_type_key, "task-generic.svg")
        icon_path = Path(f"assets/icons/{svg_filename}")

        if icon_path.exists():
            base_pixmap = QIcon(str(icon_path)).pixmap(55, 55)
            painter = QPainter(base_pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(base_pixmap.rect(), QColor("#64748B"))
            painter.end()
            self.lbl_placeholder_icon.setPixmap(base_pixmap)
        else:
            self.lbl_placeholder_icon.setText("⚙️")
            self.lbl_placeholder_icon.setObjectName("PlaceholderIcon")

        safe_task_name = self.task_data.get("task_type_name", "TASK").upper()
        self.lbl_placeholder_text = QLabel(self.tr(f"{safe_task_name} TASK"))
        self.lbl_placeholder_text.setAlignment(Qt.AlignCenter)
        self.lbl_placeholder_text.setObjectName("PlaceholderText")

        placeholder_layout.addStretch()
        placeholder_layout.addWidget(self.lbl_placeholder_icon)
        placeholder_layout.addWidget(self.lbl_placeholder_text)
        placeholder_layout.addStretch()

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)

        self.thumb_stack.addWidget(self.page_placeholder)
        self.thumb_stack.addWidget(self.thumb_label)

        # The lock badge floats over the thumbnail's top-right corner, so both
        # widgets share the same grid cell (the badge stays on top when raised).
        self.thumb_container = QWidget()
        thumb_overlay = QGridLayout(self.thumb_container)
        thumb_overlay.setContentsMargins(0, 0, 0, 0)
        thumb_overlay.setSpacing(0)
        thumb_overlay.addWidget(self.thumb_stack, 0, 0)

        self.lock_badge = QLabel(self.thumb_container)
        self.lock_badge.setAlignment(Qt.AlignCenter)
        self.lock_badge.setFixedHeight(20)
        self.lock_badge.hide()
        thumb_overlay.addWidget(self.lock_badge, 0, 0, Qt.AlignTop | Qt.AlignRight)

        self.comment_badge = QToolButton(self.thumb_container)
        self.comment_badge.setCursor(Qt.PointingHandCursor)
        self.comment_badge.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.comment_badge.setIconSize(QSize(13, 13))
        self.comment_badge.setFixedHeight(20)
        self.comment_badge.clicked.connect(self._on_comments_clicked)
        thumb_overlay.addWidget(self.comment_badge, 0, 0, Qt.AlignTop | Qt.AlignLeft)
        self._render_comment_badge()

        main_layout.addWidget(self.thumb_container)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(12)

        if self.on_kitsu_callback is not None and self.task_data.get("id") and self.task_data.get("project_id"):
            self.kitsu_btn = QPushButton(self.tr("Kitsu"))
            self.kitsu_btn.setObjectName("KitsuTaskButton")
            self.kitsu_btn.setFixedSize(80, 36)
            self.kitsu_btn.setCursor(Qt.PointingHandCursor)
            self.kitsu_btn.clicked.connect(
                lambda checked=False: self.on_kitsu_callback(self.task_data)
            )
            btn_layout.addWidget(self.kitsu_btn)

        if not self.project_root:
            self.action_btn = QPushButton(self.tr("Folder Missing on NAS"))
            self.action_btn.setObjectName("DangerOutlineButton")
            self.action_btn.setEnabled(False)

        elif not self.can_work:
            msg = self.blocked_reason if self.blocked_reason else self.tr("Access Denied")
            self.action_btn = QPushButton(f"🔒 {msg}")
            self.action_btn.setObjectName("MutedOutlineButton")
            self.action_btn.setEnabled(False)

        elif self.is_installed and self.file_missing:
            self.action_btn = QPushButton(self.tr("File Missing on Disk"))
            self.action_btn.setObjectName("DangerOutlineButton")
            self.action_btn.setEnabled(False)
            self.action_btn.setToolTip(
                self.tr("The task file does not exist on disk. Ask a PM/TD to create or link it.")
            )

        elif self.is_installed:
            self.action_btn = QPushButton(self.tr("Launch Project Environment"))
            self.action_btn.setObjectName("SuccessOutlineButton")
            self.action_btn.setCursor(Qt.PointingHandCursor)
            self.action_btn.clicked.connect(lambda checked=False: self.on_launch_callback())

        else:
            self.action_btn = QPushButton(self.tr("Install Project Locally"))
            self.action_btn.setObjectName("WarningOutlineButton")
            self.action_btn.setCursor(Qt.PointingHandCursor)
            self.action_btn.clicked.connect(lambda checked=False: self.on_install_callback())

        self.action_btn.setFixedHeight(36)
        self.action_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_layout.addWidget(self.action_btn)

        main_layout.addLayout(btn_layout)

        self.update_vcs_btn = QPushButton()
        self.update_vcs_btn.setObjectName("UpdateVcsButton")
        self.update_vcs_btn.setCursor(Qt.PointingHandCursor)
        self.update_vcs_btn.setFixedHeight(32)
        self.update_vcs_btn.clicked.connect(self._on_update_clicked)
        main_layout.addWidget(self.update_vcs_btn)
        self._sync_update_button()

    def _on_update_clicked(self) -> None:
        if self.on_update_callback is not None:
            self.on_update_callback()

    def _sync_update_button(self) -> None:
        count = self.pending_change_count
        visible = count > 0 and self.on_update_callback is not None
        self.update_vcs_btn.setText(self.tr(f"⤴ Update VCS ({count})"))
        self.update_vcs_btn.setVisible(visible)
        self.setFixedSize(320, 320 if visible else 280)

    def set_pending_change_count(self, count: int) -> None:
        """Update the live badge for uncommitted VCS changes on this task."""
        self.pending_change_count = max(0, int(count or 0))
        self._sync_update_button()

    def set_lock_state(self, owner: str, is_mine: bool = False) -> None:
        """Render the VCS lock badge for the task's linked file.

        An empty ``owner`` means the file is unlocked, so the badge is hidden.
        """
        self.lock_owner = owner
        self.lock_is_mine = bool(is_mine)
        if not owner:
            self.lock_badge.hide()
            return

        if is_mine:
            background, foreground, label = "#10B981", "#0F172A", self.tr("🔒 You")
        else:
            background, foreground, label = "#EF4444", "#F8FAFC", f"🔒 {owner}"

        max_width = max(160, (self.thumb_stack.width() or 0) - 16)
        self.lock_badge.setText(self.lock_badge.fontMetrics().elidedText(label, Qt.ElideRight, max_width))
        self.lock_badge.setToolTip(
            self.tr("Locked by you") if is_mine else self.tr(f"Locked by {owner}")
        )
        self.lock_badge.setStyleSheet(f"""
            background-color: {background};
            color: {foreground};
            border-radius: 10px;
            font-size: 10px;
            font-weight: bold;
            padding: 0 8px;
        """)
        self.lock_badge.show()
        self.lock_badge.raise_()

    def set_can_break_lock(self, allowed: bool) -> None:
        """Allow a TD to break a lock owned by another user."""
        self.allow_break_lock = bool(allowed)

    def _show_context_menu(self, position) -> None:
        menu = QMenu(self)
        actions = 0
        if self.on_history_callback is not None:
            action_history = menu.addAction(self.tr("View VCS History…"))
            action_history.triggered.connect(
                lambda _checked=False: self.on_history_callback()
            )
            actions += 1

        owner = getattr(self, "lock_owner", "")
        if owner:
            if actions:
                menu.addSeparator()
            if getattr(self, "lock_is_mine", False):
                action = menu.addAction(self.tr("Release my lock"))
                action.triggered.connect(self.release_lock_requested.emit)
                actions += 1
            elif self.allow_break_lock:
                action = menu.addAction(self.tr("Break foreign lock"))
                action.triggered.connect(self.break_lock_requested.emit)
                actions += 1

        if actions == 0:
            return
        menu.exec(self.mapToGlobal(position))

    # ------------------------------------------------------------------
    # Comment badge
    # ------------------------------------------------------------------
    def _on_comments_clicked(self) -> None:
        if self.on_comments_callback is not None:
            self.on_comments_callback()

    def set_comment_counts(self, total: int, unread: int) -> None:
        self.comment_count = max(0, int(total or 0))
        self.unread_count = max(0, int(unread or 0))
        self._render_comment_badge()

    @staticmethod
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

    def _render_comment_badge(self) -> None:
        unread = self.unread_count > 0
        color = "#FFFFFF" if unread else "#CBD5E1"
        self.comment_badge.setText(str(self.comment_count))
        icon = self._comment_icon(color)
        self._comment_icon_ref = icon
        self.comment_badge.setIcon(icon)
        if unread:
            background, border = "#F97316", "#FB923C"
        else:
            background, border = "rgba(15, 23, 42, 0.88)", "#334155"
        self.comment_badge.setStyleSheet(
            f"QToolButton {{ background-color: {background}; color: {color};"
            f" border: 1px solid {border}; border-radius: 10px; padding: 0 6px;"
            " font-size: 10px; font-weight: bold; }"
        )
        self.comment_badge.setToolTip(
            self.tr(f"{self.comment_count} comment(s), {self.unread_count} new")
            if unread
            else self.tr(f"{self.comment_count} comment(s)")
        )
        self.comment_badge.show()

    def set_thumbnail(self, img_bytes: bytes | None) -> None:
        """Display a thumbnail already fetched by the dashboard."""
        if not img_bytes:
            self.thumb_stack.setCurrentIndex(0)
            return

        image = QImage.fromData(img_bytes)
        if image.isNull():
            self.thumb_stack.setCurrentIndex(0)
            return

        width = max(1, self.thumb_stack.width())
        height = max(1, self.thumb_stack.height())
        pixmap = QPixmap.fromImage(image)
        pixmap = pixmap.scaled(
            width,
            height,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.thumb_label.setPixmap(pixmap)
        self.thumb_label.setText("")
        self.thumb_stack.setCurrentIndex(1)
