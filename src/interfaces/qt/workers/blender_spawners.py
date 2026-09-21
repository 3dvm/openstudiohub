import subprocess
import os
from collections import deque
from pathlib import Path
from PySide6.QtCore import Signal

from src.infrastructure.qt_worker import ManagedWorker

from src.domain.production.naming import NamingPolicy
from src.domain.shared_kernel.env_contract import SandboxEnvironment
from src.infrastructure.sandbox.blender_locator import BlenderLocator


class BatchCreationWorker(ManagedWorker):
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
            failures = []

            for idx, entity in enumerate(self.entities):
                e_name = entity.get("name", "Unknown")
                e_id = entity.get("id", "")
                # For assets ``type`` holds the asset type name (e.g. "Character");
                # only shots route to the dedicated SHOT builder. Asset files are
                # always forged by the generic ASSET builder, with the Kitsu asset
                # type forwarded separately via ``kitsu_asset_type_id``.
                e_type = entity.get("type", "Asset").upper()
                build_target = "SHOT" if e_type == "SHOT" else "ASSET"

                # --- TASK FILTERING LOGIC ---
                # Spawn only the task types the PM selected, and only when the
                # task has no physical file yet. Entities with no Kitsu tasks are
                # gated out in the UI (no blank-file fallback here).
                selected = set(self.task_types or [])
                tasks_to_spawn = []
                tasks_dict = entity.get("tasks", {})
                for t_name, task_info in tasks_dict.items():
                    if selected and t_name not in selected:
                        continue
                    if not task_info.get("has_file"):
                        tasks_to_spawn.append((t_name, task_info))
                # -------------------------------------------
                
                # Nested loop to iterate each missing task of the entity
                for t_idx, (t_name, task_info) in enumerate(tasks_to_spawn):
                    
                    display_name = f"{e_name} [{t_name}]" if t_name else e_name
                    base_progress = 10 + int((idx / total_ents) * 90)
                    self.progress_updated.emit(base_progress, self.tr(f"Processing {e_type}: {display_name} ({idx+1}/{total_ents})"))
                    
                    self.log_stream.emit(f"\n[{display_name}] Spawning physical file via Headless Engine...")
                    
                    sandbox = SandboxEnvironment(
                        build_target=build_target,
                        project_root=str(project_root),
                        production_folder=vfs_svn,
                        blender_user_resources=str(project_root / vfs_local / "blender_data"),
                        blender_user_scripts=str(project_root / vfs_local / "blender_data" / "scripts"),
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
                    else:
                        # Assets: forge at the task's linked/suggested path.
                        sandbox.kitsu_task_type_name = str(t_name)
                        relative_path = (task_info or {}).get("filepath", "")
                        if not relative_path and t_name:
                            asset_type = entity.get("asset_type_name") or entity.get("type") or "props"
                            try:
                                relative_path = str(NamingPolicy.asset_path(asset_type, e_name, t_name))
                            except Exception:  # noqa: BLE001
                                relative_path = ""
                        sandbox.task_file_path = relative_path

                    env = os.environ.copy()
                    env.update(sandbox.to_os_environ())
                    
                    script_path = Path(__file__).resolve().parent.parent.parent.parent / "infrastructure" / "templates" / "headless_builder.py"
                    cmd = [str(blender_bin), "-b", "--python", str(script_path)]
                    
                    proceso = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    for line in proceso.stdout:
                        if line.strip(): self.log_stream.emit(f"    ↳ {line.strip()}")
                    proceso.wait()
                    
                    if proceso.returncode != 0:
                        failures.append(display_name)
                        self.log_stream.emit(f"[{display_name}] ❌ ERROR: Blender Headless failed.")
                    else:
                        self.log_stream.emit(f"[{display_name}] ✓ Physical file spawned.")

            self.progress_updated.emit(100, self.tr("Batch Creation Complete!"))
            if failures:
                self.finished_batch.emit(
                    False,
                    self.tr("Failed to forge {count} file(s): {names}").format(
                        count=len(failures), names=", ".join(failures)
                    ),
                )
            else:
                self.finished_batch.emit(True, f"{total_ents} entities processed successfully.")
            
        except Exception as e:  # noqa: BLE001
            error_message = f"{type(e).__name__}: {e}"
            print(f"[{self.__class__.__name__}] {error_message}")
            self.log_stream.emit(f"❌ {error_message}")
            self.finished_batch.emit(False, error_message)

class MasterSpawningWorker(ManagedWorker):
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
                blender_user_scripts=str(project_root / vfs_local / "blender_data" / "scripts"),
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

            # Track the headless build result instead of trusting the exit code
            # alone: the builder always used to exit 0, even on failure.
            tail = deque(maxlen=15)
            saw_ok = False
            saw_failure = False
            created_path = ""

            for line in proceso.stdout:
                line_clean = line.strip()
                if not line_clean: continue
                self.log_stream.emit(line_clean)
                tail.append(line_clean)

                if "RESULT: OK" in line_clean:
                    saw_ok = True
                elif "RESULT: FAILED" in line_clean:
                    saw_failure = True

                if "EXITOSO EN:" in line_clean or "creado en:" in line_clean:
                    self.progress_updated.emit(90, self.tr("Writing physical file..."))
                    for marker in ("EXITOSO EN:", "creado en:"):
                        if marker in line_clean:
                            created_path = line_clean.split(marker, 1)[-1].strip()
                            break
                elif "Cargando App-Template" in line_clean:
                    self.progress_updated.emit(50, self.tr("Loading UI Template..."))
                elif "Restaurando contexto Kitsu" in line_clean:
                    self.progress_updated.emit(70, self.tr("Authenticating with server..."))

            proceso.wait()
            if proceso.returncode == 0 and saw_ok and not saw_failure:
                self.progress_updated.emit(100, self.tr("Master File Forged Successfully!"))
                message = f"{self.build_target} created."
                if created_path:
                    message = f"{self.build_target} created: {created_path}"
                self.finished_spawn.emit(True, message)
            else:
                details = "\n".join(tail)
                reason = (
                    "The headless builder reported a failure."
                    if saw_failure
                    else f"Blender exited with code {proceso.returncode} without a result marker."
                )
                self.finished_spawn.emit(False, f"{reason}\n{details}".strip())

        except Exception as e:  # noqa: BLE001
            error_message = f"{type(e).__name__}: {e}"
            print(f"[{self.__class__.__name__}] {error_message}")
            self.log_stream.emit(f"❌ {error_message}")
            self.finished_spawn.emit(False, error_message)

class StoryboardBatchWorker(ManagedWorker):
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
                    blender_user_scripts=str(project_root / vfs_local / "blender_data" / "scripts"),
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
            
        except Exception as e:  # noqa: BLE001
            error_message = f"{type(e).__name__}: {e}"
            print(f"[{self.__class__.__name__}] {error_message}")
            self.log_stream.emit(f"❌ {error_message}")
            self.finished_batch.emit(False, error_message)
