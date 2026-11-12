# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/render/offers.py
# Architectural role: Render domain / marketplace offer diagnostics
# =========================================================================================

"""Framework-free models for explaining why no render offer was selected.

The marketplace adapters turn their raw rows into :class:`OfferSnapshot` values
and use :func:`build_diagnostics` to produce exact per-constraint failures,
nearby offers and minimal limit relaxations. The UI can then show what failed
instead of a generic "no offer" message.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

_US_MARKERS = (
    "UNITED STATES",
    "AMERICA",
    "CANADA",
    "MEXICO",
    "BRAZIL",
    "ARGENTINA",
    "CHILE",
    "COLOMBIA",
    "PERU",
    "URUGUAY",
    "PARAGUAY",
    "BOLIVIA",
    "ECUADOR",
    "VENEZUELA",
)


def is_us_geolocation(geolocation: str) -> bool:
    """Return True for an Americas location used by the region preference."""
    text = (geolocation or "").upper()
    if re.search(r"\b(?:US|USA|CA)\b", text):
        return True
    return any(marker in text for marker in _US_MARKERS)


@dataclass(frozen=True)
class OfferSnapshot:
    """Marketplace-independent view of one rentable offer."""

    offer_id: int
    gpu_name: str
    gpu_ram_gb: float
    cpu_ram_gb: float
    disk_space_gb: float
    cuda_version: str
    reliability: float
    price_per_hour: float
    inet_down_mbps: float
    inet_up_mbps: float
    geolocation: str
    gpu_profile: str = ""
    gpu_label: str = ""


@dataclass(frozen=True)
class OfferLimits:
    """The limits applied to one offer search."""

    gpu_profile: str
    gpu_label: str
    min_gpu_ram_gb: float
    max_price_per_hour: float = 0.0
    min_reliability: float = 0.95
    min_cpu_ram_gb: float = 0.0
    min_inet_down_mbps: float = 0.0
    min_inet_up_mbps: float = 0.0
    preferred_region: str = "prefer_americas"
    us_only: bool = False
    min_disk_gb: int = 40
    min_cuda: str = "12.8"


@dataclass(frozen=True)
class OfferMiss:
    """One failed requirement for one offer."""

    field: str
    label: str
    actual_text: str
    required_text: str
    relation: str
    gap: float = 0.0

    @property
    def summary(self) -> str:
        return (
            f"{self.label}: {self.actual_text} "
            f"({self.relation} {self.required_text})"
        )


@dataclass(frozen=True)
class OfferSuggestion:
    """A single limit change that would make at least one offer valid."""

    field: str
    value: object
    label: str
    reason: str
    offer_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class OfferCandidateReport:
    """One offer plus every requirement it failed."""

    offer: OfferSnapshot
    misses: tuple[OfferMiss, ...]

    @property
    def passing(self) -> bool:
        return not self.misses

    @property
    def score(self) -> tuple[int, float]:
        return (len(self.misses), sum(miss.gap for miss in self.misses))

    @property
    def failure_text(self) -> str:
        return ", ".join(miss.summary for miss in self.misses)


@dataclass(frozen=True)
class OfferAlternative:
    """A valid offer found in a different GPU profile."""

    gpu_profile: str
    gpu_label: str
    offer: OfferSnapshot


@dataclass(frozen=True)
class OfferDiagnostics:
    """Everything the UI needs to explain and recover from a blocked search."""

    limits: OfferLimits
    candidates: tuple[OfferCandidateReport, ...] = ()
    near_offers: tuple[OfferCandidateReport, ...] = ()
    suggestions: tuple[OfferSuggestion, ...] = ()
    query: str = ""

    @property
    def gpu_profile(self) -> str:
        return self.limits.gpu_profile

    @property
    def gpu_label(self) -> str:
        return self.limits.gpu_label

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def message(self) -> str:
        if not self.candidates:
            return (
                f"No rentable {self.limits.gpu_label} offer matched the base "
                "search (GPU model, disk and CUDA version)."
            )
        return f"No {self.limits.gpu_label} offer meets all the current limits."


def evaluate_offer(
    offer: OfferSnapshot,
    limits: OfferLimits,
) -> tuple[OfferMiss, ...]:
    """Return every limit the offer fails, in a stable display order."""
    misses: list[OfferMiss] = []

    if offer.gpu_ram_gb < limits.min_gpu_ram_gb:
        misses.append(
            OfferMiss(
                field="gpu_ram_gb",
                label="GPU VRAM",
                actual_text=f"{offer.gpu_ram_gb:.1f} GB",
                required_text=f"{limits.min_gpu_ram_gb:.0f} GB",
                relation="<",
                gap=max(
                    0.0,
                    (limits.min_gpu_ram_gb - offer.gpu_ram_gb)
                    / max(1.0, limits.min_gpu_ram_gb),
                ),
            )
        )
    if offer.reliability < limits.min_reliability:
        misses.append(
            OfferMiss(
                field="min_reliability",
                label="Reliability",
                actual_text=f"{offer.reliability:.3f}",
                required_text=f"{limits.min_reliability:.2f}",
                relation="<",
                gap=max(0.0, limits.min_reliability - offer.reliability),
            )
        )
    if limits.max_price_per_hour > 0 and offer.price_per_hour > limits.max_price_per_hour:
        misses.append(
            OfferMiss(
                field="max_price_per_hour",
                label="Price",
                actual_text=f"${offer.price_per_hour:.3f}/h",
                required_text=f"${limits.max_price_per_hour:.3f}/h",
                relation=">",
                gap=max(
                    0.0,
                    (offer.price_per_hour - limits.max_price_per_hour)
                    / max(0.01, limits.max_price_per_hour),
                ),
            )
        )
    if limits.min_cpu_ram_gb > 0 and offer.cpu_ram_gb < limits.min_cpu_ram_gb:
        misses.append(
            OfferMiss(
                field="min_cpu_ram_gb",
                label="Host RAM",
                actual_text=f"{offer.cpu_ram_gb:.1f} GB",
                required_text=f"{limits.min_cpu_ram_gb:.0f} GB",
                relation="<",
                gap=max(
                    0.0,
                    (limits.min_cpu_ram_gb - offer.cpu_ram_gb)
                    / max(1.0, limits.min_cpu_ram_gb),
                ),
            )
        )
    if (
        limits.min_inet_down_mbps > 0
        and offer.inet_down_mbps < limits.min_inet_down_mbps
    ):
        misses.append(
            OfferMiss(
                field="min_inet_down_mbps",
                label="Download",
                actual_text=f"{offer.inet_down_mbps:.0f} Mbps",
                required_text=f"{limits.min_inet_down_mbps:.0f} Mbps",
                relation="<",
                gap=max(
                    0.0,
                    (limits.min_inet_down_mbps - offer.inet_down_mbps)
                    / max(1.0, limits.min_inet_down_mbps),
                ),
            )
        )
    if (
        limits.min_inet_up_mbps > 0
        and offer.inet_up_mbps < limits.min_inet_up_mbps
    ):
        misses.append(
            OfferMiss(
                field="min_inet_up_mbps",
                label="Upload",
                actual_text=f"{offer.inet_up_mbps:.0f} Mbps",
                required_text=f"{limits.min_inet_up_mbps:.0f} Mbps",
                relation="<",
                gap=max(
                    0.0,
                    (limits.min_inet_up_mbps - offer.inet_up_mbps)
                    / max(1.0, limits.min_inet_up_mbps),
                ),
            )
        )
    if limits.us_only and not is_us_geolocation(offer.geolocation):
        misses.append(
            OfferMiss(
                field="preferred_region",
                label="Region",
                actual_text=offer.geolocation or "unknown",
                required_text="Americas",
                relation="not in",
                gap=1.0,
            )
        )
    return tuple(misses)


def evaluate_offers(
    offers: Iterable[OfferSnapshot],
    limits: OfferLimits,
) -> tuple[OfferCandidateReport, ...]:
    """Evaluate every offer once, preserving marketplace order."""
    return tuple(
        OfferCandidateReport(offer=offer, misses=evaluate_offer(offer, limits))
        for offer in offers
    )


def build_diagnostics(
    offers: Sequence[OfferSnapshot],
    limits: OfferLimits,
    *,
    query: str = "",
    near_limit: int = 5,
) -> OfferDiagnostics:
    """Build exact failure information, near offers and minimal fixes."""
    reports = evaluate_offers(offers, limits)
    failing = [report for report in reports if not report.passing]
    near = tuple(sorted(failing, key=lambda report: report.score)[:max(1, near_limit)])
    suggestions = _build_suggestions(reports, limits)
    return OfferDiagnostics(
        limits=limits,
        candidates=reports,
        near_offers=near,
        suggestions=suggestions,
        query=query,
    )


def _passes_without(
    report: OfferCandidateReport,
    field: str,
) -> tuple[OfferMiss, ...]:
    return tuple(miss for miss in report.misses if miss.field != field)


def _build_suggestions(
    reports: Sequence[OfferCandidateReport],
    limits: OfferLimits,
) -> tuple[OfferSuggestion, ...]:
    suggestions: list[OfferSuggestion] = []

    price_report = _pick_by_single_field(
        reports, "max_price_per_hour", choose="min", accessor="price_per_hour"
    )
    if price_report is not None and limits.max_price_per_hour > 0:
        target = _ceil_cents(price_report.offer.price_per_hour)
        if target > limits.max_price_per_hour:
            suggestions.append(
                OfferSuggestion(
                    field="max_price_per_hour",
                    value=target,
                    label=f"Raise max price to ${target:.2f}/h",
                    reason=(
                        f"{len(_matching_ids(reports, 'max_price_per_hour', target))} "
                        f"offer(s) would then match, starting at "
                        f"${price_report.offer.price_per_hour:.3f}/h."
                    ),
                    offer_ids=_matching_ids(reports, "max_price_per_hour", target),
                )
            )

    ram_report = _pick_by_single_field(
        reports, "min_cpu_ram_gb", choose="max", accessor="cpu_ram_gb"
    )
    if ram_report is not None and limits.min_cpu_ram_gb > 0:
        target = float(max(1, math.floor(ram_report.offer.cpu_ram_gb)))
        if target < limits.min_cpu_ram_gb:
            suggestions.append(
                OfferSuggestion(
                    field="min_cpu_ram_gb",
                    value=target,
                    label=f"Lower Min RAM to {target:.0f} GB",
                    reason=(
                        f"{len(_matching_ids(reports, 'min_cpu_ram_gb', target))} "
                        f"offer(s) would then match, the largest with "
                        f"{ram_report.offer.cpu_ram_gb:.1f} GB."
                    ),
                    offer_ids=_matching_ids(reports, "min_cpu_ram_gb", target),
                )
            )

    down_report = _pick_by_single_field(
        reports, "min_inet_down_mbps", choose="max", accessor="inet_down_mbps"
    )
    if down_report is not None and limits.min_inet_down_mbps > 0:
        target = float(max(0, math.floor(down_report.offer.inet_down_mbps)))
        if target < limits.min_inet_down_mbps:
            suggestions.append(
                OfferSuggestion(
                    field="min_inet_down_mbps",
                    value=target,
                    label=f"Lower download floor to {target:.0f} Mbps",
                    reason=(
                        f"{len(_matching_ids(reports, 'min_inet_down_mbps', target))} "
                        f"offer(s) would then match."
                    ),
                    offer_ids=_matching_ids(
                        reports, "min_inet_down_mbps", target
                    ),
                )
            )

    up_report = _pick_by_single_field(
        reports, "min_inet_up_mbps", choose="max", accessor="inet_up_mbps"
    )
    if up_report is not None and limits.min_inet_up_mbps > 0:
        target = float(max(0, math.floor(up_report.offer.inet_up_mbps)))
        if target < limits.min_inet_up_mbps:
            suggestions.append(
                OfferSuggestion(
                    field="min_inet_up_mbps",
                    value=target,
                    label=f"Lower upload floor to {target:.0f} Mbps",
                    reason=(
                        f"{len(_matching_ids(reports, 'min_inet_up_mbps', target))} "
                        f"offer(s) would then match."
                    ),
                    offer_ids=_matching_ids(reports, "min_inet_up_mbps", target),
                )
            )

    if limits.us_only:
        candidates = [
            report
            for report in reports
            if not _passes_without(report, "preferred_region") and report.misses
        ]
        ids = tuple(report.offer.offer_id for report in candidates)
        if candidates:
            suggestions.append(
                OfferSuggestion(
                    field="preferred_region",
                    value="any",
                    label="Allow any region",
                    reason=f"{len(candidates)} offer(s) are outside the Americas.",
                    offer_ids=ids,
                )
            )

    return tuple(suggestions)


def _pick_by_single_field(
    reports: Sequence[OfferCandidateReport],
    field: str,
    *,
    choose: str,
    accessor: str,
) -> OfferCandidateReport | None:
    """Pick the candidate that needs the smallest relaxation of one field."""
    candidates = [
        report
        for report in reports
        if report.misses
        and all(miss.field == field for miss in report.misses)
    ]
    if not candidates:
        return None
    key = lambda report: float(getattr(report.offer, accessor))
    return min(candidates, key=key) if choose == "min" else max(candidates, key=key)


def _matching_ids(
    reports: Sequence[OfferCandidateReport],
    field: str,
    value: float,
) -> tuple[int, ...]:
    """Return offers that would pass once ``field`` is relaxed to ``value``."""
    ids: list[int] = []
    for report in reports:
        misses = list(report.misses)
        if not misses:
            continue
        remaining = [
            miss for miss in misses if miss.field != field
        ]
        if remaining:
            continue
        if field == "max_price_per_hour":
            if report.offer.price_per_hour <= value:
                ids.append(report.offer.offer_id)
        elif field == "min_cpu_ram_gb":
            if report.offer.cpu_ram_gb >= value:
                ids.append(report.offer.offer_id)
        elif field == "min_inet_down_mbps":
            if report.offer.inet_down_mbps >= value:
                ids.append(report.offer.offer_id)
        elif field == "min_inet_up_mbps":
            if report.offer.inet_up_mbps >= value:
                ids.append(report.offer.offer_id)
    return tuple(ids)


def _ceil_cents(value: float) -> float:
    return math.ceil(float(value) * 100.0 - 1e-9) / 100.0
