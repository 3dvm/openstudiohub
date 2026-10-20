# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/components/comment_panel.py
# Architectural role: UI Component / Task comment drawer (PySide6)
# =========================================================================================

"""Right-side task comment drawer.

Pure presentation: the owning view feeds ``set_task``/``set_comments`` and
listens to ``send_requested``/``close_requested``. Comment text is rendered as
plain text (no HTML) to avoid injection from the Kitsu payload.
"""

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.domain.production.comments import comment_parent_id, normalize_checklist


class CommentPanel(QFrame):
    close_requested = Signal()
    send_requested = Signal(str)
    checklist_toggled = Signal(str, int, bool)  # (comment_id, item_index, checked)

    PANEL_WIDTH = 360

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CommentPanel")
        self.setStyleSheet(
            "QFrame#CommentPanel { background-color: #0F172A; border-left: 1px solid #334155; }"
        )
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)

        self._task = None
        self._checklist_enabled = True
        self._checklist_boxes = []
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        self.lbl_title = QLabel(self.tr("Comments"))
        self.lbl_title.setStyleSheet("color: #F8FAFC; font-size: 14px; font-weight: bold;")
        self.lbl_subtitle = QLabel("")
        self.lbl_subtitle.setStyleSheet("color: #94A3B8; font-size: 11px;")
        title_box.addWidget(self.lbl_title)
        title_box.addWidget(self.lbl_subtitle)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            "QPushButton { background: transparent; color: #94A3B8; border: none; font-size: 14px; }"
            "QPushButton:hover { color: #F8FAFC; }"
        )
        btn_close.clicked.connect(self.close_requested.emit)

        header.addLayout(title_box, stretch=1)
        header.addWidget(btn_close, alignment=Qt.AlignTop)
        layout.addLayout(header)

        self.lbl_state = QLabel("")
        self.lbl_state.setStyleSheet("color: #94A3B8; font-size: 12px;")
        self.lbl_state.setWordWrap(True)
        layout.addWidget(self.lbl_state)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("InvisibleScrollArea")
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_widget)
        layout.addWidget(self.scroll, stretch=1)

        self.composer = QPlainTextEdit()
        self.composer.setPlaceholderText(self.tr("Write a comment… (Ctrl+Enter to send)"))
        self.composer.setFixedHeight(76)
        self.composer.setStyleSheet(
            "QPlainTextEdit { background-color: #1E293B; color: #F8FAFC; border: 1px solid #334155;"
            " border-radius: 6px; padding: 6px; font-size: 12px; }"
            "QPlainTextEdit:focus { border-color: #3B82F6; }"
        )
        self.composer.textChanged.connect(self._sync_send_button)
        layout.addWidget(self.composer)

        self.btn_send = QPushButton(self.tr("Send"))
        self.btn_send.setFixedHeight(32)
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.setStyleSheet(
            "QPushButton { background-color: #3B82F6; color: white; font-weight: bold;"
            " border-radius: 6px; border: none; }"
            "QPushButton:hover { background-color: #2563EB; }"
            "QPushButton:disabled { background-color: #334155; color: #94A3B8; }"
        )
        self.btn_send.clicked.connect(self._on_send)
        layout.addWidget(self.btn_send)

        self.composer.installEventFilter(self)
        self._sync_send_button()

    def eventFilter(self, obj, event):
        if obj is self.composer and event.type() == QEvent.Type.KeyPress:
            if (
                event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and event.modifiers() & Qt.ControlModifier
            ):
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_task(self, task) -> None:
        self._task = task or {}
        entity = (task or {}).get("entity_name") or (task or {}).get("name") or "Task"
        task_type = (task or {}).get("task_type_name") or ""
        project = (task or {}).get("project_name") or ""
        self.lbl_title.setText(f"{entity} - {task_type}" if task_type else str(entity))
        self.lbl_subtitle.setText(project)
        self.set_error("")
        self.clear_composer()

    def set_comments(self, comments: list) -> None:
        scroll_value = self.scroll.verticalScrollBar().value()
        self._clear_comments()
        if not comments:
            self.lbl_state.setText(self.tr("No comments yet."))
            self.lbl_state.show()
            return
        self.lbl_state.hide()
        for comment in comments:
            self.list_layout.insertWidget(self.list_layout.count() - 1, self._build_bubble(comment))

        def restore_scroll() -> None:
            try:
                self.scroll.verticalScrollBar().setValue(scroll_value)
            except RuntimeError:
                pass

        QTimer.singleShot(0, restore_scroll)

    def set_checklist_enabled(self, enabled: bool) -> None:
        self._checklist_enabled = bool(enabled)
        for box in list(self._checklist_boxes):
            try:
                box.setEnabled(self._checklist_enabled)
            except RuntimeError:
                continue

    def set_loading(self, loading: bool) -> None:
        if loading:
            self.lbl_state.setText(self.tr("Loading comments…"))
            self.lbl_state.show()

    def set_error(self, message: str) -> None:
        if message:
            self.lbl_state.setText(self.tr(f"Could not load comments: {message}"))
            self.lbl_state.show()

    def set_posting(self, posting: bool) -> None:
        self.btn_send.setEnabled(not posting and bool(self.composer.toPlainText().strip()))
        self.btn_send.setText(self.tr("Sending…") if posting else self.tr("Send"))

    def clear_composer(self) -> None:
        self.composer.clear()

    def comment_text(self) -> str:
        return self.composer.toPlainText()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _on_send(self) -> None:
        text = self.composer.toPlainText().strip()
        if not text:
            return
        self.send_requested.emit(text)

    def _sync_send_button(self) -> None:
        self.btn_send.setEnabled(bool(self.composer.toPlainText().strip()))

    def _clear_comments(self) -> None:
        self._checklist_boxes = []
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_bubble(self, comment: dict) -> QWidget:
        wrapper = QFrame()
        wrapper.setStyleSheet(
            "QFrame { background-color: #1E293B; border: 1px solid #334155; border-radius: 8px; }"
        )
        indent = 18 if comment_parent_id(comment) else 0
        outer = QHBoxLayout(wrapper)
        outer.setContentsMargins(indent, 8, 8, 8)

        bubble = QVBoxLayout()
        bubble.setSpacing(3)

        meta = QHBoxLayout()
        author = QLabel(str(comment.get("_author") or "Unknown"))
        author.setStyleSheet("color: #F8FAFC; font-size: 11px; font-weight: bold; border: none;")
        created = QLabel(str(comment.get("_created") or ""))
        created.setStyleSheet("color: #64748B; font-size: 10px; border: none;")
        meta.addWidget(author)
        meta.addStretch()
        if comment.get("_status"):
            status = QLabel(str(comment["_status"]))
            status.setStyleSheet(
                "background-color: #0F172A; color: #93C5FD; border: 1px solid #334155;"
                " border-radius: 6px; padding: 0 6px; font-size: 9px;"
            )
            meta.addWidget(status)
        meta.addWidget(created)
        bubble.addLayout(meta)

        body_text = str(comment.get("text") or comment.get("comment") or "")
        if body_text:
            body = QLabel(body_text)
            body.setWordWrap(True)
            body.setTextFormat(Qt.PlainText)
            body.setStyleSheet("color: #CBD5E1; font-size: 12px; border: none; background: transparent;")
            bubble.addWidget(body)

        attachments = comment.get("attachment_files") or []
        if attachments:
            note = QLabel(self.tr(f"📎 {len(attachments)} attachment(s)"))
            note.setStyleSheet("color: #94A3B8; font-size: 10px; border: none;")
            bubble.addWidget(note)

        checklist = normalize_checklist(comment.get("_checklist") or comment.get("checklist"))
        if checklist:
            checked_count = sum(1 for item in checklist if item["checked"])
            header = QLabel(self.tr(f"Checklist {checked_count}/{len(checklist)}"))
            header.setStyleSheet(
                "color: #93C5FD; font-size: 10px; font-weight: bold;"
                " border: none; margin-top: 4px;"
            )
            bubble.addWidget(header)
            for index, item in enumerate(checklist):
                self._add_checklist_item(bubble, comment, index, item)

        outer.addLayout(bubble, stretch=1)
        return wrapper

    def _add_checklist_item(self, layout, comment: dict, index: int, item: dict) -> None:
        text = str(item.get("text") or "").replace("&", "&&")
        checkbox = QCheckBox(text)
        checkbox.setStyleSheet(
            "QCheckBox { color: #CBD5E1; font-size: 11px; border: none; background: transparent; }"
            "QCheckBox::indicator { width: 14px; height: 14px; }"
        )
        checkbox.setChecked(bool(item.get("checked")))
        self._apply_checklist_strike(checkbox, bool(item.get("checked")))
        checkbox.setEnabled(self._checklist_enabled)
        comment_id = str(comment.get("id", ""))
        checkbox.toggled.connect(
            lambda checked, cid=comment_id, i=index, box=checkbox: self._on_checklist_toggled(
                box, cid, i, checked
            )
        )
        self._checklist_boxes.append(checkbox)
        layout.addWidget(checkbox)

    def _on_checklist_toggled(self, checkbox, comment_id: str, index: int, checked: bool) -> None:
        self._apply_checklist_strike(checkbox, checked)
        self.checklist_toggled.emit(comment_id, index, checked)

    @staticmethod
    def _apply_checklist_strike(checkbox: QCheckBox, checked: bool) -> None:
        font = checkbox.font()
        font.setStrikeOut(checked)
        checkbox.setFont(font)
