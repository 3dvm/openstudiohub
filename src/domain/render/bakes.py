# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/render/bakes.py
# Architectural role: Render domain / remote bake policy
# =========================================================================================

"""Policy shared by the panel, workers and the Vast offer search."""

from __future__ import annotations

DEFAULT_GN_BAKE_MIN_CPU_RAM_GB = 60.0


def bake_geometry_nodes_effective(settings, shots) -> bool:
    """Resolve the tri-state node-bake setting for a set of shots."""
    configured = getattr(settings, "bake_geometry_nodes", None)
    if configured is not None:
        return bool(configured)
    for shot in shots or ():
        for bake in getattr(shot, "geometry_bakes", ()) or ():
            if not getattr(bake, "local_cache", False) or getattr(
                bake, "cache_stale", False
            ):
                return True
    return False


def min_cpu_ram_gb_effective(settings, shots) -> float:
    """Return the host RAM floor, auto-raising it for node-side GN bakes."""
    configured = float(getattr(settings, "min_cpu_ram_gb", 0.0) or 0.0)
    if configured > 0:
        return configured
    targets = list(shots or ())
    if (
        bake_geometry_nodes_effective(settings, targets)
        and any(getattr(shot, "geometry_bakes", ()) for shot in targets)
    ):
        return DEFAULT_GN_BAKE_MIN_CPU_RAM_GB
    return 0.0
