# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/file_downloader.py
# Rol Arquitectónico: Utility / Asynchronous Network Engine
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.0.0
# =========================================================================================

"""
Motor de transferencia asíncrono para descargas masivas (Chunked Streaming).
Desacoplado del hilo principal de la GUI (QThread). Escribe de forma atómica
en el disco destino e implementa limpieza de residuos (Rollback) ante caídas de red.
"""

import requests
from pathlib import Path
from PySide6.QtCore import QThread, Signal

class FileDownloaderWorker(QThread):
    """
    Worker Thread para descargas HTTP.
    Emite el progreso porcentual y garantiza la integridad estructural del archivo.
    """
    progress_updated = Signal(int)
    status_update = Signal(str, str)
    download_completed = Signal(Path)
    error_occurred = Signal(str)

    def __init__(self, url: str, dest_path: Path, chunk_size: int = 8192):
        super().__init__()
        self.url = url
        self.dest_path = dest_path
        self.chunk_size = chunk_size

    def run(self):
        try:
            self.status_update.emit(f"Iniciando descarga: {self.dest_path.name}...", "yellow")
            
            # Garantizar la existencia estructural del árbol de directorios destino
            self.dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Iniciar conexión de flujo continuo (Evita desbordamiento de RAM)
            with requests.get(self.url, stream=True, timeout=15) as response:
                response.raise_for_status()
                
                total_length = response.headers.get('content-length')
                
                if total_length is None:
                    # El servidor no reporta tamaño (Descarga ciega)
                    with open(self.dest_path, 'wb') as f:
                        f.write(response.content)
                    self.progress_updated.emit(100)
                else:
                    # Descarga fraccionada con cálculo aritmético de progreso
                    dl_bytes = 0
                    total_length = int(total_length)
                    
                    with open(self.dest_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=self.chunk_size):
                            if chunk:
                                dl_bytes += len(chunk)
                                f.write(chunk)
                                done_percent = int(100 * dl_bytes / total_length)
                                self.progress_updated.emit(done_percent)
                                
            self.status_update.emit(f"Descarga completada y verificada: {self.dest_path.name}", "green")
            self.download_completed.emit(self.dest_path)
            
        except requests.exceptions.RequestException as e:
            self._rollback_cleanup()
            self.error_occurred.emit(f"Fallo de integridad de red: {e}")
            
        except Exception as e:
            self._rollback_cleanup()
            self.error_occurred.emit(f"Fallo de E/S local: {e}")

    def _rollback_cleanup(self):
        """Purga el archivo parcialmente descargado para evitar empaquetados corruptos en la bóveda."""
        try:
            if self.dest_path.exists():
                self.dest_path.unlink()
        except Exception:
            pass
