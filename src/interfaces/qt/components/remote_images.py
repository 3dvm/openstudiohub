"""Asynchronous Kitsu thumbnail loading for shell widgets."""

from __future__ import annotations

import requests
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap

from src.infrastructure.qt_worker import ManagedWorker


def thumbnail_url(host: str, resource: str, object_id: str) -> str:
    base = str(host or "").rstrip("/")
    target = str(object_id or "").strip()
    kind = str(resource or "").strip().strip("/")
    if not base or not target or not kind:
        return ""
    return f"{base}/pictures/thumbnails/{kind}/{target}.png"


class RemoteImageWorker(ManagedWorker):
    """Download an authenticated Kitsu thumbnail off the UI thread."""

    image_ready = Signal(bytes)

    def __init__(self, url: str, token: str) -> None:
        super().__init__()
        self.url = url
        self.token = token

    def run(self) -> None:
        if not self.url:
            return
        try:
            response = requests.get(
                self.url,
                headers={"Authorization": f"Bearer {self.token or ''}"},
                timeout=10,
            )
            if response.status_code == 200 and response.content:
                self.image_ready.emit(response.content)
        except Exception as error:  # noqa: BLE001 - fall back to the local icon
            print(f"[RemoteImage] Download failed: {error}")


def pixmap_from_bytes(data: bytes) -> QPixmap | None:
    pixmap = QPixmap()
    if not data or not pixmap.loadFromData(data):
        return None
    return pixmap


def circular_icon(data: bytes, size: int = 28) -> QIcon | None:
    source = pixmap_from_bytes(data)
    if source is None:
        return None
    scaled = source.scaled(
        QSize(size, size),
        Qt.KeepAspectRatioByExpanding,
        Qt.SmoothTransformation,
    )
    target = QPixmap(size, size)
    target.fill(Qt.transparent)
    painter = QPainter(target)
    try:
        clip = QPainterPath()
        clip.addEllipse(0, 0, size, size)
        painter.setClipPath(clip)
        x = max(0, (scaled.width() - size) // 2)
        y = max(0, (scaled.height() - size) // 2)
        painter.drawPixmap(0, 0, scaled, x, y, size, size)
    finally:
        painter.end()
    return QIcon(target)
