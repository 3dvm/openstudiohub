# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/vault_manifest_repository.py
# Architectural role: Infrastructure / File-backed VaultManifestRepository
# =========================================================================================

"""File-backed ``VaultManifestRepository`` (single canonical schema/location)."""

import json
from pathlib import Path

from src.application.ports import VaultManifestRepository
from src.domain.vault.manifest import VaultManifest, needs_migration


class FileVaultManifestRepository(VaultManifestRepository):
    def __init__(self, vault_root: Path = None, config_factory=None) -> None:
        self._vault_root = Path(vault_root) if vault_root else None
        self._config_factory = config_factory

    @property
    def vault_root(self) -> Path:
        if self._config_factory is not None:
            return self._config_factory.get_vault_path()
        return self._vault_root

    def path(self) -> Path:
        return self.vault_root / "vault_manifest.json"

    def load(self) -> VaultManifest:
        if not self.path().exists():
            return VaultManifest()
        try:
            with open(self.path(), "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except Exception as error:  # noqa: BLE001 - corrupt manifest -> empty
            print(f"[VAULT MANIFEST] Failed to parse {self.path()}: {error}")
            return VaultManifest()

        manifest = VaultManifest.from_dict(raw)
        if needs_migration(raw):
            # Legacy schema detected: rewrite it canonical so the fix persists.
            self.save(manifest)
        return manifest

    def save(self, manifest: VaultManifest) -> bool:
        try:
            self.path().parent.mkdir(parents=True, exist_ok=True)
            with open(self.path(), "w", encoding="utf-8") as handle:
                json.dump(manifest.to_dict(), handle, indent=4, ensure_ascii=False)
            return True
        except Exception as error:  # noqa: BLE001
            print(f"[VAULT MANIFEST] Failed to write {self.path()}: {error}")
            return False
