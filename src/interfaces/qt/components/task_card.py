# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/components/task_card.py
# Rol Arquitectónico: UI Component / Reusable Task Card (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.8.0 (CTA Logic Matrix Fix)
# =========================================================================================

"""
Reusable visual component for Task Cards in the Artist Dashboard.
Uses ConfigFactory to resolve dynamic VFS local directory paths natively.
Implements a strict priority matrix for Call-To-Action (CTA) rendering.
"""

import webbrowser
import requests
from pathlib import Path

from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QSizePolicy, QStackedWidget,
                               QWidget)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QIcon


class ThumbnailWorker(QThread):
    """QThread dedicado a la descarga de miniaturas por HTTP."""
    image_downloaded = Signal(bytes)
    error_occurred = Signal(str)

    def __init__(self, entity_id: str, token: str, host_url: str):
        super().__init__()
        self.entity_id = entity_id
        self.token = token
        self.host_url = host_url

    def run(self):
        if not self.entity_id:
            self.error_occurred.emit("No Entity ID Available")
            return

        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }

            entity_url = f"{self.host_url}/data/entities/{self.entity_id}"

            ent_resp = requests.get(entity_url, headers=headers, timeout=10)
            if ent_resp.status_code != 200:
                self.error_occurred.emit(f"Entity not found (HTTP {ent_resp.status_code})")
                return
            
            entity_data = ent_resp.json()
            preview_id = entity_data.get("preview_file_id")
            
            if not preview_id:
                self.error_occurred.emit("Entity has no preview image")
                return

            img_url = f"{self.host_url}/pictures/thumbnails/preview-files/{preview_id}.png"
            img_resp = requests.get(img_url, headers=headers, timeout=10)

            print(f"[DEBUG WORKER] Pidiendo imagen a: {img_url}")

            #headers = {"Authorization": f"Bearer {self.token}"}
            
            #response = requests.get(img_url, headers=headers, timeout=10)

            #print(f"[DEBUG WORKER] Respuesta: HTTP {response.status_code} | Peso: {len(response.content)} bytes")
            
            if img_resp.status_code == 200:
                self.image_downloaded.emit(img_resp.content)
            else:
                self.error_occurred.emit(f"Thumbnail not found (HTTP {img_resp.status_code})")
            
        except Exception as e:
            print(f"[UI THUMBNAIL ERROR] Download failed: {e}")
            self.error_occurred.emit("Network connection error")


class TaskCard(QFrame):
    def __init__(self, parent, task_data: dict, project_root: Path, is_installed: bool, 
                 auth_manager, config_factory, on_launch_callback, on_install_callback, 
                 can_work: bool = True, blocked_reason: str = "", **kwargs):
        super().__init__(parent, **kwargs)
        
        self.task_data = task_data
        self.project_root = project_root
        self.is_installed = is_installed
        self.auth_manager = auth_manager
        self.config_factory = config_factory
        
        self.can_work = can_work
        self.blocked_reason = blocked_reason
        
        self.on_launch_callback = on_launch_callback
        self.on_install_callback = on_install_callback
        
        if self.project_root and self.config_factory:
            vfs_local = self.config_factory.get_vfs_local_name()
            self.config_path = self.project_root / vfs_local / "project_config.json"
        else:
            self.config_path = None
        
        self.setObjectName("FloatingCard")
        #self.setMinimumHeight(280)
        #self.setMinimumWidth(380)
        self.setFixedSize(320, 280)

        self._build_ui()
        self._cargar_miniatura()

    def _obtener_color_texto_contraste(self, hex_color: str) -> str:
        """Calcula luminancia sRGB relativa para el contraste del badge."""
        if not hex_color: return "white"
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6: return "white"
        try:
            r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            return "#0F172A" if luminance > 0.5 else "#F8FAFC"
        except Exception:
            return "white"

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # ---------------------------------------------------------
        # Fila Superior: Título de Entidad y Tipo de Tarea
        # ---------------------------------------------------------
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        entity_name = self.task_data.get('entity_name', self.task_data.get('name', 'Unknown Entity'))
        task_type = self.task_data.get('task_type_name', 'Task')
        title_text = f"{entity_name} - {task_type}"
        
        self.title_label = QLabel(title_text)
        self.title_label.setObjectName("H2Title")
        self.title_label.setStyleSheet("color: #F8FAFC; font-size: 14px; font-weight: bold;")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        status_color = self.task_data.get("task_status_color", self.task_data.get("status_color", "#444444"))
        status_name = self.task_data.get("task_status_name", self.task_data.get("status_name", "TODO"))
        text_color_contraste = self._obtener_color_texto_contraste(status_color)
        
        self.status_badge = QLabel(status_name.upper())
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setFixedHeight(22)
        self.status_badge.setStyleSheet(f"""
            background-color: {status_color};
            color: {text_color_contraste};
            border-radius: 11px;
            font-size: 10px;
            font-weight: bold;
            padding: 0 10px;
        """)
        header_layout.addWidget(self.status_badge)
        main_layout.addLayout(header_layout)

        # ---------------------------------------------------------
        # Fila Central: Thumbnail Cinematográfico
        # ---------------------------------------------------------
        # self.thumb_frame = QFrame(self)
        # self.thumb_frame.setFixedHeight(160)
        # self.thumb_frame.setStyleSheet("background-color: #0B1120; border-radius: 8px;") 
        #
        # thumb_layout = QVBoxLayout(self.thumb_frame)
        # thumb_layout.setContentsMargins(5, 5, 5, 5)
        #
        # self.thumb_label = QLabel(self.tr("No Thumbnail Available"))
        # self.thumb_label.setObjectName("PlaceholderText")
        # self.thumb_label.setAlignment(Qt.AlignCenter)
        # self.thumb_label.setStyleSheet("color: #475569; font-style: italic; font-size: 12px;")
        # thumb_layout.addWidget(self.thumb_label)
        # main_layout.addWidget(self.thumb_frame)

        # 2. Miniatura Dinámica (QStackedWidget)
        self.thumb_stack = QStackedWidget()
        self.thumb_stack.setFixedHeight(140)
        self.thumb_stack.setStyleSheet("QStackedWidget { background-color: #0F172A; border-radius: 8px; border: 1px solid #1E293B; }")
        
        # --- Página 0: Placeholder Inteligente ---
        self.page_placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.page_placeholder)
        placeholder_layout.setAlignment(Qt.AlignCenter)
        placeholder_layout.setSpacing(10)
        
        self.lbl_placeholder_icon = QLabel()
        self.lbl_placeholder_icon.setAlignment(Qt.AlignCenter)
        
        # Resolver nombre de tarea a SVG
        task_type = self.task_data.get("task_type_name", "generic").lower()
        
        icon_map = {
            "storyboard": "task-storyboard.svg",
            "layout": "task-layout.svg",
            "modeling": "task-modeling.svg",
            "rigging": "task-rigging.svg",
            "animation": "task-animation.svg",
            "lighting": "task-lighting.svg",
            "compositing": "task-compositing.svg",
            "editorial": "task-editorial.svg",
            "edit": "task-editorial.svg"
        }
        
        svg_filename = icon_map.get(task_type, "task-generic.svg")
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
            
        # Formatear el texto (ej: "ANIMATION PLACEHOLDER")
        safe_task_name = self.task_data.get("task_type_name", "TASK").upper()
        self.lbl_placeholder_text = QLabel(self.tr(f"{safe_task_name} TASK"))
        self.lbl_placeholder_text.setAlignment(Qt.AlignCenter)
        self.lbl_placeholder_text.setStyleSheet("color: #64748B; font-size: 10px; font-weight: bold; letter-spacing: 1px; background: transparent;")
        
        placeholder_layout.addStretch()
        placeholder_layout.addWidget(self.lbl_placeholder_icon)
        placeholder_layout.addWidget(self.lbl_placeholder_text)
        placeholder_layout.addStretch()
        
        # --- Página 1: Imagen Real ---
        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("border-radius: 8px; background-color: transparent;")
        
        self.thumb_stack.addWidget(self.page_placeholder)
        self.thumb_stack.addWidget(self.thumb_label)
        
        main_layout.addWidget(self.thumb_stack)


        # ---------------------------------------------------------
        # Fila Inferior: Botones de Acción Modulares
        # ---------------------------------------------------------
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

        # Matriz Condicional de Renderizado del CTA Primario (Corregida)
        if not self.project_root:
            self.action_btn = QPushButton(self.tr("Folder Missing on NAS"))
            self.action_btn.setEnabled(False)
            self.action_btn.setStyleSheet("QPushButton { border: 1px solid #EF4444; color: #EF4444; background: transparent; border-radius: 6px; font-weight: bold; font-size: 13px; }")
        
        elif not self.can_work:
            # Prioridad Absoluta: Si está bloqueada, no importa si está instalada o no.
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
            self.action_btn.clicked.connect(
                lambda checked=False: self.on_launch_callback(self.project_root, self.config_path, self.task_data)
            )
        
        else:
            self.action_btn = QPushButton(self.tr("Install Project Locally"))
            self.action_btn.setCursor(Qt.PointingHandCursor)
            self.action_btn.setStyleSheet("""
                QPushButton { border: 1px solid #F59E0B; color: #F59E0B; background: transparent; border-radius: 6px; font-weight: bold; font-size: 13px; }
                QPushButton:hover { background-color: rgba(245, 158, 11, 0.1); }
            """)
            self.action_btn.clicked.connect(
                lambda checked=False: self.on_install_callback(self.project_root, self.task_data)
            )

        self.action_btn.setFixedHeight(36)
        self.action_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_layout.addWidget(self.action_btn)

        main_layout.addLayout(btn_layout)

    def _cargar_miniatura(self):
        entity_id = self.task_data.get("entity_id")
        
        # 2. Extraemos el ID del archivo de previsualización de la entidad
        # preview_id = entity_data.get("preview_file_id")
        #
        # task_name = self.task_data.get('name', 'Unknown')
        # print(f"\n[DEBUG THUMB] Tarea: '{task_name}' | Preview ID extraído: {preview_id}")
        
        # Fallback por si Gazu devuelve la data aplanada
        # if not preview_id:
        #     print(f"[DEBUG THUMB] ❌ Cancelando descarga: preview_id es nulo o vacío.")
        #     preview_id = self.task_data.get("preview_file_id")

        if not entity_id:
            print(f"[DEBUG THUMB] ❌ Cancelando descarga: preview_id es nulo o vacío.")
            self._on_thumbnail_error("No preview image mapped")
            return

        token = self.auth_manager.get_current_token()
        base_url = self.auth_manager.kitsu_host
        
        self.worker = ThumbnailWorker(entity_id, token, base_url)
        self.worker.image_downloaded.connect(self._on_thumbnail_ready)
        self.worker.error_occurred.connect(self._on_thumbnail_error)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _on_thumbnail_ready(self, img_bytes: bytes):
        image = QImage.fromData(img_bytes)
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            pixmap = pixmap.scaled(self.thumb_stack.width(), self.thumb_stack.height(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self.thumb_label.setPixmap(pixmap)
            self.thumb_label.setText("") 

            self.thumb_stack.setCurrentIndex(1)
        else:
            self._on_thumbnail_error(self.tr("Corrupted image format"))

    def _on_thumbnail_error(self, message: str):
        self.thumb_stack.setCurrentIndex(0)
