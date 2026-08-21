import subprocess
import os
import glob
import platform
from pathlib import Path
from PySide6.QtCore import QThread, Signal

from core.kitsu_manager import KitsuManager


class BatchCreationWorker(QThread):
    progress_updated = Signal(int, str)
    log_stream = Signal(str)
    finished_batch = Signal(bool, str)

    def __init__(self, pm_core, config_factory, project_id: str, project_name: str, entities: list, task_types: list):
        super().__init__()
        self.pm_core = pm_core
        self.config = config_factory
        self.project_id = project_id
        self.project_name = project_name
        self.entities = entities # Lista de dicts crudos
        self.task_types = task_types

    def run(self):
        try:
            total_ents = len(self.entities)
            if total_ents == 0:
                self.finished_batch.emit(False, "No entities provided.")
                return

            nas_root = self.config.get_workspace_root()
            vfs_local = self.config.get_vfs_local_name()
            folder_name = self.project_name.strip().lower().replace(" ", "-")
            project_root = nas_root / folder_name
            base_blender_dir = project_root / vfs_local / "blender-build"
            
            import platform, glob, os, subprocess
            os_name = platform.system().lower()
            if os_name == "windows":
                exe_list = glob.glob(str(base_blender_dir / "**" / "blender.exe"), recursive=True)
            elif os_name == "darwin":
                exe_list = glob.glob(str(base_blender_dir / "**" / "MacOS" / "Blender"), recursive=True)
            else:
                exe_list = glob.glob(str(base_blender_dir / "**" / "blender"), recursive=True)
                
            if not exe_list:
                raise FileNotFoundError("Blender binary not found in sandbox.")

            vfs_svn = self.config.get_vfs_svn_name()

            for idx, entity in enumerate(self.entities):
                e_name = entity.get("name", "Unknown")
                e_id = entity.get("id", "")
                e_type = entity.get("type", "Asset").upper()
                
                # --- NUEVA LÓGICA DE FILTRADO POR TAREAS ---
                tasks_to_spawn = []
                if e_type == "SHOT":
                    tasks_dict = entity.get("tasks", {})
                    for t_name in self.task_types:
                        # Solo forjamos si la toma tiene esta tarea en Kitsu y NO tiene archivo
                        task_info = tasks_dict.get(t_name)
                        if task_info and not task_info.get("has_file"):
                            tasks_to_spawn.append(t_name)
                else:
                    # Los Assets conservan su comportamiento de iterar una vez por ahora
                    tasks_to_spawn = [""] 
                # -------------------------------------------
                
                # Bucle anidado para iterar cada tarea faltante de la entidad
                for t_idx, t_name in enumerate(tasks_to_spawn):
                    
                    display_name = f"{e_name} [{t_name}]" if t_name else e_name
                    base_progress = 10 + int((idx / total_ents) * 90)
                    self.progress_updated.emit(base_progress, self.tr(f"Processing {e_type}: {display_name} ({idx+1}/{total_ents})"))
                    
                    self.log_stream.emit(f"\n[{display_name}] Spawning physical file via Headless Engine...")
                    
                    env = os.environ.copy()
                    env["OPENSTUDIO_BUILD_TARGET"] = e_type 
                    env["OPENSTUDIO_PROJECT_ROOT"] = str(project_root)
                    env["OPENSTUDIO_PRODUCTION_FOLDER"] = vfs_svn
                    env["BLENDER_USER_RESOURCES"] = str(project_root / vfs_local / "blender_data")
                    env["OPENSTUDIO_KITSU_PROJECT_ID"] = str(self.project_id)
                    env["OPENSTUDIO_TARGET_ENTITY_ID"] = str(e_id) 
                    env["OPENSTUDIO_KITSU_ENTITY_NAME"] = str(e_name)
                    
                    env["OPENSTUDIO_KITSU_ASSET_TYPE_ID"] = str(entity.get("asset_type_id", ""))
                    env["OPENSTUDIO_KITSU_ASSET_TYPE_NAME"] = str(entity.get("asset_type_name", ""))

                    # Inyección dinámica de la secuencia y el tipo de tarea
                    if e_type == "SHOT":
                        env["OPENSTUDIO_KITSU_SEQUENCE_NAME"] = str(entity.get("parent", ""))
                        env["OPENSTUDIO_KITSU_TASK_TYPE_NAME"] = str(t_name) 
                    
                    env["OPENSTUDIO_KITSU_HOST"] = self.config.get_kitsu_api_url()
                    env["OPENSTUDIO_KITSU_USER"] = os.environ.get("OPENSTUDIO_KITSU_USER", "")
                    env["OPENSTUDIO_KITSU_PWD"] = os.environ.get("OPENSTUDIO_KITSU_PWD", "")
                    
                    script_path = Path(__file__).parent.parent.parent / "core" / "templates" / "headless_builder.py"
                    cmd = [exe_list[0], "-b", "--python", str(script_path)]
                    
                    proceso = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    for line in proceso.stdout:
                        if line.strip(): self.log_stream.emit(f"    ↳ {line.strip()}")
                    proceso.wait()
                    
                    if proceso.returncode != 0:
                        self.log_stream.emit(f"[{display_name}] ❌ ERROR: Blender Headless failed.")
                    else:
                        self.log_stream.emit(f"[{display_name}] ✓ Physical file spawned.")

                # base_progress = 10 + int((idx / total_ents) * 90)
                # self.progress_updated.emit(base_progress, self.tr(f"Processing {e_type}: {e_name} ({idx+1}/{total_ents})"))
                #
                # self.log_stream.emit(f"\n[{e_name}] Spawning physical file via Headless Engine...")
                #
                # env = os.environ.copy()
                # env["OPENSTUDIO_BUILD_TARGET"] = e_type # "ASSET" o "SHOT"
                # env["OPENSTUDIO_PROJECT_ROOT"] = str(project_root)
                # env["OPENSTUDIO_PRODUCTION_FOLDER"] = vfs_svn
                # env["BLENDER_USER_RESOURCES"] = str(project_root / vfs_local / "blender_data")
                # env["OPENSTUDIO_KITSU_PROJECT_ID"] = str(self.project_id)
                # env["OPENSTUDIO_TARGET_ENTITY_ID"] = str(e_id) # <- ID Inyectado
                # env["OPENSTUDIO_KITSU_ENTITY_NAME"] = str(e_name)
                #
                # # Inyectamos los datos del Asset Type que arreglamos en el ProductionManager
                # env["OPENSTUDIO_KITSU_ASSET_TYPE_ID"] = str(entity.get("asset_type_id", ""))
                # env["OPENSTUDIO_KITSU_ASSET_TYPE_NAME"] = str(entity.get("asset_type_name", ""))
                #
                # # Si llega a ser un Shot, enviamos el nombre de la secuencia (que está guardado en "parent")
                # if e_type == "SHOT":
                #     env["OPENSTUDIO_KITSU_SEQUENCE_NAME"] = str(entity.get("sequence_name", ""))
                #     env["OPENSTUDIO_KITSU_TASK_TYPE_NAME"] = "Layout"
                # # ----------------------------------------
                #
                # env["OPENSTUDIO_KITSU_HOST"] = self.config.get_kitsu_api_url()
                # env["OPENSTUDIO_KITSU_USER"] = os.environ.get("OPENSTUDIO_KITSU_USER", "")
                # env["OPENSTUDIO_KITSU_PWD"] = os.environ.get("OPENSTUDIO_KITSU_PWD", "")
                #  # --- DEBUG: VOLCADO COMPLETO DEL ENTORNO ---
                # print("\n" + "="*60)
                # print("🔍 AUDITORÍA COMPLETA DE VARIABLES DE ENTORNO")
                # print("="*60)
                #
                # # Cambia 'clean_env' por 'env' si quieres ver el diccionario original
                # for key, value in sorted(env.items()):
                #     # Filtramos un poco para no imprimir las cientos de variables base del sistema, 
                #     # y centrarnos solo en las inyectadas por OpenStudio o Blender.
                #     if key.startswith("OPENSTUDIO_") or key.startswith("BLENDER_"):
                #         print(f"[{key}]: '{value}'")
                #
                # print("="*60 + "\n")
                # # -------------------------------------------
                # script_path = Path(__file__).parent.parent.parent / "core" / "templates" / "headless_builder.py"
                # cmd = [exe_list[0], "-b", "--python", str(script_path)]
                #
                # proceso = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                # for line in proceso.stdout:
                #     if line.strip(): self.log_stream.emit(f"    ↳ {line.strip()}")
                # proceso.wait()
                #
                # if proceso.returncode != 0:
                #     self.log_stream.emit(f"[{e_name}] ❌ ERROR: Blender Headless failed.")
                # else:
                #     self.log_stream.emit(f"[{e_name}] ✓ Physical file spawned.")

            self.progress_updated.emit(100, self.tr("Batch Creation Complete!"))
            self.finished_batch.emit(True, f"{total_ents} entities processed successfully.")
            
        except Exception as e:
            self.finished_batch.emit(False, str(e))

class MasterSpawningWorker(QThread):
    progress_updated = Signal(int, str)
    log_stream = Signal(str)
    finished_spawn = Signal(bool, str)

    def __init__(self, config_factory, project_name, build_target, project_id=""):
        super().__init__()
        self.config = config_factory
        self.project_name = project_name
        self.build_target = build_target
        self.project_id = project_id

    def run(self):
        try:
            self.progress_updated.emit(10, self.tr("Locating project and sandbox..."))
            nas_root = self.config.get_workspace_root()
            vfs_local = self.config.get_vfs_local_name()
            folder_name = self.project_name.strip().lower().replace(" ", "-")
            project_root = nas_root / folder_name
            
            base_blender_dir = project_root / vfs_local / "blender-build"
            os_name = platform.system().lower()
            if os_name == "windows":
                exe_list = glob.glob(str(base_blender_dir / "**" / "blender.exe"), recursive=True)
            elif os_name == "darwin":
                exe_list = glob.glob(str(base_blender_dir / "**" / "MacOS" / "Blender"), recursive=True)
            else:
                exe_list = glob.glob(str(base_blender_dir / "**" / "blender"), recursive=True)
                
            if not exe_list:
                raise FileNotFoundError("Blender binary not found in sandbox.")
            blender_bin = exe_list[0]

            self.progress_updated.emit(20, self.tr("Preparing environment variables..."))
            env = os.environ.copy()
            
            # --- INYECCIÓN DE DEPENDENCIAS ---
            env["OPENSTUDIO_BUILD_TARGET"] = self.build_target
            env["OPENSTUDIO_PROJECT_ROOT"] = str(project_root)
            env["OPENSTUDIO_PRODUCTION_FOLDER"] = self.config.get_vfs_svn_name()
            env["BLENDER_USER_RESOURCES"] = str(project_root / vfs_local / "blender_data")
            env["OPENSTUDIO_KITSU_PROJECT_ID"] = str(self.project_id)
            
            # --- CÓDIGO CORREGIDO ---
            env["OPENSTUDIO_KITSU_HOST"] = self.config.get_kitsu_api_url()
            env["OPENSTUDIO_KITSU_USER"] = os.environ.get("OPENSTUDIO_KITSU_USER", "")
            env["OPENSTUDIO_KITSU_PWD"] = os.environ.get("OPENSTUDIO_KITSU_PWD", "")
            # ----------------------------------------
            
            script_path = Path(__file__).parent.parent.parent / "core" / "templates" / "headless_builder.py"
            
            self.progress_updated.emit(30, self.tr("Booting Blender Engine..."))
            cmd = [str(blender_bin), "-b", "--python", str(script_path)]
            proceso = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            
            for line in proceso.stdout:
                line_clean = line.strip()
                if not line_clean: continue
                self.log_stream.emit(line_clean)
                
                if "Cargando App-Template" in line_clean:
                    self.progress_updated.emit(50, self.tr("Loading UI Template..."))
                elif "Restaurando contexto Kitsu" in line_clean:
                    self.progress_updated.emit(70, self.tr("Authenticating with server..."))
                elif "GUARDADO FORZADO EXITOSO" in line_clean:
                    self.progress_updated.emit(90, self.tr("Writing physical file..."))
            
            proceso.wait()
            if proceso.returncode == 0:
                self.progress_updated.emit(100, self.tr("Master File Forged Successfully!"))
                self.finished_spawn.emit(True, f"{self.build_target} created.")
            else:
                raise RuntimeError(f"Blender crashed with return code {proceso.returncode}")
                
        except Exception as e:
            self.finished_spawn.emit(False, str(e))

class StoryboardBatchWorker(QThread):
    progress_updated = Signal(int, str)
    log_stream = Signal(str)
    finished_batch = Signal(bool, str)

    def __init__(self, pm_core, config_factory, project_id: str, project_name: str, sequence_names: list):
        super().__init__()
        self.pm_core = pm_core
        self.config = config_factory
        self.project_id = project_id
        self.project_name = project_name
        self.sequence_names = sequence_names
        self.kitsu = KitsuManager()

    def run(self):
        try:
            total_seqs = len(self.sequence_names)
            if total_seqs == 0:
                self.finished_batch.emit(False, self.tr("The sequence list is empty."))
                return

            self.progress_updated.emit(5, self.tr("Verifying Kitsu Pipeline schema..."))
            storyboard_tt = self.pm_core.get_or_create_storyboard_task_type(self.project_id)
            tt_id = storyboard_tt["id"]
            
            nas_root = self.config.get_workspace_root()
            vfs_local = self.config.get_vfs_local_name()
            folder_name = self.project_name.strip().lower().replace(" ", "-")
            project_root = nas_root / folder_name
            base_blender_dir = project_root / vfs_local / "blender-build"
            
            os_name = platform.system().lower()
            if os_name == "windows":
                exe_list = glob.glob(str(base_blender_dir / "**" / "blender.exe"), recursive=True)
            elif os_name == "darwin":
                exe_list = glob.glob(str(base_blender_dir / "**" / "MacOS" / "Blender"), recursive=True)
            else:
                exe_list = glob.glob(str(base_blender_dir / "**" / "blender"), recursive=True)
                
            if not exe_list:
                raise FileNotFoundError("Blender binary not found in sandbox.")

            for idx, seq_name in enumerate(self.sequence_names):
                base_progress = 10 + int((idx / total_seqs) * 90)
                self.progress_updated.emit(base_progress, self.tr(f"Processing Sequence: {seq_name} ({idx+1}/{total_seqs})"))
                
                self.log_stream.emit(f"\n[{seq_name}] Registering Entity and Task in Kitsu API...")
                existing_seq = self.kitsu.get_sequence_by_name(self.project_id, seq_name)
                
                if not existing_seq:
                    existing_seq = self.pm_core.create_sequence_with_task(self.project_id, seq_name, tt_id)
                    self.log_stream.emit(f"[{seq_name}] ✓ Kitsu database updated.")
                else:
                    self.log_stream.emit(f"[{seq_name}] ⚠️ Sequence already exists. Skipping Kitsu creation.")
               
                vfs_svn = self.config.get_vfs_svn_name()
                
                try:
                    storyboard_tt = self.pm_core.get_or_create_storyboard_task_type(self.project_id)
                    task = self.kitsu.get_task_by_entity(existing_seq, storyboard_tt)
                    
                    if task is None:
                        self.log_stream.emit(f"[{seq_name}] Tarea no encontrada. Creando nueva tarea 'main'...")
                        default_status = self.kitsu.get_default_task_status()
                        task = self.kitsu.new_task(existing_seq, storyboard_tt, name="main", task_status=default_status)
                    
                    rel_path = f"{vfs_svn}/edit/storyboards/{seq_name.lower()}-storyboard.blend"
                    
                    seq_data = existing_seq.get("data")
                    if not seq_data:
                        seq_data = {}

                    seq_data["blend_file_path"] = rel_path
                    self.kitsu.update_sequence_data(existing_seq["id"], seq_data)
                    self.log_stream.emit(f"[{seq_name}] ✓ File path saved in Sequence metadata: {rel_path}")
                    
                    software = self.kitsu.get_software_by_name("Blender")
                    if software and task:
                        self.kitsu.new_working_file(task, software, name=rel_path)
                        
                    self.log_stream.emit(f"[{seq_name}] ✓ File path mapped to Kitsu Task.")
                except Exception as e:
                    self.log_stream.emit(f"[{seq_name}] ⚠️ Fallo al mapear archivo en Kitsu: {e}")

                self.log_stream.emit(f"[{seq_name}] Spawning physical .blend file via Headless Engine...")
                
                env = os.environ.copy()
                
                # --- INYECCIÓN DE DEPENDENCIAS ---
                env["OPENSTUDIO_BUILD_TARGET"] = "STORYBOARD"
                env["OPENSTUDIO_PROJECT_ROOT"] = str(project_root)
                env["OPENSTUDIO_PRODUCTION_FOLDER"] = vfs_svn
                env["BLENDER_USER_RESOURCES"] = str(project_root / vfs_local / "blender_data")
                env["OPENSTUDIO_TARGET_SEQUENCE"] = seq_name 
                env["OPENSTUDIO_KITSU_PROJECT_ID"] = str(self.project_id)
                
                # --- CÓDIGO CORREGIDO ---
                env["OPENSTUDIO_KITSU_HOST"] = self.config.get_kitsu_api_url()
                env["OPENSTUDIO_KITSU_USER"] = os.environ.get("OPENSTUDIO_KITSU_USER", "")
                env["OPENSTUDIO_KITSU_PWD"] = os.environ.get("OPENSTUDIO_KITSU_PWD", "")
                # ----------------------------------------
                
                script_path = Path(__file__).parent.parent.parent / "core" / "templates" / "headless_builder.py"
                cmd = [exe_list[0], "-b", "--python", str(script_path)]
                
                proceso = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in proceso.stdout:
                    if line.strip(): self.log_stream.emit(f"    ↳ {line.strip()}")
                proceso.wait()
                
                if proceso.returncode != 0:
                    self.log_stream.emit(f"[{seq_name}] ❌ ERROR: Blender Headless failed.")
                else:
                    self.log_stream.emit(f"[{seq_name}] ✓ Physical file spawned.")

            self.progress_updated.emit(100, self.tr("Batch Creation Complete!"))
            self.finished_batch.emit(True, f"{total_seqs} Storyboard sequences processed successfully.")
            
        except Exception as e:
            self.finished_batch.emit(False, str(e))
