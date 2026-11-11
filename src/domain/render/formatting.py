# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/render/formatting.py
# Architectural role: Render domain / shared byte formatting
# =========================================================================================

"""Byte-size formatting shared by the render infrastructure and the UI."""

from __future__ import annotations

import math

_UNITS = (
    (1_000_000_000_000.0, "TB"),
    (1_000_000_000.0, "GB"),
    (1_000_000.0, "MB"),
    (1_000.0, "KB"),
)


def format_bytes(value, *, placeholder: str = "--") -> str:
    """Return a compact decimal size such as ``512 B``, ``31.5 MB`` or ``36.9 GB``."""
    try:
        size = float(value)
    except (TypeError, ValueError):
        return placeholder
    if not math.isfinite(size) or size < 0:
        return placeholder
    for threshold, label in _UNITS:
        if size >= threshold:
            return f"{size / threshold:.1f} {label}"
    return f"{int(size)} B"
