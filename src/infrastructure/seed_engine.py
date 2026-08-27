# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/seed_engine.py
# Architectural role: Infrastructure / Studio Seed codec
# =========================================================================================

"""Studio Seed (``.seed``) file engine.

Extracted from ``ConfigFactory`` so the configuration object no longer owns the
seed codec.

.. warning::
    The ``.seed`` format is **obfuscation** (JSON -> zlib -> base64), NOT
    encryption. It deters casual inspection but does not protect secrets at
    rest. A key-based encryption scheme is a future hardening item.
"""

import base64
import json
import re
import zlib
from pathlib import Path


class StudioSeedService:
    def __init__(self, config_factory) -> None:
        self.config_factory = config_factory

    def export_seed(self, payload: dict, destino_dir: Path) -> tuple[bool, str]:
        try:
            studio_name = (payload.get("studio_profile") or {}).get("name", "").strip() or "openstudio"
            safe_name = "".join(c if c.isalnum() else "_" for c in studio_name).lower()
            safe_name = re.sub(r"_+", "_", safe_name).strip("_")
            seed_path = destino_dir / f"{safe_name}.seed"

            json_str = json.dumps(payload)
            compressed = zlib.compress(json_str.encode("utf-8"))
            encoded = base64.b64encode(compressed).decode("utf-8")

            with open(seed_path, "w", encoding="utf-8") as handle:
                handle.write(encoded)
            return True, str(seed_path)
        except Exception as error:  # noqa: BLE001
            msg = f"Failed to export seed: {error}"
            print(f"[SEED ENGINE ERROR] {msg}")
            return False, msg

    def import_seed(self, seed_path: Path) -> bool:
        try:
            if not seed_path.exists():
                return False
            with open(seed_path, "r", encoding="utf-8") as handle:
                encoded = handle.read()

            compressed = base64.b64decode(encoded)
            payload = json.loads(zlib.decompress(compressed).decode("utf-8"))
            return self.config_factory.guardar_configuracion(payload, from_seed=True)
        except Exception as error:  # noqa: BLE001
            print(f"[SEED ENGINE ERROR] Integrity failure during seed import: {error}")
            return False
