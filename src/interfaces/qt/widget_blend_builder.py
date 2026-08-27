# =========================================================================================
# OPENSTUDIOHUB
# Módulo: ui/widget_blend_builder.py
# Rol Arquitectónico: UI Component / Batch Entity Genesis Tool
# =========================================================================================

from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QTableWidget, QTableWidgetItem, 
                               QHeaderView, QWidget, QAbstractItemView,
                               QComboBox, QMessageBox, QStackedWidget,
                               QListWidget, QListWidgetItem, QLineEdit)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QColor

from src.application.production_manager import ProductionManager
from src.domain.production.naming import NamingPolicy
from src.interfaces.qt.components.pipeline_wizard import PipelineWizardWidget
from src.interfaces.qt.components.progress_dialog import SpawningProgressDialog
from src.interfaces.qt.workers.api_queries import FetchProjectsWorker, FetchEntitiesWorker, FetchSequencesWorker, FetchEditStatusWorker, FetchAssetsWorker, FetchShotsWorker
from src.interfaces.qt.workers.blender_spawners import BatchCreationWorker, MasterSpawningWorker, StoryboardBatchWorker

class WidgetBlendBuilder(QFrame):
    def __init__(self, parent, auth_manager, config_factory, status_callback, credential_vault=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.auth = auth_manager
        self.config_factory = config_factory
        self.status_callback = status_callback
        self.credential_vault = credential_vault
        
        self.pm_core = ProductionManager(self.auth, self.config_factory)
        self.current_project_id = None
        self.project_map = {}

        self.setObjectName("TransparentGridContainer")
        self._build_ui()
        
        self._load_projects_from_kitsu()
        self._load_templates_from_vault()

    def _inyectar_credenciales_ram(self):
        """Extrae la contraseña de la RAM y la expone efímeramente para el subproceso Headless."""
        if self.credential_vault:
            import os
            kitsu_user, kitsu_pwd = self.credential_vault.get_kitsu_credentials()
            os.environ["OPENSTUDIO_KITSU_USER"] = kitsu_user or ""
            os.environ["OPENSTUDIO_KITSU_PWD"] = kitsu_pwd or ""

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(20)

        # --- 1. SELECTOR DE PROYECTO ---
        project_layout = QHBoxLayout()
        lbl_proj = QLabel(self.tr("Active Project:"))
        lbl_proj.setObjectName("InputLabel")
        
        self.combo_projects = QComboBox()
        self.combo_projects.setObjectName("StandardComboBox")
        self.combo_projects.setFixedSize(250, 35)
        self.combo_projects.currentIndexChanged.connect(self._on_project_changed)
        
        project_layout.addWidget(lbl_proj)
        project_layout.addWidget(self.combo_projects)
        project_layout.addStretch()
        main_layout.addLayout(project_layout)

        # --- 2. PIPELINE WIZARD (Top Section) ---
        self.wizard = PipelineWizardWidget(self)
        self.wizard.action_requested.connect(self._ejecutar_fase_pipeline)
        self.wizard.step_changed.connect(self.change_step)
        main_layout.addWidget(self.wizard)

        # --- 3. STACKED WIDGET (Panel Dinámico Inferior) ---
        self.stack = QStackedWidget()
        
        # PÁGINA 0: BREAKDOWN MANUAL DE STORYBOARD
        self.page_storyboard = QWidget()
        sb_layout = QVBoxLayout(self.page_storyboard)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        
        lbl_sb_desc = QLabel(self.tr("Enter the sequences (e.g. SQ010) identified during the script breakdown. This will register them in Kitsu and spawn their physical .blend files."))
        lbl_sb_desc.setObjectName("PageDescription")
        lbl_sb_desc.setWordWrap(True)
        sb_layout.addWidget(lbl_sb_desc)

        input_layout = QHBoxLayout()
        self.input_seq = QLineEdit()
        self.input_seq.setObjectName("FormInput")
        self.input_seq.setPlaceholderText(self.tr("Enter Sequence Name (e.g. SQ010) and press Enter"))
        self.input_seq.setFixedSize(300, 35)
        self.input_seq.returnPressed.connect(self._add_sequence_to_list)
        
        self.btn_add_seq = QPushButton(self.tr("Add"))
        self.btn_add_seq.setObjectName("SecondaryButton")
        self.btn_add_seq.setFixedSize(80, 35)
        self.btn_add_seq.clicked.connect(self._add_sequence_to_list)
        
        input_layout.addWidget(self.input_seq)
        input_layout.addWidget(self.btn_add_seq)
        input_layout.addStretch()
        sb_layout.addLayout(input_layout)
        
        self.list_sequences = QListWidget()
        self.list_sequences.setObjectName("FormInput") 
        sb_layout.addWidget(self.list_sequences)
        
        self.btn_clear_seq = QPushButton(self.tr("Clear List"))
        self.btn_clear_seq.setObjectName("LinkButton")
        self.btn_clear_seq.setCursor(Qt.PointingHandCursor)
        self.btn_clear_seq.clicked.connect(self.list_sequences.clear)
        sb_layout.addWidget(self.btn_clear_seq, alignment=Qt.AlignRight)
        
        self.stack.addWidget(self.page_storyboard)

        # --- NUEVO: PÁGINA 1: RADIOGRAFÍA EDITORIAL ---
        self.page_editorial = QWidget()
        edit_layout = QVBoxLayout(self.page_editorial)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        
        lbl_edit_desc = QLabel(self.tr("Editorial Master configuration and assignment."))
        lbl_edit_desc.setObjectName("PageDescription")
        edit_layout.addWidget(lbl_edit_desc)

        # Tarjeta visual para los datos
        frame_edit = QFrame()
        frame_edit.setObjectName("CardFrame") # O el estilo que uses para tarjetas
        flayout = QVBoxLayout(frame_edit)
        flayout.setSpacing(10)
        
        self.lbl_edit_filename = QLabel(self.tr("File: Scanning..."))
        self.lbl_edit_version = QLabel(self.tr("Version: --"))
        self.lbl_edit_editor = QLabel(self.tr("Assigned to: --"))
        self.lbl_edit_status = QLabel(self.tr("Status: --"))
        
        # Aplicamos estilos de texto corporativo
        for lbl in [self.lbl_edit_filename, self.lbl_edit_version, self.lbl_edit_editor, self.lbl_edit_status]:
            lbl.setObjectName("FormInput") 
            flayout.addWidget(lbl)
            
        edit_layout.addWidget(frame_edit)
        edit_layout.addStretch()
        
        self.stack.addWidget(self.page_editorial)

        # PÁGINA 1: TABLA KANBAN (Edición, Assets, Shots)
        self.page_entities = QWidget()
        ent_layout = QVBoxLayout(self.page_entities)
        ent_layout.setContentsMargins(0, 0, 0, 0)
        
        controls_layout = QHBoxLayout()
        self.lbl_kpi_total = self._create_kpi_label(self.tr("Total Entries: 0"))
        self.lbl_kpi_shots = self._create_kpi_label(self.tr("Shots: 0"))
        self.lbl_kpi_assets = self._create_kpi_label(self.tr("Assets: 0"))

        controls_layout.addWidget(self.lbl_kpi_total)
        controls_layout.addWidget(self.lbl_kpi_shots)
        controls_layout.addWidget(self.lbl_kpi_assets)
        controls_layout.addStretch()
        
        # self.combo_templates = QComboBox()
        # self.combo_templates.setObjectName("StandardComboBox")
        # self.combo_templates.setFixedSize(200, 35)
        # controls_layout.addWidget(self.combo_templates)

        # --- NUEVO: BOTÓN GLOBAL DE ASIGNACIÓN EN KITSU ---
        self.btn_open_kitsu_assets = QPushButton(self.tr("Assign Artists in Kitsu"))
        self.btn_open_kitsu_assets.setObjectName("SecondaryButton")
        self.btn_open_kitsu_assets.setCursor(Qt.PointingHandCursor)
        self.btn_open_kitsu_assets.clicked.connect(self._open_kitsu_assets_view)
        self.btn_open_kitsu_assets.hide() # Oculto por defecto (solo se muestra en paso 3)
        controls_layout.addWidget(self.btn_open_kitsu_assets)

        ent_layout.addLayout(controls_layout)

        # --- NUEVO: PANEL DE CHECKBOXES DE TAREAS (Oculto por defecto) ---
        self.panel_tasks = QWidget()
        self.layout_tasks = QHBoxLayout(self.panel_tasks)
        self.layout_tasks.setContentsMargins(0, 10, 0, 10)
        
        lbl_tasks = QLabel(self.tr("Select Tasks to Spawn:"))
        lbl_tasks.setObjectName("InputLabel")
        self.layout_tasks.addWidget(lbl_tasks)
        
        self.layout_checkboxes = QHBoxLayout()
        self.layout_tasks.addLayout(self.layout_checkboxes)
        self.layout_tasks.addStretch()
        
        self.task_checkboxes = {} # Diccionario para rastrear qué se marcó
        
        ent_layout.addWidget(self.panel_tasks)
        # -----------------------------------------------------------------

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("DataGrid")
        self.table.setHorizontalHeaderLabels(["", self.tr("Entity Name"), self.tr("Type"), self.tr("Parent Sequence"), self.tr("Frame Range"), self.tr("Kitsu Status")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(True)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        ent_layout.addWidget(self.table, stretch=1)
        self.stack.addWidget(self.page_entities)
        
        main_layout.addWidget(self.stack, stretch=1)

    # --- UI HELPERS ---
    def _create_kpi_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("KPILabel")
        return lbl

    def _create_pill_label(self, text: str, color_hex: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 2, 5, 2)
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setObjectName("PillLabel")
        lbl.setStyleSheet(f"background-color: {color_hex};")
        layout.addWidget(lbl)
        return widget

    def _open_kitsu_assets_view(self):
        """Abre el navegador en la vista de Assets del proyecto actual."""
        if not self.current_project_id: return
        kitsu_url = self.config_factory.get_kitsu_api_url().replace("/api", "")
        # Construimos la URL paramétrica exacta
        url = f"{kitsu_url}/productions/{self.current_project_id}/assets?search="
        
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def change_step(self, step_number: int):
        if not self.current_project_id: return

        self.wizard.set_step(step_number)
        # self.stack.setCurrentIndex(0 if step_number == 1 else 1)

        if step_number == 1:
            self.stack.setCurrentIndex(0)
        elif step_number == 2:
            self.stack.setCurrentIndex(1)
            self.load_editorial_status()
        elif step_number == 3:
            self.stack.setCurrentIndex(2)
            self.load_assets_from_kitsu()
        elif step_number == 4:
            self.stack.setCurrentIndex(2)
            self.load_shots_from_kitsu() # Para los shots luego
        #else:
            #self.stack.setCurrentIndex(2) # Pasos 3 y 4 van a la tabla Kanban
        
        # if step_number == 2:
        #     self.load_editorial_status()


    def _add_sequence_to_list(self):
        raw_seq_name = self.input_seq.text().strip().upper()
        if not raw_seq_name: return

        seq_name = NamingPolicy.sanitize_name(raw_seq_name)

        for i in range(self.list_sequences.count()):
            item = self.list_sequences.item(i)
            if item.data(Qt.UserRole + 1) == seq_name:
                self.input_seq.clear()
                return

        # Añadir como nueva entidad pendiente
        item = QListWidgetItem(f"{seq_name} (New Entry)")
        item.setData(Qt.UserRole, False) # Aún no tiene archivo físico
        item.setData(Qt.UserRole + 1, seq_name)
        item.setForeground(QColor("#3B82F6")) # Azul
        
        self.list_sequences.addItem(item)
        self.input_seq.clear()
        self.input_seq.setFocus()

    # --- NETWORK / I/O LOGIC ---
    def _load_projects_from_kitsu(self):
        self.combo_projects.blockSignals(True)
        self.combo_projects.addItem(self.tr("Loading projects..."))
        
        self.worker_projects = FetchProjectsWorker(self.auth.production_service)
        self.worker_projects.data_ready.connect(self._on_projects_loaded)
        self.worker_projects.error_occurred.connect(lambda e: self.status_callback(f"Project fetch error: {e}", "red"))
        self.worker_projects.start()

    def _on_projects_loaded(self, projects: list):
        self.combo_projects.clear()
        self.project_map.clear()
        if not projects:
            self.combo_projects.addItem(self.tr("No open projects found"))
            self.combo_projects.blockSignals(False)
            return

        for p in projects:
            self.project_map[p.get("name", "Unknown")] = p.get("id")
            self.combo_projects.addItem(p.get("name", "Unknown"))
        self.combo_projects.blockSignals(False)
        self._on_project_changed()

    def _load_templates_from_vault(self):
        return
        #self.combo_templates.clear()
        # try:
        #     if self.pm_core.vault_templates_dir.exists():
        #         templates = [d.name for d in self.pm_core.vault_templates_dir.iterdir() if d.is_dir() or d.name.endswith(".blend")]
        #         if templates: self.combo_templates.addItems(templates)
        #         else: self.combo_templates.addItem(self.tr("-- No templates --"))
        # except Exception:
        #     self.combo_templates.addItem(self.tr("-- Error reading Vault --"))

    def load_editorial_status(self):
        """Dispara la auditoría del archivo maestro de edición."""
        if not self.current_project_id: return
        
        self.status_callback(self.tr("Auditing Editorial Master..."), "yellow")
        
        # Bloquear el botón temporalmente para evitar clics dobles
        self.wizard.btn_batch_create.setEnabled(False)
        self.wizard.btn_batch_create.setText(self.tr("Scanning..."))
        
        nas_root = self.config_factory.get_workspace_root()
        vfs_svn = self.config_factory.get_vfs_svn_name()
        project_name = self.combo_projects.currentText()
        folder_name = project_name.strip().lower().replace(" ", "-")
        project_root = nas_root / folder_name
        
        self.worker_edit = FetchEditStatusWorker(self.auth.production_service, self.current_project_id, project_name, project_root, vfs_svn)
        self.worker_edit.data_ready.connect(self._render_editorial_status)
        self.worker_edit.error_occurred.connect(lambda e: self.status_callback(f"Edit fetch error: {e}", "red"))
        self.worker_edit.start()

    def load_assets_from_kitsu(self):
        """Dispara la auditoría de todos los assets del proyecto."""
        if not self.current_project_id: return
        self.status_callback(self.tr("Auditing assets from Kitsu and SVN..."), "yellow")
        self.table.setRowCount(0)
        self.btn_open_kitsu_assets.show() # Mostramos el botón en este paso
        
        nas_root = self.config_factory.get_workspace_root()
        vfs_svn = self.config_factory.get_vfs_svn_name()
        project_name = self.combo_projects.currentText()
        folder_name = project_name.strip().lower().replace(" ", "-")
        project_root = nas_root / folder_name
        
        self.worker_assets = FetchAssetsWorker(self.auth.production_service, self.current_project_id, project_root, vfs_svn)
        self.worker_assets.data_ready.connect(self._render_assets)
        self.worker_assets.error_occurred.connect(lambda e: self.status_callback(f"Asset fetch error: {e}", "red"))
        self.worker_assets.start()

    def _render_assets(self, assets: list):
        """Pinta los assets en la tabla Kanban."""
        self.table.setRowCount(len(assets))
        
        for row, asset in enumerate(assets):
            chk_item = QTableWidgetItem()
            
            # Si el archivo ya existe, desmarcamos y bloqueamos el checkbox
            if asset["has_file"]:
                chk_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Unchecked)
            else:
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Checked) # Autoseleccionar los pendientes
                
            chk_item.setData(Qt.UserRole, asset["raw_data"])
            self.table.setItem(row, 0, chk_item)
            
            self.table.setItem(row, 1, QTableWidgetItem(asset["name"]))
            self.table.setCellWidget(row, 2, self._create_pill_label("Asset", "#8B5CF6"))
            self.table.setItem(row, 3, QTableWidgetItem("N/A"))
            self.table.setItem(row, 4, QTableWidgetItem("N/A"))
            
            # Estado físico visual
            status_text = "✓ File Exists" if asset["has_file"] else "Pending Spawn"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor("#10B981") if asset["has_file"] else QColor("#F59E0B"))
            self.table.setItem(row, 5, status_item)

        self.lbl_kpi_total.setText(self.tr(f"Total Entries: {len(assets)}"))
        self.lbl_kpi_shots.setText(self.tr("Shots: 0"))
        self.lbl_kpi_assets.setText(self.tr(f"Assets: {len(assets)}"))
        self.status_callback(self.tr("✓ Assets loaded."), "green")

    def _render_editorial_status(self, edit_data: dict):
        """Pinta los resultados en pantalla y muta el CTA del Wizard."""
        self.status_callback(self.tr("Editorial audit complete."), "green")
        

        # AQUÍ puedes actualizar el layout secundario del QStackedWidget para mostrar el dict edit_data
        self.lbl_edit_filename.setText(self.tr(f"File Name: {edit_data['file_name']}"))
        self.lbl_edit_version.setText(self.tr(f"Version: {edit_data['version']}"))
        self.lbl_edit_editor.setText(self.tr(f"Assigned Editor: {edit_data['assignees']}"))
        self.lbl_edit_status.setText(self.tr(f"Task Status: {edit_data['status']}"))

        self.wizard.btn_batch_create.setEnabled(True)
        
        if edit_data["has_file"]:
            self.wizard.btn_batch_create.setText(self.tr("Assign Editor in Kitsu"))
            self.wizard.btn_batch_create.setObjectName("SecondaryButton")
            self.edit_action_mode = "ASSIGN" 
        else:
            self.wizard.btn_batch_create.setText(self.tr("Spawn Edit Master"))
            self.wizard.btn_batch_create.setObjectName("OrangeCTA")
            self.edit_action_mode = "SPAWN"
        
        self.wizard.btn_batch_create.style().polish(self.wizard.btn_batch_create)

    def _on_project_changed(self):
        project_name = self.combo_projects.currentText()
        if project_name in self.project_map:
            self.current_project_id = self.project_map[project_name]
            self.change_step(1) # Forzar paso 1 al cambiar de proyecto
            self.load_shots_from_kitsu()
            self.load_sequences_from_kitsu()

    def load_shots_from_kitsu(self):
        if not self.current_project_id: return
        self.status_callback(self.tr("Fetching pending shots from Kitsu..."), "yellow")
        self.table.setRowCount(0)
        
        nas_root = self.config_factory.get_workspace_root()
        vfs_svn = self.config_factory.get_vfs_svn_name()
        project_name = self.combo_projects.currentText()
        folder_name = project_name.strip().lower().replace(" ", "-")
        project_root = nas_root / folder_name

        self.worker_entities = FetchShotsWorker(self.auth.production_service, self.current_project_id, project_root, vfs_svn)
        self.worker_entities.data_ready.connect(self._render_shots)
        self.worker_entities.error_occurred.connect(lambda e: self.status_callback(f"Shot fetch error: {e}", "red"))
        self.worker_entities.start()

    def _render_shots(self, shots: list, task_types: list):
        # 1. Preparar las columnas dinámicas
        base_headers = ["", self.tr("Shot Name"), self.tr("Sequence"), self.tr("Frames")]
        all_headers = base_headers + task_types
        
        self.table.setColumnCount(len(all_headers))
        self.table.setHorizontalHeaderLabels(all_headers)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        for i in range(1, len(base_headers)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        for i in range(len(base_headers), len(all_headers)):
            header.setSectionResizeMode(i, QHeaderView.Stretch) # Expandir columnas de tareas

        self.table.setRowCount(len(shots))
        shots_count = len(shots)
        
        # 2. Reconstruir los checkboxes globales
        self.panel_tasks.show()
        # Limpiar checkboxes anteriores
        while self.layout_checkboxes.count():
            child = self.layout_checkboxes.takeAt(0)
            if child.widget(): child.widget().deleteLater()
            
        self.task_checkboxes.clear()
        for tt_name in task_types:
            from PySide6.QtWidgets import QCheckBox
            chk = QCheckBox(tt_name)
            chk.setChecked(True) # Marcados por defecto
            self.task_checkboxes[tt_name] = chk
            self.layout_checkboxes.addWidget(chk)
        
        # 3. Llenar la Matriz
        for row, entity in enumerate(shots):
            chk_item = QTableWidgetItem()
            has_all_files = entity.get("has_file", False)
            
            if has_all_files:
                chk_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Unchecked)
            else:
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Checked)
                
            chk_item.setData(Qt.UserRole, entity) # Guardamos TODO el diccionario de la entidad
            self.table.setItem(row, 0, chk_item)
            
            self.table.setItem(row, 1, QTableWidgetItem(entity.get("name", "Unknown")))
            self.table.setItem(row, 2, QTableWidgetItem(entity.get("parent", "Unknown")))
            self.table.setItem(row, 3, QTableWidgetItem(str(entity.get("frame_in", 0))))
            
            # Pintar las celdas de tareas
            tasks_data = entity.get("tasks", {})
            for col_idx, tt_name in enumerate(task_types):
                table_col = len(base_headers) + col_idx
                
                if tt_name in tasks_data:
                    task_info = tasks_data[tt_name]
                    if task_info["has_file"]:
                        self.table.setCellWidget(row, table_col, self._create_pill_label("✓ Ready", "#10B981"))
                    else:
                        self.table.setCellWidget(row, table_col, self._create_pill_label("Pending", "#F59E0B"))
                else:
                    self.table.setCellWidget(row, table_col, self._create_pill_label("N/A", "#4B5563")) # Gris oscuro si no aplica

        self.lbl_kpi_total.setText(self.tr(f"Total Entries: {shots_count}"))
        self.lbl_kpi_shots.setText(self.tr(f"Shots: {shots_count}"))
        self.lbl_kpi_assets.setText(self.tr("Assets: 0"))
        
        self.status_callback(self.tr("✓ Shots matrix loaded."), "green")
    
    def load_sequences_from_kitsu(self):
        if not self.current_project_id: return
        self.list_sequences.clear()
        self.list_sequences.addItem(self.tr("Auditing sequences from Kitsu and SVN..."))
        
        # Calcular rutas físicas usando tu ConfigFactory
        nas_root = self.config_factory.get_workspace_root()
        vfs_svn = self.config_factory.get_vfs_svn_name()
        project_name = self.combo_projects.currentText()
        folder_name = project_name.strip().lower().replace(" ", "-")
        project_root = nas_root / folder_name
        
        self.worker_seqs = FetchSequencesWorker(self.auth.production_service, self.current_project_id, project_root, vfs_svn)
        self.worker_seqs.data_ready.connect(self._render_sequences)
        self.worker_seqs.error_occurred.connect(lambda e: self.status_callback(f"Seq fetch error: {e}", "red"))
        self.worker_seqs.start()

    def _render_sequences(self, sequences: list):
        self.list_sequences.clear()
        
        for seq in sequences:
            name = seq["name"]
            has_file = seq["has_file"]
            
            # Feedback visual de estado
            label = f"{name} (✓ File Exists)" if has_file else f"{name} (Pending Spawn)"
            item = QListWidgetItem(label)
            
            # INYECCIÓN CLAVE: Guardamos el estado y el nombre limpio de forma invisible
            item.setData(Qt.UserRole, has_file)
            item.setData(Qt.UserRole + 1, name)
            
            # Colorear según el estado físico (Verdad SVN)
            if has_file:
                item.setForeground(QColor("#10B981")) # Verde (Listo)
            else:
                item.setForeground(QColor("#F59E0B")) # Naranja (Pendiente)
                
            self.list_sequences.addItem(item)
    
    # --- ENRUTADOR PRINCIPAL ---

    def _ejecutar_fase_pipeline(self, step_id: int):
        if not self.current_project_id:
            self.status_callback(self.tr("Please select a project first."), "yellow")
            return

        if step_id == 1:
            if self.input_seq.text().strip():
                self._add_sequence_to_list()
                
            # 1. Filtrar SOLO las secuencias pendientes
            pending_sequences = []
            for i in range(self.list_sequences.count()):
                item = self.list_sequences.item(i)
                has_file = item.data(Qt.UserRole)
                if not has_file: # Si no tiene archivo físico
                    clean_name = item.data(Qt.UserRole + 1)
                    pending_sequences.append(clean_name)
                    
            if not pending_sequences:
                QMessageBox.information(self, self.tr("System Checked"), self.tr("All listed sequences already have physical files. Nothing to spawn."))
                return
                
            # 2. Preparar UI y Modal
            self.status_callback(self.tr("Spawning Storyboard sequences..."), "yellow")
            project_name = self.combo_projects.currentText()
            self.progress_modal = SpawningProgressDialog(self, self.tr("Batch Spawning Storyboards"))
            self.progress_modal.show()
            
            self._inyectar_credenciales_ram()
            # 3. Lanzar Worker SOLO con las pendientes
            self.spawn_worker = StoryboardBatchWorker(self.pm_core, self.config_factory, self.current_project_id, project_name, pending_sequences)
            self.spawn_worker.progress_updated.connect(self.progress_modal.update_progress)
            self.spawn_worker.log_stream.connect(self.progress_modal.append_log)
            
            def open_kitsu():
                kitsu_url = self.config_factory.get_kitsu_api_url().replace("/api", "")
                url = f"{kitsu_url}/productions/{self.current_project_id}/shots"
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl(url))
                self.progress_modal.accept()

            def on_sb_finished(success, msg):
                if success:
                    self.status_callback(self.tr(f"✓ {msg}"), "green")
                    self.change_step(2)
                    self.progress_modal.finalize(True, self.tr("Success: Storyboards spawned."), "Assign Artists in Kitsu", open_kitsu)
                    # RECARGA AUTOMÁTICA para pintar de verde
                    self.load_sequences_from_kitsu() 
                else:
                    self.status_callback(self.tr(f"✗ Error: {msg}"), "red")
                    self.progress_modal.finalize(False, self.tr("Process completed with errors. Check logs."))

            self.spawn_worker.finished_batch.connect(on_sb_finished)
            self.spawn_worker.start()
            
        elif step_id == 2:
            if getattr(self, "edit_action_mode", "SPAWN") == "ASSIGN":
                # Abrimos Kitsu en el navegador para la asignación manual
                kitsu_url = self.config_factory.get_kitsu_api_url().replace("/api", "")
                url = f"{kitsu_url}/productions/{self.current_project_id}/edits"
                
                QDesktopServices.openUrl(QUrl(url))
                self.status_callback(self.tr("Opened Kitsu for assignment."), "white")
                return

            project_name = self.combo_projects.currentText()
            self.progress_modal = SpawningProgressDialog(self, self.tr("Spawning EDIT Master"))
            self.progress_modal.show()

            self.spawn_worker = MasterSpawningWorker(
                self.config_factory, project_name, "EDIT", self.current_project_id
            )
            
            self.spawn_worker.progress_updated.connect(self.progress_modal.update_progress)
            self.spawn_worker.log_stream.connect(self.progress_modal.append_log)
            
            def on_finished(success, msg):
                if success:
                    self.status_callback(self.tr(f"✓ {msg}"), "green")
                    self.change_step(3)
                    self.progress_modal.finalize(True, self.tr("Success: EDIT Master forged."))
                else:
                    self.status_callback(self.tr(f"✗ Error: {msg}"), "red")
                    self.progress_modal.finalize(False, self.tr("Process completed with errors. Check logs."))
                    
            self.spawn_worker.finished_spawn.connect(on_finished)
            self.spawn_worker.start()

        elif step_id in [3, 4]:

            #self.status_callback(self.tr("Batch Creating shots..."), "yellow")
            self._trigger_batch_creation(step_id)

    def _trigger_batch_creation(self, step_id: int):
        selected_entities = [self.table.item(r, 0).data(Qt.UserRole) for r in range(self.table.rowCount()) if self.table.item(r, 0).checkState() == Qt.Checked]
        if not selected_entities:
            QMessageBox.information(self, self.tr("System Checked"), self.tr("No pending entities selected to spawn."))
            return
            
        # --- NUEVO: RECOLECTAR TAREAS SELECCIONADAS ---
        selected_tasks = []
        if step_id == 4: # Solo aplicamos la matriz a los Shots
            selected_tasks = [name for name, chk in self.task_checkboxes.items() if chk.isChecked()]
            if not selected_tasks:
                QMessageBox.warning(self, self.tr("Missing Tasks"), self.tr("Please select at least one task type to spawn."))
                return
        else:
            # Tareas por defecto para Assets
            selected_tasks = ["Modeling", "Rigging", "Shading", "Concept"]
        # ----------------------------------------------

        # Levantar ventana de log modal
        self.progress_modal = SpawningProgressDialog(self, self.tr("Batch Spawning Production Files"))
        self.progress_modal.show()
        
        # Interceptor: Redirigimos el callback del worker hacia el log visual
        def intercept_log(msg: str, color: str = "white"):
            self.progress_modal.append_log(msg)
            self.progress_modal.update_progress(50, self.tr("Forging..."))
            
        self._inyectar_credenciales_ram()
        self.worker_batch = BatchCreationWorker(
            pm_core=self.pm_core,
            config_factory=self.config_factory,
            project_id=self.current_project_id,
            project_name=self.combo_projects.currentText(),
            entities=selected_entities,
            task_types=selected_tasks, # Tareas comunes de Assets
            #status_cb=intercept_log # <-- Inyección del interceptor
        )

        # Conectar las señales directamente al modal flotante
        self.worker_batch.progress_updated.connect(self.progress_modal.update_progress)
        self.worker_batch.log_stream.connect(self.progress_modal.append_log)

        def on_batch_finished(success: bool, message: str):
            if success:
                self.progress_modal.update_progress(100, self.tr("Done!"))
                self.progress_modal.finalize(True, self.tr("Success: Files Spawned."), "Assign in Kitsu", self._open_kitsu_assets_view)
                if step_id == 3:
                    self.load_assets_from_kitsu() # Recargar la lista de Assets
                elif step_id == 4:
                    self.load_shots_from_kitsu()
            else:
                self.progress_modal.finalize(False, self.tr("Process completed with errors. Check logs."))
                QMessageBox.critical(self, self.tr("Batch Creation Failed"), message)
                
        self.worker_batch.finished_batch.connect(on_batch_finished)
        self.worker_batch.start()
