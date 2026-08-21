import glob
import re
from pathlib import Path
from PySide6.QtCore import QThread, Signal

from core.kitsu_manager import KitsuManager

def sanitize_kitsu_name(raw_name: str) -> str:
    if not raw_name:
        return ""
    clean_name = raw_name.lower().replace(" ", "_")
    clean_name = re.sub(r'[^a-z0-9_\-]', '', clean_name)
    return re.sub(r'_+', '_', clean_name)

class FetchProjectsWorker(QThread):
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self):
        super().__init__()
        self.kitsu = KitsuManager()

    def run(self):
        try:
            self.data_ready.emit(self.kitsu.all_projects())
        except Exception as e:
            self.error_occurred.emit(str(e))

class FetchShotsWorker(QThread):
    """Consulta Kitsu y el disco físico para auditar el estado de los Shots."""
    data_ready = Signal(list, list)
    error_occurred = Signal(str)

    def __init__(self, project_id: str, project_root: Path, vfs_svn: str):
        super().__init__()
        self.project_id = project_id
        self.project_root = project_root
        self.vfs_svn = vfs_svn
        self.kitsu = KitsuManager()

    def run(self):
        try:
            # 1. Traemos TODOS los shots y TODAS las secuencias (para mapeo rápido)
            shots = self.kitsu.all_shots_for_project(self.project_id)
            sequences = self.kitsu.all_sequences_for_project(self.project_id)
            all_tasks = self.kitsu.all_tasks_for_project(self.project_id)
            task_types = self.kitsu.all_task_types()
            
            # Mapa ultra-rápido para no consultar Kitsu por cada shot
            seq_map = {seq["id"]: seq["name"] for seq in sequences}
            tt_map = {tt["id"]: tt["name"] for tt in task_types}
            
            tasks_by_entity = {}
            for task in all_tasks:
                eid = task.get("entity_id")
                if eid not in tasks_by_entity:
                    tasks_by_entity[eid] = []
                tasks_by_entity[eid].append(task)

            result = []
            project_task_types = set()

            for shot in shots:
                shot_id = shot["id"]
                name = shot.get("name", "Unknown")
                seq_name = seq_map.get(shot.get("parent_id"), "Unknow")

                shot_tasks_data = {}
                shot_tasks = tasks_by_entity.get(shot_id, [])

                shot_has_all_files = True
                if not shot_tasks: shot_has_all_files = False

                for task in shot_tasks:
                    tt_name = tt_map.get(task["task_type_id"], "Unknown")
                    project_task_types.add(tt_name)

                    has_file = False
                    
                    task_data = task.get("data")
                    if not task_data:
                        task_data = {}

                    # AHORA AUDITAMOS EL FILEPATH DE LA TAREA, NO DEL SHOT
                    kitsu_filepath = task_data.get("filepath")
                    
                    if kitsu_filepath:
                        physical_path = self.project_root / self.vfs_svn / kitsu_filepath
                        if physical_path.exists():
                            has_file = True

                    shot_tasks_data[tt_name] = {
                        "task_id": task["id"],
                        "has_file": has_file,
                        "raw_task": task
                    }
                    
                    if not has_file:
                        shot_has_all_files = False
                
                # # Obtener el nombre de la secuencia a la que pertenece
                # parent_id = shot.get("parent_id")
                # seq_name = seq_map.get(parent_id, "Unknown")
                #
                # # Inyectamos la secuencia en la data cruda (útil para el render o spawners)
                # shot["sequence_name"] = seq_name
                #
                # # Auditoría usando metadatos de filepath
                # shot_data = shot.get("data")
                # if not shot_data:
                #     shot_data = {}
                #
                # kitsu_filepath = shot_data.get("filepath")
                #
                # if kitsu_filepath:
                #     physical_path = self.project_root / self.vfs_svn / kitsu_filepath
                #     if physical_path.exists():
                #         has_file = True
                #     else:
                #         print(f"[AUDITORIA SHOTS] ⚠️ Ruta registrada en Kitsu, pero no existe: {physical_path}")
                #

                result.append({
                    "id": shot_id,
                    "name": name,
                    "type": "Shot",
                    "parent": seq_name,
                    "frame_in": shot.get("nb_frames", 0),
                    "tasks": shot_tasks_data, # Diccionario con el estado de cada tarea
                    "has_file": shot_has_all_files, # Para bloquear el checkbox principal
                    "raw_data": shot
                })
                
            self.data_ready.emit(result, list(project_task_types))
        except Exception as e:
            self.error_occurred.emit(str(e))

class FetchEntitiesWorker(QThread):
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, pm_core, project_id):
        super().__init__()
        self.pm_core = pm_core
        self.project_id = project_id

    def run(self):
        try:
            self.data_ready.emit(self.pm_core.get_pending_entities(self.project_id))
        except Exception as e:
            self.error_occurred.emit(str(e))

class FetchSequencesWorker(QThread):
    """Consulta las secuencias de Kitsu y verifica su existencia física en el SVN."""
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, project_id: str, project_root: Path, vfs_svn: str):
        super().__init__()
        self.project_id = project_id
        self.project_root = project_root
        self.vfs_svn = vfs_svn
        self.kitsu = KitsuManager()

    def run(self):
        try:
            # 1. Traer todas las secuencias del proyecto en Kitsu
            sequences = self.kitsu.all_sequences_for_project(self.project_id)
            
            result = []
            for seq in sequences:
                name = seq.get("name", "").upper()
                
                # 2. Verificar existencia física del .blend
                file_path = self.project_root / self.vfs_svn / "edit" / "storyboards" / f"{name.lower()}-storyboard.blend"
                has_file = file_path.exists()
                
                result.append({
                    "name": name,
                    "has_file": has_file
                })
                
            self.data_ready.emit(result)
        except Exception as e:
            self.error_occurred.emit(str(e))

class FetchAssetsWorker(QThread):
    """Consulta Kitsu y el disco físico para auditar el estado de los Assets."""
    data_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, project_id: str, project_root: Path, vfs_svn: str):
        super().__init__()
        self.project_id = project_id
        self.project_root = project_root
        self.vfs_svn = vfs_svn
        self.kitsu = KitsuManager()

    def run(self):
        try:
            # Extraer todos los assets del proyecto desde la base de datos
            assets = self.kitsu.all_assets_for_project(self.project_id)
            
            # --- Traer todos los Asset Types de Kitsu para mapearlos ---
            all_asset_types = self.kitsu.all_asset_types()
            asset_types_map = {at["id"]: at for at in all_asset_types}
            # ------------------------------------------------------------------

            result = []
            asset_dir = self.project_root / self.vfs_svn / "assets"
            
            for asset in assets:
                raw_name = asset.get("name", "Unknown")
                clean_name= sanitize_kitsu_name(raw_name)

                has_file = False

                asset_data = asset.get("data")
                if not asset_data:
                    asset_data = {}

                kitsu_filepath = asset_data.get("filepath")

                if kitsu_filepath:
                    physical_path = self.project_root / self.vfs_svn / kitsu_filepath

                    if physical_path.exists():
                        has_file = True
                    else:
                        print(f"[AUDITORIA ASSETS] ⚠️ Ruta registrada en Kitsu, pero no existe en disco: {physical_path}")
                else:
                    pass


                # --- Inyectar el Asset Type en la metadata cruda ---
                type_id = asset.get("entity_type_id")
                if type_id and type_id in asset_types_map:
                    asset["asset_type_id"] = type_id
                    asset["asset_type_name"] = asset_types_map[type_id].get("name", "")
                else:
                    asset["asset_type_id"] = ""
                    asset["asset_type_name"] = ""
                # ----------------------------------------------------------

                # if asset_dir.exists():
                #     found = list(asset_dir.rglob(f"*{clean_name}*.blend"))
                #     found = [f for f in found if "blend1" not in str(f)]
                #     if found:
                #         has_file = True

                final_name=raw_name

                if not has_file and raw_name != clean_name:
                    try:
                        # Corregimos el nombre permanentemente en la base de datos de Kitsu
                        asset["name"] = clean_name
                        self.kitsu.update_asset(asset)
                        final_name = clean_name
                    except Exception as e:
                        print(f"⚠️ Error actualizando nombre en Kitsu para {raw_name}: {e}")

                
                asset["name"] = final_name

                result.append({
                    "id": asset["id"],
                    "name": final_name,
                    "type": asset["asset_type_name"],
                    "has_file": has_file,
                    "raw_data": asset # Guardamos la data cruda para el Spawning
                })
                
            self.data_ready.emit(result)
        except Exception as e:
            self.error_occurred.emit(str(e))

class FetchEditStatusWorker(QThread):
    """Consulta Kitsu y el disco físico para auditar el estado del Master de Edición."""
    data_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, project_id: str, project_name: str, project_root: Path, vfs_svn: str):
        super().__init__()
        self.project_id = project_id
        self.project_name = project_name
        self.project_root = project_root
        self.vfs_svn = vfs_svn
        self.kitsu = KitsuManager()

    def run(self):
        try:
            
            # 1. Buscar la entidad Edit en Kitsu (Usualmente Kitsu crea un 'Edit' global)
            edits = self.kitsu.all_edits_for_project(self.project_id)
            main_edit = edits[0] if edits else None
            
            status_name = "Not Created"
            assignees_names = "Unassigned"
            
            # 2. Extraer metadata de Kitsu si existe
            if main_edit:
                tasks = self.kitsu.all_tasks_for_edit(main_edit["id"])
                task = tasks[0] if tasks else None

                #main_edit

                task = tasks[0] if tasks else None
                if task:
                    status_name = task.get("task_status", {}).get("name", "N/A")
                    assignees = task.get("assignees", [])
                    if assignees:
                        assignees_names = ", ".join([a.get("full_name", "Unknown") for a in assignees])

            # 3. Auditar la verdad física en el SVN
            edit_dir = self.project_root / self.vfs_svn / "edit"
            has_file = False
            file_name = "File not found"
            version = "N/A"
            
            if edit_dir.exists():
                # Buscar el archivo .blend de edición (ignora auto-saves)
                blend_files = glob.glob(str(edit_dir / "*.blend"))
                blend_files = [f for f in blend_files if "blend1" not in f]
                
                if blend_files:
                    has_file = True
                    blend_files.sort()
                    latest_file = Path(blend_files[-1]) # Tomamos la versión más alta
                    file_name = latest_file.name
                    
                    # Regex para extraer el v001, v002 del final del nombre
                    match = re.search(r'(v\d+)', file_name, re.IGNORECASE)
                    if match:
                        version = match.group(1).lower()

            # 4. Empaquetar resultados
            result = {
                "has_file": has_file,
                "file_name": file_name,
                "version": version,
                "assignees": assignees_names,
                "status": status_name
            }
            
            self.data_ready.emit(result)
        except Exception as e:
            self.error_occurred.emit(str(e))
