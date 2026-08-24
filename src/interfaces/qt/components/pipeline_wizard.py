# OPENSTUDIOHUB
# Módulo: ui/components/pipeline_wizard.py
# Rol: Componente visual secuencial para el Production Manager

from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, 
                               QLabel, QPushButton, QWidget, QSizePolicy)
from PySide6.QtCore import Qt, Signal

class PipelineStepNode(QWidget):
    """Nodo individual de la barra de progreso (Círculo + Título)."""
    
    clicked = Signal(int)

    def __init__(self, step_number: int, title: str):
        super().__init__()
        self.step_number = step_number

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)
        
        self.node_circle = QLabel(str(step_number))
        self.node_circle.setAlignment(Qt.AlignCenter)
        self.node_circle.setFixedSize(44, 44)
        
        self.lbl_title = QLabel(f"{step_number}. {title}")
        self.lbl_title.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(self.node_circle, alignment=Qt.AlignCenter)
        layout.addWidget(self.lbl_title, alignment=Qt.AlignCenter)
        
        self.setCursor(Qt.PointingHandCursor)
        self.set_state(is_active=False, is_completed=False)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.step_number)
        return super().mousePressEvent(event)

    def set_state(self, is_active: bool, is_completed: bool):
        # Asignación semántica para el QSS global
        if is_completed:
            self.node_circle.setObjectName("StepNodeCompleted")
            self.lbl_title.setObjectName("StepTitleCompleted")
            self.node_circle.setText("✓")
        elif is_active:
            self.node_circle.setObjectName("StepNodeActive")
            self.lbl_title.setObjectName("StepTitleActive")
            self.node_circle.setText( str(self.step_number) )
        else:
            self.node_circle.setObjectName("StepNodePending")
            self.lbl_title.setObjectName("StepTitlePending")
            self.node_circle.setText( str(self.step_number) )
        
        # Forzar refresco de estilos en Qt
        self.node_circle.style().polish(self.node_circle)
        self.lbl_title.style().polish(self.lbl_title)


class PipelineWizardWidget(QFrame):
    """Barra de progreso secuencial y orquestador de Batch Creation."""
    action_requested = Signal(int) # Emite el paso actual (1=Storyboard, 2=Edit...)

    step_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PipelineWizardCard")
        
        self.current_step = 1
        self.steps_data = ["Storyboard", "Editorial", "Assets", "Shots"]
        self._nodes = []
        self._lines = []
        
        self._build_ui()
        self.set_step(1) # Inicializar en el paso 1

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)

        # Título
        lbl_header = QLabel(self.tr("Overall Project Health"))
        lbl_header.setObjectName("WizardHeader")
        main_layout.addWidget(lbl_header)

        # Contenedor de la barra de progreso
        progress_layout = QHBoxLayout()
        progress_layout.setAlignment(Qt.AlignCenter)
        progress_layout.setSpacing(0)

        for i, title in enumerate(self.steps_data):
            # Crear Nodo
            node = PipelineStepNode(i + 1, title)
            
            node.clicked.connect(self.step_changed.emit)

            self._nodes.append(node)
            progress_layout.addWidget(node)

            # Crear Línea conectora (excepto para el último nodo)
            if i < len(self.steps_data) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self._lines.append(line)
                progress_layout.addWidget(line)

        main_layout.addLayout(progress_layout)

        # Botón Call to Action Central
        btn_layout = QHBoxLayout()
        self.btn_batch_create = QPushButton(self.tr("Batch Create Pending Files"))
        self.btn_batch_create.setObjectName("OrangeCTA")
        self.btn_batch_create.setCursor(Qt.PointingHandCursor)
        self.btn_batch_create.clicked.connect(lambda: self.action_requested.emit(self.current_step))
        
        # Spacer para centrar el botón
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_batch_create, stretch=1)
        btn_layout.addStretch()
        
        main_layout.addLayout(btn_layout)

    def set_step(self, step_number: int):
        """Actualiza el estado visual de los nodos y las líneas."""
        self.current_step = step_number
        
        for i, node in enumerate(self._nodes):
            is_completed = (i + 1) < step_number
            is_active = (i + 1) == step_number
            node.set_state(is_active, is_completed)
            
        for i, line in enumerate(self._lines):
            # Si el nodo a la izquierda de la línea está completado, colorear la línea
            if (i + 1) < step_number:
                line.setObjectName("StepLineCompleted")
            else:
                line.setObjectName("StepLinePending")
            line.style().polish(line)
            
        # Actualizar texto del botón según la etapa
        text_map = {
            1: "Spawn Storyboard Master",
            2: "Spawn Edit Master",
            3: "Batch Create Assets",
            4: "Batch Create Shots"
        }
        self.btn_batch_create.setText(self.tr(text_map.get(step_number, "Batch Create")))
