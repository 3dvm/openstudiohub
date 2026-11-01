# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/services/task_file_resolver.py
# Architectural role: Application service / task file resolution
# =========================================================================================

"""Resolve the physical ``.blend`` file backing a Kitsu task.

The canonical link lives in the task custom data (``data.filepath``). Older
tasks may not have a link, and some studio files use slightly different casing
or version suffixes than the naming policy predicts. This resolver keeps the
linked path when it exists and otherwise searches the expected entity folder
for the best matching file. It never returns a path that does not exist.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from src.domain.path_resolver import PathResolver
from src.domain.production.naming import NamingPolicy
from src.domain.production.value_objects import EntityType

_VERSION_RE = re.compile(r"[-_]v(\d+)$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[-_.\s]+")


@dataclass(frozen=True)
class ResolvedTaskFile:
    relative_path: str
    absolute_path: Path


class TaskFileResolver:
    def __init__(self, config_factory=None) -> None:
        self.config_factory = config_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def resolve(
        self,
        project_root: Path,
        task_data: dict,
        production_folder: str = "",
    ) -> Optional[ResolvedTaskFile]:
        if not project_root:
            return None
        workspace = self.workspace_root(project_root, production_folder)
        if not workspace.exists():
            return None

        for linked in self._linked_paths(task_data):
            path = self._existing_path(workspace, linked)
            if path is not None:
                return self._result(path, workspace)

        expected = self._expected_path(task_data)
        if expected:
            path = self._existing_path(workspace, expected)
            if path is not None:
                newest = self._scan_directory(path.parent, task_data)
                return self._result(newest or path, workspace)

        found = self._scan_scope(workspace, task_data)
        if found is not None:
            return self._result(found, workspace)
        return None

    def workspace_root(self, project_root: Path, production_folder: str = "") -> Path:
        folder = production_folder
        if not folder:
            getter = getattr(self.config_factory, "get_vfs_svn_name", None)
            folder = getter() if callable(getter) else "svn"
        return Path(project_root) / folder

    # ------------------------------------------------------------------
    # Candidates
    # ------------------------------------------------------------------
    @staticmethod
    def _linked_paths(task_data: dict) -> Iterable[str]:
        data = task_data.get("data") or {}
        if isinstance(data, dict) and data.get("filepath"):
            yield str(data["filepath"])
        if task_data.get("filepath"):
            yield str(task_data["filepath"])

    @staticmethod
    def _expected_path(task_data: dict) -> str:
        try:
            return str(PathResolver().resolve(task_data) or "")
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------
    # Case-insensitive path helpers
    # ------------------------------------------------------------------
    def _existing_path(self, workspace: Path, relative_or_absolute: str) -> Optional[Path]:
        raw = Path(relative_or_absolute)
        candidates = [workspace / raw] if not raw.is_absolute() else [raw]
        if not raw.is_absolute():
            # Some blueprints store the path including the VCS root folder.
            candidates.append(workspace.parent / raw)
        for candidate in candidates:
            if candidate.is_file():
                return candidate

        if not raw.is_absolute():
            resolved = self._resolve_parts(workspace, raw)
            if resolved is not None and resolved.is_file():
                return resolved
        return None

    def _resolve_parts(self, base: Path, relative: Path) -> Optional[Path]:
        current = base
        for part in relative.parts:
            if part in ("", "."):
                continue
            candidate = current / part
            if candidate.exists():
                current = candidate
                continue
            if not current.is_dir():
                return None
            lowered = part.lower()
            match = next(
                (entry for entry in current.iterdir() if entry.name.lower() == lowered),
                None,
            )
            if match is None:
                return None
            current = match
        return current

    # ------------------------------------------------------------------
    # Folder scan fallback
    # ------------------------------------------------------------------
    def _scan_scope(self, workspace: Path, task_data: dict) -> Optional[Path]:
        entity_type = EntityType.from_raw(
            task_data.get("entity_type_name", task_data.get("entity_type", ""))
        )
        if entity_type == EntityType.SHOT:
            sequence = task_data.get("sequence_name", "")
            if not sequence:
                return None
            scope = self._resolve_parts(
                workspace, Path("pro") / "shots" / NamingPolicy.slug(sequence)
            )
        elif entity_type == EntityType.ASSET:
            asset_type = task_data.get("asset_type_name") or "props"
            scope = self._resolve_parts(
                workspace, Path("pro") / "assets" / NamingPolicy.slug(asset_type)
            )
        else:
            expected = self._expected_path(task_data)
            scope = self._resolve_parts(workspace, Path(expected).parent) if expected else None

        if scope is None or not scope.is_dir():
            return None

        return self._scan_directory(scope, task_data, recursive=True)

    def _scan_directory(
        self, directory: Path, task_data: dict, recursive: bool = False
    ) -> Optional[Path]:
        if directory is None or not directory.is_dir():
            return None
        paths = directory.rglob("*.blend") if recursive else directory.glob("*.blend")
        matches = [
            path
            for path in paths
            if path.is_file() and self._matches(path, task_data)
        ]
        if not matches:
            return None
        return max(matches, key=self._rank)

    def _matches(self, path: Path, task_data: dict) -> bool:
        tokens = [token for token in _TOKEN_RE.split(path.stem.lower()) if token]
        task_aliases = self._aliases(
            task_data.get("task_type_short_name"),
            task_data.get("task_type_name"),
        )
        entity_aliases = self._aliases(
            task_data.get("entity_name"),
            task_data.get("name"),
        )
        task_match = (
            True
            if not task_aliases
            else any(self._token_matches(token, task_aliases) for token in tokens)
        )
        if not task_match:
            return False
        if not entity_aliases:
            return True
        return any(self._token_matches(token, entity_aliases) for token in tokens)

    @staticmethod
    def _aliases(*values: object) -> set[str]:
        aliases: set[str] = set()
        for value in values:
            normalized = NamingPolicy.slug(str(value or ""))
            if not normalized:
                continue
            aliases.add(normalized)
            aliases.update(token for token in _TOKEN_RE.split(normalized) if len(token) >= 3)
        return aliases

    @staticmethod
    def _token_matches(token: str, aliases: set[str]) -> bool:
        for alias in aliases:
            if token == alias:
                return True
            if len(alias) >= 3 and (token.startswith(alias) or alias.startswith(token)):
                return True
        return False

    @staticmethod
    def _rank(path: Path) -> tuple[int, float]:
        match = _VERSION_RE.search(path.stem)
        version = int(match.group(1)) if match else 0
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        return (version, modified)

    @staticmethod
    def _result(path: Path, workspace: Path) -> ResolvedTaskFile:
        try:
            relative = path.relative_to(workspace).as_posix()
        except ValueError:
            relative = path.as_posix()
        return ResolvedTaskFile(relative_path=relative, absolute_path=path)
