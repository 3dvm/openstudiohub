# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/provisioning_workers.py
# Rol Arquitectónico: Core Services / Network Downloaders & Archivers
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0
# =========================================================================================

import shutil
import tempfile
import urllib.request
import zipfile
import os

from pathlib import Path
from html.parser import HTMLParser
from PySide6.QtCore import Signal, QThread

from src.domain.addon_inspector import AddonInspector
from src.infrastructure.manifest_manager import ManifestManager
from src.domain.addon_parser import AddonParser

class ApacheIndexParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for attr, value in attrs:
                if attr == 'href':
                    self.links.append(value)

class RepoFolderFetcherWorker(QThread):
    folders_ready = Signal(list)
    status = Signal(str, str)

    def run(self):
        try:
            req = urllib.request.Request("https://download.blender.org/release/", headers={'User-Agent': 'OpenStudioHub/1.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8')
            parser = ApacheIndexParser()
            parser.feed(html)
            raw_folders = [l for l in parser.links if l.endswith('/') and ('Blender' in l or l.replace('/', '').replace('.', '').isdigit())]
            raw_folders.sort(reverse=True)
            self.folders_ready.emit(raw_folders)
            self.status.emit("✓ Remote directory tree fetched.", "green")
        except Exception as e:
            self.status.emit(f"✗ Failed to reach remote repository: {str(e)}", "red")
            self.folders_ready.emit([])

class RepoFileFetcherWorker(QThread):
    files_ready = Signal(list)
    status = Signal(str, str)

    def __init__(self, folder_name: str):
        super().__init__()
        self.folder_name = folder_name

    def run(self):
        try:
            url = f"https://download.blender.org/release/{self.folder_name}"
            req = urllib.request.Request(url, headers={'User-Agent': 'OpenStudioHub/1.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8')
            parser = ApacheIndexParser()
            parser.feed(html)
            valid_exts = ('.zip', '.xz', '.dmg', '.msi', '.exe', '.pkg')
            raw_files = [f for f in parser.links if f.endswith(valid_exts) and not f.startswith('?')]
            raw_files.sort()
            self.files_ready.emit(raw_files)
        except Exception as e:
            self.status.emit(f"✗ Failed to fetch binaries: {str(e)}", "red")
            self.files_ready.emit([])

class BlenderDirectDownloadWorker(QThread):
    progress = Signal(int)
    status = Signal(str, str)
    finished = Signal(bool, str)

    def __init__(self, folder_name: str, file_name: str, target_dir: Path):
        super().__init__()
        self.folder_name = folder_name
        self.file_name = file_name
        self.target_dir = target_dir

    def run(self):
        try:
            final_path = self.target_dir / self.file_name
            
            # 1. Inteligencia de Caché: Evitar descargas duplicadas
            if final_path.exists():
                self.status.emit(f"✓ Asset '{self.file_name}' already exists in Vault. Skipped download.", "green")
                self.progress.emit(100)
                self.finished.emit(True, self.file_name)
                return

            # 2. Flujo de Descarga
            url = f"https://download.blender.org/release/{self.folder_name}{self.file_name}"
            self.target_dir.mkdir(parents=True, exist_ok=True)
            archive_path = self.target_dir / f"{self.file_name}.tmp"
            
            self.status.emit(f"Downloading selected package: {self.file_name}...", "yellow")
            req = urllib.request.Request(url, headers={'User-Agent': 'OpenStudioHub/1.0'})
            
            with urllib.request.urlopen(req) as response:
                total_size = int(response.info().get('Content-Length', 0))
                downloaded = 0
                block_size = 1024 * 64

                with open(archive_path, 'wb') as out_file:
                    while True:
                        block = response.read(block_size)
                        if not block: break
                        downloaded += len(block)
                        out_file.write(block)
                        if total_size > 0:
                            self.progress.emit(int((downloaded / total_size) * 100))

            archive_path.rename(final_path)
            self.status.emit(f"✓ Compressed asset '{self.file_name}' mirrored on NAS.", "green")
            self.finished.emit(True, self.file_name)

        except Exception as e:
            self.status.emit(f"✗ Archive transfer failed: {str(e)}", "red")
            self.finished.emit(False, "")

class StudioToolsFetchWorker(QThread):
    """
    Descarga la release oficial de Studio Tools, detecta las carpetas internas,
    las re-empaqueta en archivos .zip dinámicamente según la barrera de Blender 4.2,
    y registra los add-ons compatibles en la bóveda.
    """
    progress_updated = Signal(int)
    status_update = Signal(str, str)
    finished_packing = Signal(dict) 
    error_occurred = Signal(str)

    def __init__(self, vault_root: Path, current_version: str):
        super().__init__()
        self.vault_root = vault_root
        self.current_version = current_version
        self.url = "https://projects.blender.org/studio/blender-studio-tools/releases/download/latest/blender_studio_add-ons_latest.zip"

    def run(self):
        # 0. Instanciamos el manager de forma segura, asilado dentro de este hilo
        from src.infrastructure.manifest_manager import ManifestManager
        self.manifest_manager = ManifestManager(self.vault_root)

        temp_dir = Path(tempfile.mkdtemp())
        master_zip_path = temp_dir / "blender_studio_add-ons_latest.zip"
        
        try:
            # 1. Descarga del Release ZIP usando urllib.request nativo
            # (Mantén exactamente el mismo bloque try/except que tenías para la descarga, 
            # extracción y re-empaquetado dual de la iteración anterior)
            
            self.status_update.emit("Descargando release oficial de Studio Tools...", "yellow")
            import urllib.request
            req = urllib.request.Request(self.url, headers={'User-Agent': 'OpenStudioHub/1.0'})
            
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.info().get('Content-Length', 0))
                downloaded = 0
                with open(master_zip_path, 'wb') as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk: break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            self.progress_updated.emit(int((downloaded / total_size) * 30))
                            
            self.status_update.emit("Extrayendo master branch...", "yellow")
            
            # 2. Extracción del Master ZIP
            extract_dir = temp_dir / "extracted"
            extract_dir.mkdir()
            with zipfile.ZipFile(master_zip_path, 'r') as zf:
                zf.extractall(extract_dir)
                
            # 3. Ubicar el directorio raíz de los add-ons (manejando la subcarpeta de Gitea)
            addons_root = extract_dir
            subdirs = [d for d in addons_root.iterdir() if d.is_dir()]
            if len(subdirs) == 1 and "blender_studio_add-ons" in subdirs[0].name:
                addons_root = subdirs[0]

            addon_dirs = [d for d in addons_root.iterdir() if d.is_dir() and ((d / "blender_manifest.toml").exists() or (d / "__init__.py").exists())]
            
            if not addon_dirs:
                raise ValueError("No se encontraron directorios de add-ons válidos en la release.")
                
            total_addons = len(addon_dirs)
            registered_count = 0
            
            # 2. Creamos un diccionario para acumular lo que logramos registrar
            nuevos_addons_ram = {}
            import os

            addons_dir =self.vault_root / "addons"
            addons_dir.mkdir(parents=True, exist_ok=True)

            for i, addon_dir in enumerate(addon_dirs):
                self.status_update.emit(f"Empaquetando y validando {addon_dir.name}...", "yellow")
                addon_zip_path = temp_dir / f"{addon_dir.name}.zip"
                
                # Barrera Blender 4.2+: Las extensiones exigen el manifiesto en la raíz absoluta del ZIP.
                # Legacy (<4.2): Los add-ons clásicos exigen estar contenidos en una subcarpeta.
                is_extension = (addon_dir / "blender_manifest.toml").exists()
                
                with zipfile.ZipFile(addon_zip_path, 'w', zipfile.ZIP_DEFLATED) as out_zf:
                    for root, _, files in os.walk(addon_dir):
                        for file in files:
                            file_path = Path(root) / file
                            arcname = file_path.relative_to(addon_dir) if is_extension else file_path.relative_to(addon_dir.parent)
                            out_zf.write(file_path, arcname)
                
                # Validación y Registro en la Bóveda
                parsed = AddonParser.parse_zip(addon_zip_path)
                if parsed["is_valid"]:
                    if AddonParser.is_compatible(parsed["min_blender_version"], self.current_version):
                        addon_name_parsed = parsed["name"]
                        addon_ver_parsed = parsed["version"]

                        target_zip_name = f"{addon_name_parsed}-{addon_ver_parsed}.zip"
                        target_zip_path = addons_dir / target_zip_name
                        shutil.copy2(addon_zip_path, target_zip_path)

                        exito, msg = self.manifest_manager.register_addon(
                            blender_version=self.current_version,
                            addon_name=addon_name_parsed,
                            addon_version=addon_ver_parsed,
                            source_zip=target_zip_path
                        )
                        if exito:
                            registered_count += 1
                            # 3. Guardamos los datos con la misma estructura que usa TabSoftware
                            desc = parsed.get("description", "Blender Studio Tool")
                            nuevos_addons_ram[addon_name_parsed] = {
                                "version": addon_ver_parsed,
                                "description": desc[:60] + "..." if len(desc) > 60 else desc,
                                "mandatory": False,
                                "requires": []
                            }
                            
                self.progress_updated.emit(30 + int(((i + 1) / total_addons) * 70))
                
            self.status_update.emit(f"✓ Studio Tools Auto-Fetch completado. {registered_count} add-ons registrados.", "green")
            
            # 4. Emitimos la señal entregando el diccionario a la interfaz
            self.finished_packing.emit(nuevos_addons_ram)
            
        except Exception as e:
            import traceback
            print(f"[StudioToolsFetchWorker] ERROR: {traceback.format_exc()}")
            self.error_occurred.emit(str(e))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
