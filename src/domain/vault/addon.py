# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/vault/addon.py
# Architectural role: Vault domain / add-on metadata parsing
# =========================================================================================

"""Unified Blender add-on metadata parser.

Consolidates the two previously divergent parsers (``AddonParser`` and
``AddonInspector``). Supports both the modern ``blender_manifest.toml``
(Blender 4.2+ extensions) and the legacy ``bl_info`` dict in ``__init__.py``.
Parsing is done with regex (no execution of untrusted code).
"""

import re
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class AddonMetadata:
    name: str = "unknown_addon"
    version: str = "1.0.0"
    min_blender_version: str = "0.0.0"
    description: str = ""
    type: str = "unknown"  # "manifest" | "legacy" | "unknown"
    is_valid: bool = False


def _first(content: str, pattern: str) -> str:
    match = re.search(pattern, content)
    return match.group(1) if match else ""


def _tuple_to_str(parts) -> str:
    return ".".join(str(p) for p in parts) if parts else ""


def _version_tuple(content: str, key: str) -> str:
    match = re.search(rf'"{key}"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)', content)
    if not match:
        return ""
    return _tuple_to_str([p for p in match.groups() if p is not None])


def parse_toml(content: str) -> AddonMetadata:
    # Prefer the extension "id" (canonical, e.g. "blender_kitsu") over "name".
    name = _first(content, r'id\s*=\s*"([^"]+)"') or _first(content, r'name\s*=\s*"([^"]+)"') or "unknown_addon"
    version = _first(content, r'version\s*=\s*"([^"]+)"') or "1.0.0"
    blender_min = _first(content, r'blender_version_min\s*=\s*"([^"]+)"') or "4.2.0"
    description = _first(content, r'description\s*=\s*"([^"]+)"')
    return AddonMetadata(
        name=name,
        version=version,
        min_blender_version=blender_min,
        description=description,
        type="manifest",
        is_valid=bool(name != "unknown_addon"),
    )


def parse_legacy_bl_info(content: str) -> AddonMetadata:
    bl_info_match = re.search(r'bl_info\s*=\s*\{([^}]+)\}', content, re.DOTALL)
    if not bl_info_match:
        return AddonMetadata(type="legacy", is_valid=False)

    body = bl_info_match.group(1)
    name = _first(body, r'"name"\s*:\s*["\']([^"\']+)["\']') or "unknown_addon"
    version = _version_tuple(body, "version") or "1.0.0"
    blender_min = _version_tuple(body, "blender") or "2.80.0"
    description = _first(body, r'"description"\s*:\s*"([^"]+)"')
    return AddonMetadata(
        name=name,
        version=version,
        min_blender_version=blender_min,
        description=description,
        type="legacy",
        is_valid=True,
    )


def parse_zip(zip_path: Path) -> AddonMetadata:
    if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
        return AddonMetadata()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()

            tomls = sorted((f for f in names if f.endswith("blender_manifest.toml")), key=lambda x: x.count("/"))
            if tomls:
                return parse_toml(zf.read(tomls[0]).decode("utf-8", errors="ignore"))

            inits = sorted((f for f in names if f.endswith("__init__.py")), key=lambda x: x.count("/"))
            for init in inits:
                content = zf.read(init).decode("utf-8", errors="ignore")
                if "bl_info" in content:
                    meta = parse_legacy_bl_info(content)
                    if meta.name == "unknown_addon":
                        meta = replace(meta, name=Path(init).parent.name or "unknown_addon")
                    return meta
    except Exception:  # noqa: BLE001 - malformed zip -> unknown addon
        pass
    return AddonMetadata()


def parse_directory(dir_path: Path) -> AddonMetadata:
    toml_path = dir_path / "blender_manifest.toml"
    if toml_path.exists():
        return parse_toml(toml_path.read_text(encoding="utf-8", errors="ignore"))

    init_path = dir_path / "__init__.py"
    if init_path.exists():
        content = init_path.read_text(encoding="utf-8", errors="ignore")
        if "bl_info" in content:
            meta = parse_legacy_bl_info(content)
            if meta.name == "unknown_addon":
                meta = replace(meta, name=dir_path.name)
            return meta
    return AddonMetadata()
