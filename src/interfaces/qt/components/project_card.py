# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/project_card.py
# Architectural role: UI Component / Role-Aware Project Card
# =========================================================================================

"""Reusable presentational project card.

It renders the role-aware action matrix and loads the thumbnail asynchronously.
Every business action (install, launch, delete, navigation) is delegated to
injected callbacks provided by the parent ViewModel.
"""

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class ProjectThumbnailWorker(QThread):
    """Background thread for downloading project thumbnails over HTTP."""

    image_downloaded = Signal(bytes)
    error_occurred = Signal(str)

    def __init__(self, thumbnail_fetcher, project_id: str, token: str, host_url: str) -> None:
        super().__init__()
        self.thumbnail_fetcher = thumbnail_fetcher
        self.project_id = project_id
        self.token = token
        self.host_url = host_url

    def run(self) -> None:
        img_bytes = self.thumbnail_fetcher(self.project_id, self.token, self.host_url)
        if img_bytes:
            self.image_downloaded.emit(img_bytes)
        else:
            self.error_occurred.emit("No thumbnail")


class DeleteProjectDialog(QDialog):
    """Type-to-delete safety dialog (GitHub style)."""

    def __init__(self, parent, project_name: str) -> None:
        super().__init__(parent)
        self.project_name = project_name
        self.setWindowTitle(self.tr("⚠️ Warning: Project Destruction"))
        self.setFixedSize(450, 220)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        lbl_warn = QLabel(self.tr("You are about to permanently delete the project:\n<b>{0}</b>\n\nThis action will destroy Kitsu data, the SVN repository, and local files.").format(self.project_name))
        lbl_warn.setWordWrap(True)
        lbl_warn.setStyleSheet("color: #EF4444; font-size: 13px;")
        layout.addWidget(lbl_warn)

        lbl_instruct = QLabel(self.tr("To confirm, type <b>{0}</b> below:").format(self.project_name))
        lbl_instruct.setStyleSheet("color: #94A3B8;")
        layout.addWidget(lbl_instruct)

        self.entry_confirm = QLineEdit()
        self.entry_confirm.setObjectName("FormInput")
        self.entry_confirm.setFixedHeight(35)
        self.entry_confirm.textChanged.connect(self._validate_input)
        layout.addWidget(self.entry_confirm)

        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton(self.tr("Cancel"))
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.setFixedHeight(35)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_delete = QPushButton(self.tr("Permanently Delete"))
        self.btn_delete.setStyleSheet("background-color: #EF4444; color: white; font-weight: bold; border-radius: 6px;")
        self.btn_delete.setFixedHeight(35)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_delete)
        layout.addLayout(btn_layout)

    def _validate_input(self, text: str) -> None:
        self.btn_delete.setEnabled(text == self.project_name)


class ProjectCard(QFrame):
    def __init__(
        self,
        parent: QWidget,
        project_data: dict,
        user_role: str,
        status: dict,
        token: str,
        host: str,
        thumbnail_fetcher: Callable,
        on_install: Callable,
        on_launch: Callable,
        on_delete: Callable,
        on_open_kitsu: Callable,
        on_watchtower: Callable,
        on_open_wizard: Optional[Callable] = None,
    ) -> None:
        super().__init__(parent)

        self.project_data = project_data
        self.user_role = user_role
        self.token = token
        self.host = host
        self.thumbnail_fetcher = thumbnail_fetcher

        self.on_install = on_install
        self.on_launch = on_launch
        self.on_delete = on_delete
        self.on_open_kitsu = on_open_kitsu
        self.on_watchtower = on_watchtower
        self.on_open_wizard = on_open_wizard

        self.project_dir = status["project_dir"]
        self.is_installed = status["is_installed"]

        self.setObjectName("FloatingCard")
        self.setFixedSize(320, 330)

        self.setStyleSheet("""
            QFrame#FloatingCard { background-color: #1E293B; border-radius: 12px; border: 1px solid #334155; }
            QFrame#FloatingCard:hover { border: 1px solid #3B82F6; }
        """)

        self._build_ui()
        self._apply_status(status)
        self._load_thumbnail()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        lbl_status = QLabel(self.project_data.get("project_status_name", self.tr("Active Project")))
        lbl_status.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: bold;")
        header_layout.addWidget(lbl_status)

        header_layout.addStretch()

        self.btn_options = QToolButton()
        self.btn_options.setText("⋮")
        self.btn_options.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_options.setStyleSheet("""
            QToolButton { background: transparent; color: #94A3B8; font-size: 20px; font-weight: bold; border: none; padding-bottom: 5px; }
            QToolButton:hover { color: #F8FAFC; }
            QToolButton::menu-indicator { image: none; }
        """)
        self.btn_options.setPopupMode(QToolButton.InstantPopup)

        self.options_menu = QMenu(self)
        self.options_menu.setStyleSheet("""
            QMenu { background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155; border-radius: 6px; }
            QMenu::item { padding: 8px 25px; }
            QMenu::item:selected { background-color: #3B82F6; }
        """)

        action_config = self.options_menu.addAction(self.tr("⚙️ Configure Project"))
        action_config.triggered.connect(lambda: self.on_open_kitsu("/production-settings"))

        if self.user_role == "td":
            self.options_menu.addSeparator()
            self.options_menu.addAction(self.tr("📦 Archive Project"))
            self.options_menu.addSeparator()

            red_pixmap = QPixmap(12, 12)
            red_pixmap.fill(QColor("#EF4444"))
            action_delete = self.options_menu.addAction(QIcon(red_pixmap), self.tr("Delete Project"))
            action_delete.triggered.connect(self._on_delete_requested)

        self.btn_options.setMenu(self.options_menu)
        header_layout.addWidget(self.btn_options)
        main_layout.addLayout(header_layout)

        self.thumb_stack = QStackedWidget()
        self.thumb_stack.setFixedHeight(130)
        self.thumb_stack.setStyleSheet("QStackedWidget { background-color: #0F172A; border-radius: 8px; border: 1px solid #1E293B; }")

        self.page_placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.page_placeholder)
        placeholder_layout.setAlignment(Qt.AlignCenter)
        self.lbl_placeholder_text = QLabel(self.tr("AWESOME PROJECT"))
        self.lbl_placeholder_text.setStyleSheet("color: #64748B; font-size: 10px; font-weight: bold;")
        placeholder_layout.addWidget(self.lbl_placeholder_text)

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("border-radius: 8px; background-color: transparent;")

        self.thumb_stack.addWidget(self.page_placeholder)
        self.thumb_stack.addWidget(self.thumb_label)
        main_layout.addWidget(self.thumb_stack)

        title_layout = QHBoxLayout()
        self.project_name = self.project_data.get("name", self.tr("Unknown Project"))
        self.lbl_title = QLabel(self.project_name)
        self.lbl_title.setStyleSheet("color: #F8FAFC; font-size: 15px; font-weight: bold;")
        title_layout.addWidget(self.lbl_title)
        title_layout.addStretch()

        self.lbl_badge = QLabel(self.tr("Checking..."))
        self.lbl_badge.setAlignment(Qt.AlignCenter)
        self.lbl_badge.setStyleSheet("background-color: #0F172A; color: #94A3B8; border: 1px solid #334155; border-radius: 6px; padding: 2px 8px; font-size: 10px; font-weight: bold;")
        title_layout.addWidget(self.lbl_badge)
        main_layout.addLayout(title_layout)

        self.lbl_sync_status = QLabel(self.tr("🗄️ Checking..."))
        self.lbl_sync_status.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: bold;")
        main_layout.addWidget(self.lbl_sync_status)

        self.actions_layout = QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 5, 0, 0)
        self.actions_layout.setSpacing(10)
        main_layout.addLayout(self.actions_layout)

        self.btn_kitsu_dropdown = QToolButton()
        self.btn_kitsu_dropdown.setPopupMode(QToolButton.InstantPopup)
        self.btn_kitsu_dropdown.setCursor(Qt.PointingHandCursor)
        self.btn_kitsu_dropdown.setFixedHeight(35)

        kitsu_menu = QMenu(self)
        kitsu_menu.setStyleSheet("QMenu { background-color: #0F172A; color: #F8FAFC; border: 1px solid #334155; border-radius: 6px; } QMenu::item { padding: 8px 25px; } QMenu::item:selected { background-color: #3B82F6; }")
        kitsu_menu.addAction("To: Assets", lambda: self.on_open_kitsu("/assets"))
        kitsu_menu.addAction("To: Shots", lambda: self.on_open_kitsu("/shots"))
        kitsu_menu.addAction("To: Sequences", lambda: self.on_open_kitsu("/sequences"))
        kitsu_menu.addAction("To: Edit", lambda: self.on_open_kitsu("/edits"))
        self.btn_kitsu_dropdown.setMenu(kitsu_menu)

        self.btn_watchtower = QPushButton("")
        self.btn_watchtower.setFixedSize(35, 35)
        self.btn_watchtower.setCursor(Qt.PointingHandCursor)
        self.btn_watchtower.setToolTip(self.tr("Open Watchtower Dashboard"))

        wt_icon_path = Path("assets/icons/radar.svg")
        if wt_icon_path.exists() and wt_icon_path.is_file():
            try:
                with open(wt_icon_path, "r", encoding="utf-8") as handle:
                    svg_content = handle.read()
                svg_content = svg_content.replace("currentColor", "#94A3B8")
                svg_content = svg_content.replace('stroke-width="2"', 'stroke-width="2.5"')
                pixmap = QPixmap()
                pixmap.loadFromData(svg_content.encode("utf-8"), "SVG")
                self.btn_watchtower.setIcon(QIcon(pixmap))
            except Exception:  # noqa: BLE001
                pass
        self.btn_watchtower.clicked.connect(self._on_watchtower_clicked)

        self.btn_primary_action = QPushButton()
        self.btn_primary_action.setFixedHeight(35)
        self.btn_primary_action.setCursor(Qt.PointingHandCursor)

        if self.user_role == "td":
            self.btn_kitsu_dropdown.setText("Open in Kitsu ▼")
            self.btn_kitsu_dropdown.setStyleSheet("""
                QToolButton { background-color: #F97316; color: white; font-weight: bold; border-radius: 6px; padding: 0 15px; }
                QToolButton:hover { background-color: #EA580C; }
                QToolButton::menu-indicator { image: none; }
            """)
            self.btn_kitsu_dropdown.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            self.btn_watchtower.setStyleSheet("""
                QPushButton { background: transparent; border: 1px solid #334155; border-radius: 6px; font-size: 16px;}
                QPushButton:hover { background-color: #334155; }
            """)

            self.actions_layout.addWidget(self.btn_kitsu_dropdown)
            self.actions_layout.addWidget(self.btn_watchtower)
            self.btn_primary_action.hide()

        else:
            self.btn_kitsu_dropdown.setText("▼")
            kitsu_icon_path = Path("assets/icons/kitsu.svg")
            if kitsu_icon_path.exists() and kitsu_icon_path.is_file():
                try:
                    with open(kitsu_icon_path, "r", encoding="utf-8") as handle:
                        svg_content = handle.read()
                    svg_content = svg_content.replace("currentColor", "#F97316")
                    svg_content = svg_content.replace('stroke-width="2"', 'stroke-width="2.5"')
                    pixmap = QPixmap()
                    pixmap.loadFromData(svg_content.encode("utf-8"), "SVG")
                    self.btn_kitsu_dropdown.setIcon(QIcon(pixmap))
                    self.btn_kitsu_dropdown.setIconSize(QSize(18, 18))
                except Exception:  # noqa: BLE001
                    self.btn_kitsu_dropdown.setText("🎬 ▼")
            else:
                self.btn_kitsu_dropdown.setText("🎬 ▼")

            self.btn_kitsu_dropdown.setStyleSheet("""
                QToolButton { background: transparent; color: #F97316; border: 1px solid #334155; border-radius: 6px; padding: 0 10px; font-weight: bold;}
                QToolButton:hover { background-color: rgba(249, 115, 22, 0.1); border-color: #F97316; }
                QToolButton::menu-indicator { image: none; }
            """)

            self.actions_layout.addWidget(self.btn_primary_action, stretch=1)
            self.actions_layout.addWidget(self.btn_kitsu_dropdown)

            if self.user_role == "manager":
                self.btn_watchtower.setStyleSheet("""
                    QPushButton { background: transparent; border: 1px solid #334155; border-radius: 6px; font-size: 16px;}
                    QPushButton:hover { background-color: #334155; }
                """)
                self.actions_layout.addWidget(self.btn_watchtower)
            else:
                self.btn_watchtower.hide()

    def _apply_status(self, status: dict) -> None:
        """Update the sync badge and primary action button from computed state."""
        if status["is_installed"] and self.project_dir:
            self.lbl_sync_status.setText(self.tr("🗄️ 🟢 Ready on Disk"))
            self.lbl_sync_status.setStyleSheet("color: #10B981; font-size: 12px; font-weight: bold;")
            self.lbl_badge.setText(status["badge_text"])

            if self.user_role != "td":
                if self.user_role == "manager":
                    self.btn_primary_action.setText(self.tr("Pipeline Wizard"))
                    self.btn_primary_action.setStyleSheet("background-color: #F59E0B; color: #0F172A; font-weight: bold; border-radius: 6px; border: none;")
                    if self.on_open_wizard:
                        self.btn_primary_action.clicked.connect(lambda: self.on_open_wizard(self.project_name))
                else:
                    self.btn_primary_action.setText(self.tr("Launch Project"))
                    self.btn_primary_action.setStyleSheet("background-color: #3B82F6; color: white; font-weight: bold; border-radius: 6px; border: none;")
                    self.btn_primary_action.clicked.connect(lambda: self.on_launch(self.project_dir))
        else:
            self.lbl_sync_status.setText(self.tr("🗄️ ⚪ Cloud Only"))
            self.lbl_sync_status.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: bold;")
            self.lbl_badge.setText(self.tr("Not Mounted"))

            if self.user_role != "td":
                self.btn_primary_action.setText(self.tr("Install Workspace ↓"))
                self.btn_primary_action.setStyleSheet("background-color: #10B981; color: #0F172A; font-weight: bold; border-radius: 6px; border: none;")
                self.btn_primary_action.clicked.connect(lambda: self._request_install(self.project_dir))

    def _request_install(self, project_dir) -> None:
        self.btn_primary_action.setEnabled(False)
        self.btn_primary_action.setText(self.tr("Installing..."))
        self.btn_primary_action.setStyleSheet("background-color: #94A3B8; color: #0F172A; font-weight: bold; border-radius: 6px; border: none;")
        self.on_install(project_dir)

    def set_install_result(self, success: bool, message: str) -> None:
        """Re-enable the install button after a failure (success triggers a refresh)."""
        if not success:
            self.btn_primary_action.setEnabled(True)
            self.btn_primary_action.setText(self.tr("Retry Install ↓"))
            self.btn_primary_action.setStyleSheet("background-color: #10B981; color: #0F172A; font-weight: bold; border-radius: 6px; border: none;")

    def _on_watchtower_clicked(self) -> None:
        if self.project_dir:
            self.on_watchtower(self.project_dir)
        else:
            QMessageBox.warning(self, "Watchtower", self.tr("The project must be mounted on your disk to visualize Watchtower."))

    def _on_delete_requested(self) -> None:
        dialog = DeleteProjectDialog(self, self.project_name)
        if dialog.exec() == QDialog.Accepted:
            self.on_delete(self.project_name)

    def _load_thumbnail(self) -> None:
        project_id = self.project_data.get("id")
        self.worker = ProjectThumbnailWorker(self.thumbnail_fetcher, project_id, self.token, self.host)
        self.worker.image_downloaded.connect(self._on_thumbnail_ready)
        self.worker.error_occurred.connect(self._on_thumbnail_error)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _on_thumbnail_ready(self, img_bytes: bytes) -> None:
        image = QImage.fromData(img_bytes)
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            pixmap = pixmap.scaled(290, 140, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x_offset = (pixmap.width() - 290) // 2
            y_offset = (pixmap.height() - 140) // 2
            self.thumb_label.setPixmap(pixmap.copy(x_offset, y_offset, 290, 140))
            self.thumb_stack.setCurrentIndex(1)
        else:
            self._on_thumbnail_error(self.tr("Corrupted file"))

    def _on_thumbnail_error(self, message: str) -> None:
        self.thumb_stack.setCurrentIndex(0)
