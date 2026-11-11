"""Unit tests for the Vast.ai CLI adapter (no network calls)."""

import json
import subprocess
from pathlib import Path

from src.infrastructure.render.vast import VastProvider


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, command, timeout):
        self.calls.append(list(command))
        for predicate, payload, returncode in self.responses:
            if predicate(command):
                return subprocess.CompletedProcess(
                    command, returncode, json.dumps(payload), ""
                )
        return subprocess.CompletedProcess(command, 1, "", "unexpected command")


def _cli(tmp_path: Path) -> Path:
    path = tmp_path / "vastai"
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    return path


def test_balance_reads_credit(tmp_path):
    runner = FakeRunner([(lambda cmd: "show" in cmd and "user" in cmd, {"credit": 2.86}, 0)])
    provider = VastProvider(_cli(tmp_path), runner=runner)

    assert provider.balance() == 2.86


def test_choose_offers_filters_price_and_reliability(tmp_path):
    offers = [
        {
            "id": 1,
            "gpu_name": "RTX 3090",
            "gpu_total_ram": 24576,
            "cpu_ram": 32000,
            "disk_space": 100,
            "cuda_max_good": "13.0",
            "reliability2": 0.99,
            "dph_total": 0.15,
            "inet_down": 200,
        },
        {
            "id": 2,
            "gpu_name": "RTX 3090",
            "gpu_total_ram": 24576,
            "cpu_ram": 32000,
            "disk_space": 100,
            "cuda_max_good": "13.0",
            "reliability2": 0.99,
            "dph_total": 0.9,
            "inet_down": 200,
        },
    ]
    runner = FakeRunner([(lambda cmd: "search" in cmd and "offers" in cmd, offers, 0)])
    provider = VastProvider(_cli(tmp_path), runner=runner)

    selected = provider.choose_offers(
        "rtx_3090", count=2, max_price_per_hour=0.2, min_disk_gb=40
    )

    assert [offer.id for offer in selected] == [1]
    assert selected[0].gpu_ram_gb == 24.0


def test_create_and_destroy_instance(tmp_path):
    created = {"id": 123, "actual_status": "running", "ssh_host": "ssh5.vast.ai", "ssh_port": 12052, "dph_total": 0.15, "gpu_name": "RTX 3090"}
    runner = FakeRunner(
        [
            (lambda cmd: "create" in cmd and "instance" in cmd, {"new_contract": 123}, 0),
            (lambda cmd: "show" in cmd and "instance" in cmd and "123" in cmd, created, 0),
            (lambda cmd: "destroy" in cmd and "instance" in cmd, {}, 0),
        ]
    )
    provider = VastProvider(_cli(tmp_path), runner=runner)

    instance = provider.create_instance(1, label="test")
    assert instance.id == 123
    assert instance.ssh_port == 12052
    assert instance.price_per_hour == 0.15

    provider.destroy_instance(123)


def test_destroy_by_label_prefix_only_touches_matching_instances(tmp_path):
    instances = [
        {"id": 1, "label": "osh-render-p0005-abc-0", "actual_status": "running"},
        {"id": 2, "label": "other-job", "actual_status": "running"},
    ]
    runner = FakeRunner(
        [
            (lambda cmd: "show" in cmd and "instances" in cmd, instances, 0),
            (lambda cmd: "destroy" in cmd and "instance" in cmd, {}, 0),
        ]
    )
    provider = VastProvider(_cli(tmp_path), runner=runner)

    assert provider.destroy_by_label_prefix("osh-render-p0005-") == 1
    destroyed = [call for call in runner.calls if "destroy" in call]
    assert destroyed and "1" in destroyed[0]


def test_choose_offers_prefers_us_and_filters_bandwidth(tmp_path):
    offers = [
        {
            "id": 1,
            "gpu_name": "RTX 3090",
            "gpu_total_ram": 24576,
            "cpu_ram": 32000,
            "disk_space": 100,
            "cuda_max_good": "13.0",
            "reliability2": 0.99,
            "dph_total": 0.16,
            "inet_down": 300,
            "inet_up": 200,
            "geolocation": "United States, US",
        },
        {
            "id": 2,
            "gpu_name": "RTX 3090",
            "gpu_total_ram": 24576,
            "cpu_ram": 32000,
            "disk_space": 100,
            "cuda_max_good": "13.0",
            "reliability2": 0.99,
            "dph_total": 0.12,
            "inet_down": 400,
            "inet_up": 300,
            "geolocation": "China, CN",
        },
    ]
    runner = FakeRunner([(lambda cmd: "search" in cmd and "offers" in cmd, offers, 0)])
    provider = VastProvider(_cli(tmp_path), runner=runner)

    preferred = provider.choose_offers(
        "rtx_3090", count=1, preferred_region="prefer_us", min_inet_down_mbps=100
    )
    assert preferred[0].id == 1

    us_only = provider.choose_offers(
        "rtx_3090", count=2, preferred_region="us", min_inet_down_mbps=100
    )
    assert [offer.id for offer in us_only] == [1]


def test_choose_offers_filters_system_ram(tmp_path):
    offers = [
        {
            "id": 1,
            "gpu_name": "RTX 3090",
            "gpu_total_ram": 24576,
            "cpu_ram": 16000,
            "disk_space": 100,
            "cuda_max_good": "13.0",
            "reliability2": 0.99,
            "dph_total": 0.10,
            "inet_down": 200,
            "inet_up": 200,
        },
        {
            "id": 2,
            "gpu_name": "RTX 3090",
            "gpu_total_ram": 24576,
            "cpu_ram": 65536,
            "disk_space": 100,
            "cuda_max_good": "13.0",
            "reliability2": 0.99,
            "dph_total": 0.15,
            "inet_down": 200,
            "inet_up": 200,
        },
    ]
    runner = FakeRunner([(lambda cmd: "search" in cmd and "offers" in cmd, offers, 0)])
    provider = VastProvider(_cli(tmp_path), runner=runner)

    selected = provider.choose_offers(
        "rtx_3090", count=2, max_price_per_hour=0.2, min_cpu_ram_gb=60
    )

    assert [offer.id for offer in selected] == [2]
    assert selected[0].cpu_ram_gb == 64.0


def test_choose_offers_raises_with_exact_diagnostics(tmp_path):
    offers = [
        {
            "id": 1,
            "gpu_name": "RTX 4070",
            "gpu_total_ram": 12288,
            "cpu_ram": 32000,
            "disk_space": 200,
            "cuda_max_good": "13.0",
            "reliability2": 0.99,
            "dph_total": 0.135,
            "inet_down": 940,
            "inet_up": 115,
        },
        {
            "id": 2,
            "gpu_name": "RTX 4070",
            "gpu_total_ram": 12288,
            "cpu_ram": 64000,
            "disk_space": 200,
            "cuda_max_good": "13.0",
            "reliability2": 0.99,
            "dph_total": 0.335,
            "inet_down": 700,
            "inet_up": 280,
        },
    ]
    runner = FakeRunner([(lambda cmd: "search" in cmd and "offers" in cmd, offers, 0)])
    provider = VastProvider(_cli(tmp_path), runner=runner)

    import pytest

    from src.infrastructure.render.vast import VastOfferError

    with pytest.raises(VastOfferError) as raised:
        provider.choose_offers(
            "rtx_4070",
            count=1,
            max_price_per_hour=0.18,
            min_cpu_ram_gb=32,
            min_inet_down_mbps=100,
            min_inet_up_mbps=50,
        )

    diagnostics = raised.value.diagnostics
    assert diagnostics is not None
    assert diagnostics.near_offers[0].offer.offer_id == 1
    assert "Host RAM: 31.2 GB (< 32 GB)" in diagnostics.near_offers[0].failure_text
    labels = {suggestion.label for suggestion in diagnostics.suggestions}
    assert "Lower Min RAM to 31 GB" in labels
    assert "Raise max price to $0.34/h" in labels


def test_search_other_profiles_returns_valid_alternatives(tmp_path):
    offer = {
        "id": 9,
        "gpu_name": "RTX 3090",
        "gpu_total_ram": 24576,
        "cpu_ram": 64000,
        "disk_space": 200,
        "cuda_max_good": "13.0",
        "reliability2": 0.99,
        "dph_total": 0.15,
        "inet_down": 500,
        "inet_up": 200,
        "geolocation": "United States, US",
    }
    runner = FakeRunner(
        [
            (
                lambda cmd: "RTX_3090" in " ".join(cmd),
                [offer],
                0,
            ),
            (lambda cmd: "search" in cmd and "offers" in cmd, [], 0),
        ]
    )
    provider = VastProvider(_cli(tmp_path), runner=runner)

    alternatives = provider.search_other_profiles(
        "rtx_4070",
        max_price_per_hour=0.18,
        min_cpu_ram_gb=32,
        min_inet_down_mbps=100,
        min_inet_up_mbps=50,
    )

    assert [item.gpu_profile for item in alternatives] == ["rtx_3090"]
    assert alternatives[0].offer.offer_id == 9
