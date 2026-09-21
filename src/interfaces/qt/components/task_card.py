# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/task_card.py
# Architectural role: UI Component / Reusable Task Card (PySide6)
# =========================================================================================

"""Reusable presentational task card for the artist dashboard.

It renders the CTA priority matrix and loads the thumbnail asynchronously.
All business actions are delegated through the injected callbacks.
"""

import webbrowser
from pathlib import Path

import requests
from PySide6.QtCore import Qt, Signal

from src.infrastructure.qt_worker import ManagedWorker
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

class ThumbnailWorker(ManagedWorker):
    """Background thread for downloading entity thumbnails over HTTP."""

    image_downloaded = Signal(bytes)
    error_occurred = Signal(str)

    def __init__(self, entity_id: str, token: str, host_url: str) -> None:
        super().__init__()
        self.entity_id = entity_id
        self.token = token
        self.host_url = host_url

    def run(self) -> None:
        if not self.entity_id:
            self.error_occurred.emit("No Entity ID Available")
            return

        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            entity_url = f"{self.host_url}/data/entities/{self.entity_id}"
            entity_resp = requests.get(entity_url, headers=headers, timeout=10)
            if entity_resp.status_code != 200:
                self.error_occurred.emit(f"Entity not found (HTTP {entity_resp.status_code})")
                return

            entity_data = entity_resp.json()
            preview_id = entity_data.get("preview_file_id")

            if not preview_id:
                self.error_occurred.emit("Entity has no preview image")
                return

            img_url = f"{self.host_url}/pictures/thumbnails/preview-files/{preview_id}.png"
            img_resp = requests.get(img_url, headers=headers, timeout=10)

            if img_resp.status_code == 200:
                self.image_downloaded.emit(img_resp.content)
            else:
                self.error_occurred.emit(f"Thumbnail not found (HTTP {img_resp.status_code})")

        except Exception as error:  # noqa: BLE001
            print(f"[UI THUMBNAIL ERROR] Download failed: {error}")
            self.error_occurred.emit("Network connection error")


class TaskCard(QFrame):
    def __init__(
        self,
        parent,
        task_data: dict,
        project_root,
        is_installed: bool,
        can_work: bool,
        blocked_reason: str,
        token: str,
        host: str,
        on_launch_callback,
        on_install_callback,
        **kwargs,
    ) -> None:
        super().__init__(parent, **kwargs)

        self.task_data = task_data
        self.project_root = project_root
        self.is_installed = is_installed
        self.can_work = can_work
        self.blocked_reason = blocked_reason
        self.token = token
        self.host = host

        self.on_launch_callback = on_launch_callback
        self.on_install_callback = on_install_callback

        self.setObjectName("FloatingCard")
        self.setFixedSize(320, 280)

        self._build_ui()
        self._load_thumbnail()

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
        self.title_label.setStyleSheet("color: #F8FAFC; font-size: 14px; font-weight: bold;")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        status_color = self.task_data.get("task_status_color", self.task_data.get("status_color", "#444444"))
        status_name = self.task_data.get("task_status_name", self.task_data.get("status_name", "TODO"))
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
        self.thumb_stack.setStyleSheet("QStackedWidget { background-color: #0F172A; border-radius: 8px; border: 1px solid #1E293B; }")

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
            self.lbl_placeholder_icon.setStyleSheet("font-size: 40px; background: transparent; color: #64748B;")

        safe_task_name = self.task_data.get("task_type_name", "TASK").upper()
        self.lbl_placeholder_text = QLabel(self.tr(f"{safe_task_name} TASK"))
        self.lbl_placeholder_text.setAlignment(Qt.AlignCenter)
        self.lbl_placeholder_text.setStyleSheet("color: #64748B; font-size: 10px; font-weight: bold; letter-spacing: 1px; background: transparent;")

        placeholder_layout.addStretch()
        placeholder_layout.addWidget(self.lbl_placeholder_icon)
        placeholder_layout.addWidget(self.lbl_placeholder_text)
        placeholder_layout.addStretch()

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("border-radius: 8px; background-color: transparent;")

        self.thumb_stack.addWidget(self.page_placeholder)
        self.thumb_stack.addWidget(self.thumb_label)

        main_layout.addWidget(self.thumb_stack)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(12)

        task_url = self.task_data.get("task_url")
        if task_url:
            self.kitsu_btn = QPushButton(self.tr("Kitsu ↗"))
            self.kitsu_btn.setObjectName("LinkButton")
            self.kitsu_btn.setFixedSize(80, 36)
            self.kitsu_btn.setCursor(Qt.PointingHandCursor)
            self.kitsu_btn.setStyleSheet("""
                QPushButton#LinkButton { background-color: #1E293B; color: #94A3B8; border: 1px solid #334155; border-radius: 6px; font-size: 12px; }
                QPushButton#LinkButton:hover { background-color: #334155; color: #F8FAFC; }
            """)
            self.kitsu_btn.clicked.connect(lambda checked=False, u=task_url: webbrowser.open(u))
            btn_layout.addWidget(self.kitsu_btn)

        if not self.project_root:
            self.action_btn = QPushButton(self.tr("Folder Missing on NAS"))
            self.action_btn.setEnabled(False)
            self.action_btn.setStyleSheet("QPushButton { border: 1px solid #EF4444; color: #EF4444; background: transparent; border-radius: 6px; font-weight: bold; font-size: 13px; }")

        elif not self.can_work:
            msg = self.blocked_reason if self.blocked_reason else self.tr("Access Denied")
            self.action_btn = QPushButton(f"🔒 {msg}")
            self.action_btn.setEnabled(False)
            self.action_btn.setStyleSheet("QPushButton:disabled { border: 1px solid #475569; color: #94A3B8; background: transparent; border-radius: 6px; font-weight: bold; font-size: 13px; }")

        elif self.is_installed:
            self.action_btn = QPushButton(self.tr("Launch Project Environment"))
            self.action_btn.setCursor(Qt.PointingHandCursor)
            self.action_btn.setStyleSheet("""
                QPushButton { border: 1px solid #10B981; color: #10B981; background: transparent; border-radius: 6px; font-weight: bold; font-size: 13px; }
                QPushButton:hover { background-color: rgba(16, 185, 129, 0.1); }
            """)
            self.action_btn.clicked.connect(lambda checked=False: self.on_launch_callback())

        else:
            self.action_btn = QPushButton(self.tr("Install Project Locally"))
            self.action_btn.setCursor(Qt.PointingHandCursor)
            self.action_btn.setStyleSheet("""
                QPushButton { border: 1px solid #F59E0B; color: #F59E0B; background: transparent; border-radius: 6px; font-weight: bold; font-size: 13px; }
                QPushButton:hover { background-color: rgba(245, 158, 11, 0.1); }
            """)
            self.action_btn.clicked.connect(lambda checked=False: self.on_install_callback())

        self.action_btn.setFixedHeight(36)
        self.action_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_layout.addWidget(self.action_btn)

        main_layout.addLayout(btn_layout)

    def _load_thumbnail(self) -> None:
        entity_id = self.task_data.get("entity_id")

        if not entity_id:
            self._on_thumbnail_error("No preview image mapped")
            return

        self.worker = ThumbnailWorker(entity_id, self.token, self.host)
        self.worker.image_downloaded.connect(self._on_thumbnail_ready)
        self.worker.error_occurred.connect(self._on_thumbnail_error)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _on_thumbnail_ready(self, img_bytes: bytes) -> None:
        image = QImage.fromData(img_bytes)
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            pixmap = pixmap.scaled(self.thumb_stack.width(), self.thumb_stack.height(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self.thumb_label.setPixmap(pixmap)
            self.thumb_label.setText("")
            self.thumb_stack.setCurrentIndex(1)
        else:
            self._on_thumbnail_error(self.tr("Corrupted image format"))

    def _on_thumbnail_error(self, message: str) -> None:
        self.thumb_stack.setCurrentIndex(0)
