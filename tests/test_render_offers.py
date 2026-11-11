"""Unit tests for marketplace offer diagnostics."""

from src.domain.render.offers import (
    OfferLimits,
    OfferSnapshot,
    build_diagnostics,
    evaluate_offer,
)


def _offer(
    offer_id: int,
    *,
    price: float = 0.14,
    cpu_ram: float = 64.0,
    down: float = 500.0,
    up: float = 300.0,
    reliability: float = 0.99,
    region: str = "United States, US",
) -> OfferSnapshot:
    return OfferSnapshot(
        offer_id=offer_id,
        gpu_name="RTX 4070",
        gpu_ram_gb=12.0,
        cpu_ram_gb=cpu_ram,
        disk_space_gb=200.0,
        cuda_version="13.0",
        reliability=reliability,
        price_per_hour=price,
        inet_down_mbps=down,
        inet_up_mbps=up,
        geolocation=region,
    )


def _limits(**overrides) -> OfferLimits:
    values = dict(
        gpu_profile="rtx_4070",
        gpu_label="RTX 4070 12 GB",
        min_gpu_ram_gb=12.0,
        max_price_per_hour=0.18,
        min_cpu_ram_gb=32.0,
        min_inet_down_mbps=100.0,
        min_inet_up_mbps=50.0,
    )
    values.update(overrides)
    return OfferLimits(**values)


def test_evaluate_offer_reports_exact_failures():
    misses = evaluate_offer(_offer(1, price=0.34, cpu_ram=31.3), _limits())

    assert [miss.field for miss in misses] == ["max_price_per_hour", "min_cpu_ram_gb"]
    assert misses[0].summary == "Price: $0.340/h (> $0.180/h)"
    assert misses[1].summary == "Host RAM: 31.3 GB (< 32 GB)"


def test_diagnostics_find_near_offers_and_minimal_fixes():
    offers = [
        _offer(1, price=0.126, cpu_ram=15.6),
        _offer(2, price=0.135, cpu_ram=31.3),
        _offer(3, price=0.335, cpu_ram=62.9),
    ]

    diagnostics = build_diagnostics(offers, _limits())

    assert diagnostics.candidate_count == 3
    assert diagnostics.near_offers[0].offer.offer_id == 2
    labels = {suggestion.label for suggestion in diagnostics.suggestions}
    assert "Lower Min RAM to 31 GB" in labels
    assert "Raise max price to $0.34/h" in labels
    ram = next(
        item for item in diagnostics.suggestions if item.field == "min_cpu_ram_gb"
    )
    assert ram.value == 31.0
    assert ram.offer_ids == (2,)


def test_diagnostics_suggest_region_relaxation():
    offers = [_offer(1, region="China, CN")]

    diagnostics = build_diagnostics(
        offers,
        _limits(min_cpu_ram_gb=0.0, us_only=True),
    )

    assert diagnostics.suggestions
    assert diagnostics.suggestions[0].field == "preferred_region"
    assert diagnostics.suggestions[0].value == "any"


def test_diagnostics_without_candidates_has_no_near_offers():
    diagnostics = build_diagnostics([], _limits())

    assert diagnostics.candidate_count == 0
    assert diagnostics.near_offers == ()
    assert "base search" in diagnostics.message
