# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/vault_manifest_repository.py
# Architectural role: Infrastructure / File-backed VaultManifestRepository
# =========================================================================================

"""File-backed ``VaultManifestRepository`` (single canonical schema/location)."""

import json
from pathlib import Path

from src.application.ports import VaultManifestRepository
from src.domain.vault.manifest import VaultManifest


class FileVaultManifestRepository(VaultManifestRepository):
    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root

    def path(self) -> Path:
        return self.vault_root / "vault_manifest.json"

    def load(self) -> VaultManifest:
        if not self.path().exists():
            return VaultManifest()
        try:
            with open(self.path(), "r", encoding="utf-8") as handle:
                return VaultManifest.from_dict(json.load(handle))
        except Exception as error:  # noqa: BLE001 - corrupt manifest -> empty
            print(f"[VAULT MANIFEST] Failed to parse {self.path()}: {error}")
            return VaultManifest()

    def save(self, manifest: VaultManifest) -> bool:
        try:
            self.path().parent.mkdir(parents=True, exist_ok=True)
            with open(self.path(), "w", encoding="utf-8") as handle:
                json.dump(manifest.to_dict(), handle, indent=4, ensure_ascii=False)
            return True
        except Exception as error:  # noqa: BLE001
            print(f"[VAULT MANIFEST] Failed to write {self.path()}: {error}")
            return False
