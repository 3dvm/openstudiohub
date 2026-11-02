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
