# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/production_manager.py
# Architectural role: Production orchestrator (PM batch entity genesis)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. All rights reserved.
# License: GNU General Public License v3.0 (GPLv3)
# =========================================================================================

"""Production Manager orchestrator.

Fetches entities proposed by Editorial and batch-spawns production tasks and
physical master .blend files. Path rules come from the ``NamingPolicy`` domain
service (single source of truth), and typed reads/writes go through the
``ProductionRepository``.

NOTE: ``get_pending_entities`` / ``get_or_create_storyboard_task_type`` /
``create_sequence_with_task`` still use ``self.kitsu`` directly because their
callers consume raw Kitsu dicts (e.g. ``raw_data``); they will be migrated to
the repository in the Phase 6 UI decoupling.
"""

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.application.bus import MessageBus
from src.domain.production.events import FilePathMapped, TaskForged
from src.domain.production.naming import NamingPolicy
from src.infrastructure.kitsu.production_repository import KitsuProductionRepository
from src.infrastructure.kitsu_manager import KitsuManager


class ProductionManager:
    def __init__(self, auth_manager, config_factory, bus: Optional[MessageBus] = None) -> None:
        self.auth_manager = auth_manager
        self.config_factory = config_factory
        self.kitsu = KitsuManager()
        self.repository = KitsuProductionRepository(self.kitsu)
        self.bus = bus or MessageBus()

        try:
            self.vault_root = self.config_factory.get_workspace_root() / "openstudio_vault"
        except Exception:
            self.vault_root = Path.home() / "openstudio_vault"

        self.vault_templates_dir = self.vault_root / "project_templates"

    def get_pending_entities(self, project_id: str) -> List[Dict[str, Any]]:
        """Shots and Assets awaiting PM validation (returns raw-dict projections)."""
        pending_list = []
        try:
            valid_statuses = ["Todo", "Ready To Start"]

            shots = self.kitsu.all_shots_for_project(project_id)
            for shot in shots:
                status = shot.get("status", "Todo")
                if status in valid_statuses:
                    seq = self.kitsu.get_sequence(shot.get("sequence_id"))
                    pending_list.append({
                        "id": shot["id"],
                        "name": shot["name"],
                        "type": "Shot",
                        "parent": seq["name"] if seq else "Unknown",
                        "frame_in": shot.get("nb_frames", 0),
                        "status": status,
                        "raw_data": shot,
                    })

            assets = self.kitsu.all_assets_for_project(project_id)
            for asset in assets:
                status = asset.get("status", "Todo")
                if status == "Todo":
                    asset_type_id = asset.get("entity_type_id", "")
                    asset_type = self.kitsu.get_asset_type(asset.get("entity_type_id"))
                    pending_list.append({
                        "id": asset["id"],
                        "name": asset["name"],
                        "Parent": asset.get("parent"),
                        "type": asset_type["name"] if asset_type else "Unknown",
                        "asset_type_id": asset_type_id,
                        "frame_in": 0,
                        "status": status,
                        "raw_data": asset,
                    })

        except Exception as e:
            print(f"[PRODUCTION MANAGER] Gazu API Error fetching entities: {e}")

        return pending_list

    def map_file_to_task(self, entity_dict: dict, task_type_name: str, relative_path: str) -> bool:
        """Inject the generated .blend path into the entity's Kitsu metadata."""
        try:
            entity_data = entity_dict.get("data") or {}
            entity_data["blend_file_path"] = relative_path
            ok = self.repository.update_entity_data(entity_dict["id"], entity_data)
            if ok:
                self.bus.publish(FilePathMapped(entity_id=entity_dict["id"], file_path=relative_path))
            return ok
        except Exception as e:
            print(f"[PRODUCTION MANAGER] Error mapping file to Kitsu: {e}")
            return False

    def batch_create_entity_files(self, project_name: str, entities: List[Dict[str, Any]],
                                  base_template: str, task_types: List[str], status_callback) -> Tuple[bool, str]:
        """Spawn tasks in Kitsu and physical master .blend files in the VCS workspace."""
        if not entities:
            return False, "No entities provided for batch creation."

        try:
            project_root = self.config_factory.get_workspace_root() / project_name
            vfs_svn = self.config_factory.get_vfs_svn_name()
            vcs_root = project_root / vfs_svn
        except Exception as e:
            return False, f"Failed to resolve NAS topography: {e}"

        template_path = self.vault_templates_dir / base_template
        if not template_path.exists() or not template_path.is_file():
            return False, f"Master template '{base_template}' not found in Vault."

        success_count = 0
        error_count = 0

        for idx, entity in enumerate(entities):
            e_name = entity.get("name", "unknown").lower().replace(" ", "_")
            e_type = entity.get("type", "Shot")
            e_parent = entity.get("parent", "unknown").lower().replace(" ", "_")
            e_id = entity.get("id")

            status_callback(f"Processing {e_type}: {e_name} ({idx + 1}/{len(entities)})...", "yellow")

            # Path generation via NamingPolicy (single source of truth).
            if e_type == "Shot":
                entity_dir = vcs_root / NamingPolicy.shot_dir(e_parent, e_name)
            else:
                entity_dir = vcs_root / NamingPolicy.asset_dir(e_parent, e_name)

            try:
                entity_dir.mkdir(parents=True, exist_ok=True)

                for task_name in task_types:
                    forged = None
                    try:
                        forged = self.repository.create_task(e_id, task_name)
                    except Exception as api_e:
                        print(f"[PRODUCTION MANAGER] Task {task_name} already exists or API error: {api_e}")

                    safe_task_name = task_name.lower().replace(" ", "")
                    blend_filename = f"{e_name}-{safe_task_name}.blend"
                    dest_blend_path = entity_dir / blend_filename

                    if not dest_blend_path.exists():
                        shutil.copy2(template_path, dest_blend_path)

                    if forged is not None:
                        self.bus.publish(
                            TaskForged(task_id=forged.id, entity_id=e_id, file_path=str(dest_blend_path))
                        )

                success_count += 1

            except Exception as io_error:
                print(f"[PRODUCTION MANAGER] File System error on {e_name}: {io_error}")
                error_count += 1

        status_callback(
            f"Batch completed: {success_count} created, {error_count} failed.",
            "green" if error_count == 0 else "yellow",
        )
        return True, f"Successfully processed {success_count} entities."

    def get_or_create_storyboard_task_type(self, project_id: str) -> dict:
        """Return (or create) the 'Storyboard' task type for Sequence entities.

        Kept on ``self.kitsu`` because its raw dict result is passed straight into
        gazu write calls by the UI spawning workers.
        """
        task_types = self.kitsu.all_task_types()
        storyboard_tt = next(
            (tt for tt in task_types if tt["name"].lower() == "storyboard" and tt["for_entity"].lower() == "sequence"),
            None,
        )

        if not storyboard_tt:
            storyboard_tt = self.kitsu.new_task_type(name="StoryboardSeq", color="#F97316", for_entity="Sequence")

        return storyboard_tt

    def create_sequence_with_task(self, project_id: str, sequence_name: str, task_type_id: str) -> dict:
        """Create a Sequence and attach its initial Storyboard task."""
        project = self.kitsu.get_project(project_id)
        sequence = self.kitsu.new_sequence(project, name=sequence_name)

        default_status = self.kitsu.get_default_task_status()
        self.kitsu.new_task(entity=sequence, task_type=task_type_id, name="main", task_status=default_status)
        return sequence

    def register_storyboard_sequence(self, project_id: str, sequence_name: str, storyboard_tt_id: str, vfs_svn: str) -> Optional[dict]:
        """Get-or-create a sequence + storyboard task and map its file path in Kitsu.

        Extracted from the StoryboardBatchWorker so the UI worker no longer
        writes to Kitsu directly.
        """
        try:
            sequence = self.kitsu.get_sequence_by_name(project_id, sequence_name)
            if not sequence:
                sequence = self.create_sequence_with_task(project_id, sequence_name, storyboard_tt_id)
        except Exception as error:  # noqa: BLE001
            print(f"[ProductionManager] Error registering sequence {sequence_name}: {error}")
            return None

        rel_path = f"{vfs_svn}/edit/storyboards/{sequence_name.lower()}-storyboard.blend"

        try:
            storyboard_tt = self.get_or_create_storyboard_task_type(project_id)
            task = self.kitsu.get_task_by_entity(sequence, storyboard_tt)
            if task is None:
                default_status = self.kitsu.get_default_task_status()
                task = self.kitsu.new_task(sequence, storyboard_tt, name="main", task_status=default_status)

            seq_data = sequence.get("data") or {}
            seq_data["blend_file_path"] = rel_path
            self.kitsu.update_sequence_data(sequence["id"], seq_data)

            software = self.kitsu.get_software_by_name("Blender")
            if software and task:
                self.kitsu.new_working_file(task, software, name=rel_path)
        except Exception as error:  # noqa: BLE001
            print(f"[ProductionManager] Error mapping storyboard file for {sequence_name}: {error}")

        return sequence
