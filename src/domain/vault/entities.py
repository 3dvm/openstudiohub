# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/vault/entities.py
# Architectural role: Vault entities (Addon, Template, BlenderVersion)
# =========================================================================================

"""Vault entities (software inventory)."""

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class Addon:
    name: str
    version: str = ""
    description: str = ""
    mandatory: bool = False
    requires: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Template:
    name: str
    version: str = ""
    description: str = ""
    mandatory: bool = False
    requires: Tuple[str, ...] = ()


@dataclass(frozen=True)
class BlenderVersion:
    version: str
    addons: Tuple[Addon, ...] = field(default_factory=tuple)
    templates: Tuple[Template, ...] = field(default_factory=tuple)
