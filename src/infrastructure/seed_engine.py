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
import copy
import json
import re
import zlib
from pathlib import Path

# SSH fields that are always machine-specific and must never travel in a seed.
_MACHINE_SSH_FIELDS = ("ssh_key_path", "ssh_cert_path", "known_hosts_path")


class StudioSeedService:
    def __init__(self, config_factory) -> None:
        self.config_factory = config_factory

    @staticmethod
    def sanitize_payload(payload: dict) -> dict:
        """Return a copy safe to distribute: no machine-specific paths.

        Drops the absolute vault override (the portable ``vault_dir`` is kept)
        and blanks the per-machine SSH key/cert/known_hosts paths.
        """
        clean = copy.deepcopy(payload or {})

        infra = clean.get("infrastructure_topology")
        if isinstance(infra, dict):
            infra.pop("vault_path", None)
            legacy = infra.get("vcs_server")
            if isinstance(legacy, dict):
                StudioSeedService._scrub_ssh(legacy.get("remote"))

        servers = clean.get("vcs_engine", {}).get("servers")
        if isinstance(servers, list):
            for server in servers:
                if isinstance(server, dict):
                    StudioSeedService._scrub_ssh((server.get("profile") or {}).get("remote"))

        return clean

    @staticmethod
    def _scrub_ssh(remote) -> None:
        if isinstance(remote, dict):
            for field_name in _MACHINE_SSH_FIELDS:
                if field_name in remote:
                    remote[field_name] = ""

    def export_seed(self, payload: dict, destino_dir: Path) -> tuple[bool, str]:
        try:
            payload = self.sanitize_payload(payload)
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
            return self.config_factory.save_configuration(
                self.sanitize_payload(payload), from_seed=True
            )
        except Exception as error:  # noqa: BLE001
            print(f"[SEED ENGINE ERROR] Integrity failure during seed import: {error}")
            return False
