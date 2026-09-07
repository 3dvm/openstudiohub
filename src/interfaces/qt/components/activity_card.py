# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/activity_card.py
# Architectural role: UI Component / Activity Feed Card (PySide6)
# =========================================================================================

"""Visual component for the Activity Feed (inbox)."""

import webbrowser

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from src.application.services.production_service import ProductionService


class AcknowledgeWorker(QThread):
    """Sends the read receipt to Kitsu asynchronously."""

    ack_finished = Signal(bool)

    def __init__(self, production_service: ProductionService, task_id: str, comment_id: str) -> None:
        super().__init__()
        self.production_service = production_service
        self.task_id = task_id
        self.comment_id = comment_id

    def run(self) -> None:
        ok = self.production_service.acknowledge_activity(self.task_id, self.comment_id)
        self.ack_finished.emit(ok)


class ActivityCard(QFrame):
    def __init__(self, parent, activity_data: dict, production_service: ProductionService, on_acknowledge_callback, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.data = activity_data
        self.production_service = production_service
        self.on_acknowledge_callback = on_acknowledge_callback

        self.setObjectName("FloatingCard")
        self.setStyleSheet("""
            QFrame#FloatingCard {
                background-color: #2E3643;
                border: 1px solid #141820;
                border-radius: 8px;
            }
        """)

        self._build_ui()

    def _get_contrast_text_color(self, hex_color: str) -> str:
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
        main_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        author_name = self.data.get("author", {}).get("first_name", "U")
        lbl_avatar = QLabel(author_name[0].upper())
        lbl_avatar.setFixedSize(28, 28)
        lbl_avatar.setAlignment(Qt.AlignCenter)
        lbl_avatar.setStyleSheet("background-color: #3B82F6; color: white; border-radius: 14px; font-weight: bold;")
        header_layout.addWidget(lbl_avatar)

        entity_name = self.data.get("entity", {}).get("name", "Unknown")
        task_name = self.data.get("task_type", {}).get("name", "Task")
        lbl_title = QLabel(f"<b>{author_name}</b> on {entity_name} - {task_name}")
        lbl_title.setStyleSheet("color: #E2E8F0; font-size: 12px;")
        lbl_title.setWordWrap(True)
        header_layout.addWidget(lbl_title, stretch=1)

        main_layout.addLayout(header_layout)

        text = self.data.get("text", "...")
        if len(text) > 100:
            text = text[:97] + "..."

        lbl_text = QLabel(text)
        lbl_text.setStyleSheet("color: #94A3B8; font-size: 11px;")
        lbl_text.setWordWrap(True)
        main_layout.addWidget(lbl_text)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 5, 0, 0)

        lbl_status_tag = QLabel("Status:")
        lbl_status_tag.setStyleSheet("color: #64748B; font-size: 11px;")
        footer_layout.addWidget(lbl_status_tag)

        status_data = self.data.get("task_status", {})
        s_name = status_data.get("short_name", "???")
        s_color = status_data.get("color", "#444444")
        t_color = self._get_contrast_text_color(s_color)

        lbl_badge = QLabel(s_name.upper())
        lbl_badge.setAlignment(Qt.AlignCenter)
        lbl_badge.setStyleSheet(f"""
            background-color: {s_color};
            color: {t_color};
            border-radius: 6px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: bold;
        """)
        footer_layout.addWidget(lbl_badge)

        footer_layout.addStretch()

        self.btn_action = QPushButton("Open _Mark Read")
        self.btn_action.setCursor(Qt.PointingHandCursor)
        self.btn_action.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
        self.btn_action.clicked.connect(self._run_action)
        footer_layout.addWidget(self.btn_action)

        main_layout.addLayout(footer_layout)

    def _run_action(self) -> None:
        self.btn_action.setEnabled(False)
        self.btn_action.setText("Processing...")

        url = self.data.get("task_url")
        if url:
            webbrowser.open(url)

        task_id = self.data.get("task_id", "")
        comment_id = self.data.get("id", "")

        self.worker = AcknowledgeWorker(self.production_service, task_id, comment_id)
        self.worker.ack_finished.connect(lambda _ok: self.on_acknowledge_callback(self))
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()
