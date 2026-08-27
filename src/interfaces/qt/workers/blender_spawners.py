import subprocess
import os
from pathlib import Path
from PySide6.QtCore import QThread, Signal

from src.domain.shared_kernel.env_contract import SandboxEnvironment
from src.infrastructure.sandbox.blender_locator import BlenderLocator


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
            blender_bin = BlenderLocator.resolve(base_blender_dir)

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
                    
                    sandbox = SandboxEnvironment(
                        build_target=e_type,
                        project_root=str(project_root),
                        production_folder=vfs_svn,
                        blender_user_resources=str(project_root / vfs_local / "blender_data"),
                        kitsu_project_id=str(self.project_id),
                        target_entity_id=str(e_id),
                        kitsu_entity_name=str(e_name),
                        kitsu_asset_type_id=str(entity.get("asset_type_id", "")),
                        kitsu_asset_type_name=str(entity.get("asset_type_name", "")),
                        kitsu_host=self.config.get_kitsu_api_url(),
                        kitsu_user=os.environ.get("OPENSTUDIO_KITSU_USER", ""),
                        kitsu_pwd=os.environ.get("OPENSTUDIO_KITSU_PWD", ""),
                    )
                    if e_type == "SHOT":
                        sandbox.kitsu_sequence_name = str(entity.get("parent", ""))
                        sandbox.kitsu_task_type_name = str(t_name)

                    env = os.environ.copy()
                    env.update(sandbox.to_os_environ())
                    
                    script_path = Path(__file__).resolve().parent.parent.parent.parent / "infrastructure" / "templates" / "headless_builder.py"
                    cmd = [str(blender_bin), "-b", "--python", str(script_path)]
                    
                    proceso = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    for line in proceso.stdout:
                        if line.strip(): self.log_stream.emit(f"    ↳ {line.strip()}")
                    proceso.wait()
                    
                    if proceso.returncode != 0:
                        self.log_stream.emit(f"[{display_name}] ❌ ERROR: Blender Headless failed.")
                    else:
                        self.log_stream.emit(f"[{display_name}] ✓ Physical file spawned.")

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
            blender_bin = BlenderLocator.resolve(base_blender_dir)

            self.progress_updated.emit(20, self.tr("Preparing environment variables..."))
            sandbox = SandboxEnvironment(
                build_target=self.build_target,
                project_root=str(project_root),
                production_folder=self.config.get_vfs_svn_name(),
                blender_user_resources=str(project_root / vfs_local / "blender_data"),
                kitsu_project_id=str(self.project_id),
                kitsu_host=self.config.get_kitsu_api_url(),
                kitsu_user=os.environ.get("OPENSTUDIO_KITSU_USER", ""),
                kitsu_pwd=os.environ.get("OPENSTUDIO_KITSU_PWD", ""),
            )
            env = os.environ.copy()
            env.update(sandbox.to_os_environ())
            
            script_path = Path(__file__).resolve().parent.parent.parent.parent / "infrastructure" / "templates" / "headless_builder.py"
            
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
            blender_bin = BlenderLocator.resolve(base_blender_dir)

            for idx, seq_name in enumerate(self.sequence_names):
                base_progress = 10 + int((idx / total_seqs) * 90)
                self.progress_updated.emit(base_progress, self.tr(f"Processing Sequence: {seq_name} ({idx+1}/{total_seqs})"))
                
                vfs_svn = self.config.get_vfs_svn_name()
                self.log_stream.emit(f"\n[{seq_name}] Registering Entity and Task in Kitsu API...")
                seq = self.pm_core.register_storyboard_sequence(self.project_id, seq_name, tt_id, vfs_svn)
                if seq:
                    self.log_stream.emit(f"[{seq_name}] ✓ Kitsu database and file mapping updated.")
                else:
                    self.log_stream.emit(f"[{seq_name}] ⚠️ Failed to register sequence in Kitsu.")

                self.log_stream.emit(f"[{seq_name}] Spawning physical .blend file via Headless Engine...")
                
                sandbox = SandboxEnvironment(
                    build_target="STORYBOARD",
                    project_root=str(project_root),
                    production_folder=vfs_svn,
                    blender_user_resources=str(project_root / vfs_local / "blender_data"),
                    target_sequence=seq_name,
                    kitsu_project_id=str(self.project_id),
                    kitsu_host=self.config.get_kitsu_api_url(),
                    kitsu_user=os.environ.get("OPENSTUDIO_KITSU_USER", ""),
                    kitsu_pwd=os.environ.get("OPENSTUDIO_KITSU_PWD", ""),
                )
                env = os.environ.copy()
                env.update(sandbox.to_os_environ())
                
                script_path = Path(__file__).resolve().parent.parent.parent.parent / "infrastructure" / "templates" / "headless_builder.py"
                cmd = [str(blender_bin), "-b", "--python", str(script_path)]
                
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
