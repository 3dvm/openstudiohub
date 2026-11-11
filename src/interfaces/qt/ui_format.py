# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/ui_format.py
# Architectural role: UI consistency / user-facing duration formatting
# =========================================================================================

"""Adaptive duration formatting shared by every user-facing time display."""

from __future__ import annotations

import math

from src.domain.render.formatting import format_bytes

__all__ = ["format_bytes", "format_duration", "format_rate"]

_DAY = 86400.0
_WEEK = 7.0 * _DAY
_MONTH = 30.0 * _DAY
_YEAR = 365.0 * _DAY


def _total_seconds(seconds) -> int | None:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    if value == 0:
        return 0
    return max(1, int(round(value)))


def format_duration(
    seconds,
    *,
    placeholder: str = "--",
    max_units: int = 3,
) -> str:
    """Return an adaptive duration such as ``45s``, ``3m 20s`` or ``1w 2d``.

    The scale is picked from the total duration: seconds, minutes, hours, days,
    weeks (> 7 days), months (>= 30 days) and years (>= 365 days). Up to
    ``max_units`` non-zero units are shown.
    """
    total = _total_seconds(seconds)
    if total is None:
        return placeholder
    if total < 60:
        return f"{total}s"

    if total >= _YEAR:
        units = ((_YEAR, "y"), (_MONTH, "mo"), (_DAY, "d"))
    elif total >= _MONTH:
        units = ((_MONTH, "mo"), (_WEEK, "w"), (_DAY, "d"))
    elif total > _WEEK:
        units = ((_WEEK, "w"), (_DAY, "d"), (3600.0, "h"))
    elif total >= _DAY:
        units = ((_DAY, "d"), (3600.0, "h"), (60.0, "m"))
    elif total >= 3600:
        units = ((3600.0, "h"), (60.0, "m"), (1.0, "s"))
    else:
        units = ((60.0, "m"), (1.0, "s"))

    limit = max(1, int(max_units))
    parts: list[str] = []
    remaining = total
    for seconds_per_unit, label in units[:limit]:
        value = int(remaining // seconds_per_unit)
        remaining %= int(seconds_per_unit)
        if value:
            parts.append(f"{value}{label}")
    return " ".join(parts) or f"{total}s"


def format_rate(seconds, *, placeholder: str = "--") -> str:
    """Return a per-frame rate, preserving decimals below one minute."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return placeholder
    if not math.isfinite(value) or value < 0:
        return placeholder
    if value < 0.1:
        return "<0.1s"
    if value < 59.95:
        return f"{value:.1f}s"
    return format_duration(value, placeholder=placeholder)
