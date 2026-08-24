# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/git_packager.py
# Rol Arquitectónico: Backend Worker / Git LFS Provisioning
# =========================================================================================

import os
import shutil
import zipfile
import tempfile
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from src.infrastructure.manifest_manager import ManifestManager
from src.domain.addon_parser import AddonParser

class StudioToolsPackagerWorker(QThread):
    """Clones the repo (resolving Git LFS), repacks internal addons individually, and registers valid ones."""
    progress_updated = Signal(int)
    status_update = Signal(str, str)
    finished_packing = Signal()
    error_occurred = Signal(str)

    def __init__(self, manifest_manager: ManifestManager, current_version: str):
        super().__init__()
        self.manifest_manager = manifest_manager
        self.current_version = current_version

    def _verificar_dependencias_sistema(self):
        """Valida que Git y Git LFS estén instalados en la máquina del TD."""
        if not shutil.which("git"):
            raise RuntimeError("Git no está instalado o no está en el PATH del sistema. Instala Git para continuar.")
        
        # Verificar soporte LFS
        resultado = subprocess.run(["git", "lfs", "version"], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError("Git LFS no está instalado. Ejecuta 'git lfs install' en tu terminal antes de continuar.")

    def run(self):
        try:
            # 1. Pre-Flight Check
            self.status_update.emit("Verificando dependencias del sistema (Git LFS)...", "yellow")
            self._verificar_dependencias_sistema()

            self.status_update.emit("Clonando repositorio Studio Tools (Resolviendo LFS)...", "yellow")
            temp_dir = Path(tempfile.mkdtemp())
            repo_dir = temp_dir / "blender-studio-tools"
            
            # 2. Clonación directa por Git para forzar la descarga de los binarios LFS
            result = subprocess.run(
                ["git", "clone", "--depth", "1", "https://projects.blender.org/studio/blender-studio-tools.git", str(repo_dir)],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"Fallo crítico durante git clone: {result.stderr}")

            self.status_update.emit("Empaquetando add-ons internos...", "yellow")
            
            # 3. Identificar las carpetas de add-ons en el repositorio clonado
            addons_src_dir = repo_dir / "scripts-blender" / "addons"
            if not addons_src_dir.exists():
                raise ValueError("El directorio de add-ons no se encontró en el repositorio clonado.")

            addon_dirs = [d for d in addons_src_dir.iterdir() if d.is_dir()]
            total = len(addon_dirs)
            registered_count = 0
            
            # 4. Empaquetar y validar dinámicamente
            for i, addon_dir in enumerate(addon_dirs):
                addon_name = addon_dir.name
                self.status_update.emit(f"Empaquetando herramienta interna: {addon_name}...", "yellow")
                
                addon_zip_path = temp_dir / f"{addon_name}.zip"
                
                # Escribimos un nuevo ZIP limpio desde el sistema de archivos
                with zipfile.ZipFile(addon_zip_path, 'w', zipfile.ZIP_DEFLATED) as out_zf:
                    for root, _, files in os.walk(addon_dir):
                        for file in files:
                            file_path = Path(root) / file
                            arcname = file_path.relative_to(addons_src_dir)
                            out_zf.write(file_path, arcname)
                
                # Validación vía AddonParser
                parsed = AddonParser.parse_zip(addon_zip_path)
                if parsed["is_valid"]:
                    if AddonParser.is_compatible(parsed["min_blender_version"], self.current_version):
                        exito, msg = self.manifest_manager.register_addon(
                            blender_version=self.current_version,
                            addon_name=parsed["name"],
                            addon_version=parsed["version"],
                            source_zip=addon_zip_path
                        )
                        if exito:
                            registered_count += 1
                
                self.progress_updated.emit(int(((i + 1) / total) * 100))
            
            # 5. Atomic Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            self.status_update.emit(f"✓ Studio Tools Auto-Fetch completado. {registered_count} add-ons registrados.", "green")
            self.finished_packing.emit()
            
        except Exception as e:
            import traceback
            print(f"[StudioToolsPackager] ERROR: {traceback.format_exc()}")
            self.error_occurred.emit(str(e))
            # Fallback cleanup en caso de error
            if 'temp_dir' in locals() and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
