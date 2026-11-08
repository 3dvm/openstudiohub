# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/preview_poster.py
# Architectural role: UI component / still-preview poster with play overlay
# =========================================================================================

"""Poster shown before entering the sequence player."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QWidget

_ASSET_DIR = Path("assets/icons")


class PreviewPoster(QWidget):
    play_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PreviewPoster")
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.image_label = QLabel(self.tr("Select a shot to see its preview."))
        self.image_label.setObjectName("MutedLabel")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(220)
        self.image_label.setWordWrap(True)
        layout.addWidget(self.image_label, 0, 0)

        self.btn_play = QPushButton()
        self.btn_play.setObjectName("PosterPlayButton")
        self.btn_play.setIcon(QIcon(str(_ASSET_DIR / "play.svg")))
        self.btn_play.setIconSize(QSize(32, 32))
        self.btn_play.setFixedSize(72, 72)
        self.btn_play.setToolTip(self.tr("Play rendered sequence"))
        self.btn_play.clicked.connect(self.play_requested)
        layout.addWidget(self.btn_play, 0, 0, Qt.AlignCenter)
        self.btn_play.hide()

    def set_state(
        self,
        *,
        preview_path: Path | None = None,
        fallback_frame: Path | None = None,
        has_sequence: bool = False,
        message: str = "",
    ) -> None:
        image = preview_path if preview_path and preview_path.is_file() else fallback_frame
        if image is not None and image.is_file():
            pixmap = QPixmap(str(image))
            if not pixmap.isNull():
                self.image_label.setText("")
                self.image_label.setPixmap(
                    pixmap.scaled(
                        max(520, self.image_label.width()),
                        max(280, self.image_label.height()),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
                self.image_label.setToolTip(str(image))
            else:
                self._show_empty(message)
        else:
            self._show_empty(message)

        self.btn_play.setVisible(has_sequence)
        self.btn_play.setEnabled(has_sequence)
        self.btn_play.setToolTip(
            self.tr("Play rendered sequence")
            if has_sequence
            else self.tr("No rendered sequence yet.")
        )

    def _show_empty(self, message: str) -> None:
        self.image_label.setPixmap(
            QIcon(str(_ASSET_DIR / "image-off.svg")).pixmap(96, 96)
        )
        self.image_label.setText(
            message
            or self.tr("No preview or rendered frames for this shot.")
        )
