# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/components/activity_card.py
# Rol Arquitectónico: UI Component / Activity Feed Card (PySide6)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.6.1
# =========================================================================================

"""
Componente visual para la lista del Activity Feed (Bandeja de Entrada).
Migrado a PySide6. Estilos delegados al QSS global para integración inmersiva.
"""

import webbrowser
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QThread, Signal


class AcknowledgeWorker(QThread):
    """Hilo secundario para enviar el Acuse de Recibo a Kitsu sin bloquear la interfaz."""
    ack_finished = Signal(bool)

    def __init__(self, auth_manager, task_id: str, comment_id: str):
        super().__init__()
        self.auth = auth_manager
        self.task_id = task_id
        self.comment_id = comment_id

    def run(self):
        exito = self.auth.acknowledge_activity(self.task_id, self.comment_id)
        self.ack_finished.emit(exito)


class ActivityCard(QFrame):
    def __init__(self, parent, activity_data: dict, auth_manager, on_acknowledge_callback, **kwargs):
        super().__init__(parent, **kwargs)
        self.data = activity_data
        self.auth_manager = auth_manager
        self.on_acknowledge_callback = on_acknowledge_callback

        # Unificación B2B: Hereda del contenedor estándar aunque con una variante sutil
        self.setObjectName("FloatingCard")
        
        # Ajuste de color para acentuarla ligeramente sobre el panel derecho
        self.setStyleSheet("""
            QFrame#FloatingCard {
                background-color: #2E3643;
                border: 1px solid #141820;
                border-radius: 8px;
            }
        """)

        self._build_ui()

    def _obtener_color_texto_contraste(self, hex_color: str) -> str:
        """Calcula la luminancia relativa (sRGB) para contrastar el texto del Badge."""
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
        main_layout.setSpacing(8)

        # ---------------------------------------------------------
        # Fila 1: Avatar y Título (Autor + Tarea)
        # ---------------------------------------------------------
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # Inicial del autor (Placeholder de Avatar)
        author_name = self.data.get("author", {}).get("first_name", "U")
        lbl_avatar = QLabel(author_name[0].upper())
        lbl_avatar.setFixedSize(28, 28)
        lbl_avatar.setAlignment(Qt.AlignCenter)
        lbl_avatar.setStyleSheet("background-color: #3B82F6; color: white; border-radius: 14px; font-weight: bold;")
        header_layout.addWidget(lbl_avatar)
        
        # Texto del autor y entidad
        entity_name = self.data.get("entity", {}).get("name", "Unknown")
        task_name = self.data.get("task_type", {}).get("name", "Task")
        lbl_title = QLabel(f"<b>{author_name}</b> on {entity_name} - {task_name}")
        lbl_title.setStyleSheet("color: #E2E8F0; font-size: 12px;")
        lbl_title.setWordWrap(True)
        header_layout.addWidget(lbl_title, stretch=1)
        
        main_layout.addLayout(header_layout)

        # ---------------------------------------------------------
        # Fila 2: Texto del Comentario (Snippet)
        # ---------------------------------------------------------
        texto = self.data.get("text", "...")
        if len(texto) > 100:
            texto = texto[:97] + "..."
            
        lbl_texto = QLabel(texto)
        lbl_texto.setStyleSheet("color: #94A3B8; font-size: 11px;")
        lbl_texto.setWordWrap(True)
        main_layout.addWidget(lbl_texto)

        # ---------------------------------------------------------
        # Fila 3: Badge de Estado y Botón de Acción
        # ---------------------------------------------------------
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 5, 0, 0)
        
        lbl_estado_tag = QLabel("Estado:")
        lbl_estado_tag.setStyleSheet("color: #64748B; font-size: 11px;")
        footer_layout.addWidget(lbl_estado_tag)

        status_data = self.data.get("task_status", {})
        s_name = status_data.get("short_name", "???")
        s_color = status_data.get("color", "#444444")
        t_color = self._obtener_color_texto_contraste(s_color)

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

        self.btn_accion = QPushButton("Abrir _Marcar Leído")
        self.btn_accion.setCursor(Qt.PointingHandCursor)
        self.btn_accion.setStyleSheet("""
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
        self.btn_accion.clicked.connect(self._ejecutar_accion)
        footer_layout.addWidget(self.btn_accion)

        main_layout.addLayout(footer_layout)

    def _ejecutar_accion(self):
        """Abre el navegador, notifica al backend vía QThread y notifica al padre."""
        self.btn_accion.setEnabled(False)
        self.btn_accion.setText("Procesando...")

        # Lanzar al navegador
        url = self.data.get("task_url")
        if url:
            webbrowser.open(url)

        # Enviar el Ack asíncrono
        task_id = self.data.get("task_id", "")
        comment_id = self.data.get("id", "")

        self.worker = AcknowledgeWorker(self.auth_manager, task_id, comment_id)
        self.worker.ack_finished.connect(lambda exito: self.on_acknowledge_callback(self))
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()
