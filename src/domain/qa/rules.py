# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/qa/rules.py
# Architectural role: QA domain rules (pure, Blender-agnostic)
# =========================================================================================

"""Scene-sanity (Gatekeeper) rules.

Pure, framework-free rules extracted from the Blender addon so they can be
shared and unit-tested without Blender. The addon's ``gatekeeper.py`` gathers
``bpy`` state and delegates to these predicates.
"""

import math
import os
from typing import Iterable

FORBIDDEN_PRIMITIVES = frozenset({
    "Cube", "Sphere", "Cylinder", "Cone", "Torus", "Plane", "Monkey", "Suzanne", "Circle",
    "BézierCurve", "BezierCurve", "GPencil", "Grid", "Icosphere", "Mball", "NurbsCurve", "NurbsPath",
    "Armature",
})

AUDITABLE_OBJECT_TYPES = frozenset({
    "MESH", "CURVE", "SURFACE", "META", "FONT", "ARMATURE", "GPENCIL", "GREASEPENCIL",
})

DEFAULT_TOLERANCE = 1e-4


def _close(a: Iterable[float], b: Iterable[float], tolerance: float) -> bool:
    return all(math.isclose(x, y, abs_tol=tolerance) for x, y in zip(a, b))


def is_dirty_transform(location, rotation_euler, scale, tolerance: float = DEFAULT_TOLERANCE) -> bool:
    """True if location/rotation/scale are not at their default (identity) values."""
    return (
        not _close(location, (0.0, 0.0, 0.0), tolerance)
        or not _close(rotation_euler, (0.0, 0.0, 0.0), tolerance)
        or not _close(scale, (1.0, 1.0, 1.0), tolerance)
    )


def asset_name_from_filename(filename: str) -> str:
    """Derive the asset name from a ``<asset>-<task>.blend`` style filename."""
    base = os.path.basename(filename or "") or "Asset"
    return "-".join(base.split("-")[:-1]) if "-" in base else "Asset"


def is_forbidden_name(name: str, forbidden=FORBIDDEN_PRIMITIVES) -> bool:
    """True if the object's base name is a forbidden Blender primitive."""
    return name.split(".")[0] in forbidden


def is_valid_object_name(name: str, asset_name: str, forbidden=FORBIDDEN_PRIMITIVES) -> bool:
    """True if the name is not a primitive and follows the ``<asset>-`` prefix rule."""
    if is_forbidden_name(name, forbidden):
        return False
    return name.startswith(f"{asset_name}-")


def is_out_of_bounds(path: str, project_root: str) -> bool:
    """True if ``path`` resolves outside the project root."""
    root = os.path.normpath(project_root or "")
    return not os.path.normpath(path or "").startswith(root)
