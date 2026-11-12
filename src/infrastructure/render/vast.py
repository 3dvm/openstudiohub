# =========================================================================================
# OPENSTUDIOHUB
# Module: src/infrastructure/render/vast.py
# Architectural role: Render infrastructure / Vast.ai marketplace adapter
# =========================================================================================

"""Thin, testable wrapper around the ``vastai`` CLI.

The API key lives in ``~/.config/vastai/vast_api_key`` (managed by the CLI);
this module never accepts or logs it. All calls use ``--raw`` JSON output so
the adapter is independent from the CLI's table formatting.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Sequence

from src.domain.render.capacity import (
    GPU_PROFILES,
    similar_gpu_profiles,
)
from src.domain.render.offers import (
    OfferAlternative,
    OfferDiagnostics,
    OfferLimits,
    OfferSnapshot,
    build_diagnostics,
    is_us_geolocation,
)

Runner = Callable[[Sequence[str], float], subprocess.CompletedProcess]

DEFAULT_IMAGE = "pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime"
DEFAULT_DISK_GB = 40
DEFAULT_TIMEOUT = 120.0


class VastError(RuntimeError):
    """Base error for the Vast adapter."""


class VastNotConfiguredError(VastError):
    """The CLI or its API key is missing."""


class VastCommandError(VastError):
    """The CLI returned a non-zero exit code."""


class VastOfferError(VastError):
    """No offer satisfies the requested constraints."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: OfferDiagnostics | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class VastOffer:
    id: int
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
    raw: dict
    gpu_profile: str = ""
    gpu_label: str = ""

    def snapshot(self) -> OfferSnapshot:
        return OfferSnapshot(
            offer_id=self.id,
            gpu_name=self.gpu_name,
            gpu_ram_gb=self.gpu_ram_gb,
            cpu_ram_gb=self.cpu_ram_gb,
            disk_space_gb=self.disk_space_gb,
            cuda_version=self.cuda_version,
            reliability=self.reliability,
            price_per_hour=self.price_per_hour,
            inet_down_mbps=self.inet_down_mbps,
            inet_up_mbps=self.inet_up_mbps,
            geolocation=self.geolocation,
            gpu_profile=self.gpu_profile,
            gpu_label=self.gpu_label,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "VastOffer":
        return cls(
            id=int(data.get("id") or 0),
            gpu_name=str(data.get("gpu_name") or ""),
            gpu_ram_gb=round(float(data.get("gpu_total_ram") or 0) / 1024.0, 1),
            cpu_ram_gb=round(float(data.get("cpu_ram") or 0) / 1024.0, 1),
            disk_space_gb=float(data.get("disk_space") or 0),
            cuda_version=str(data.get("cuda_max_good") or data.get("cuda_vers") or ""),
            reliability=float(data.get("reliability2") or data.get("reliability") or 0),
            price_per_hour=float(data.get("dph_total") or 0),
            inet_down_mbps=float(data.get("inet_down") or 0),
            inet_up_mbps=float(data.get("inet_up") or 0),
            geolocation=str(data.get("geolocation") or data.get("machine_location") or ""),
            raw=dict(data),
        )


@dataclass(frozen=True)
class VastInstance:
    id: int
    label: str
    status: str
    ssh_host: str
    ssh_port: int
    price_per_hour: float
    gpu_name: str
    raw: dict

    @classmethod
    def from_dict(cls, data: dict) -> "VastInstance":
        return cls(
            id=int(data.get("id") or data.get("instance_id") or 0),
            label=str(data.get("label") or ""),
            status=str(data.get("actual_status") or data.get("status") or ""),
            ssh_host=str(data.get("ssh_host") or ""),
            ssh_port=int(data.get("ssh_port") or 0),
            price_per_hour=float(data.get("dph_total") or 0),
            gpu_name=str(data.get("gpu_name") or ""),
            raw=dict(data),
        )


def resolve_vastai_cli(explicit: str | Path | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path
        raise VastNotConfiguredError(f"vastai CLI not found at {path}")
    found = shutil.which("vastai")
    if found:
        return Path(found)
    fallback = Path.home() / ".local" / "bin" / "vastai"
    if fallback.is_file():
        return fallback
    raise VastNotConfiguredError(
        "The vastai CLI is not installed. Install it and authenticate with "
        "'vastai set api-key'."
    )


class VastProvider:
    def __init__(
        self,
        vastai_path: str | Path | None = None,
        *,
        runner: Runner | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.cli = resolve_vastai_cli(vastai_path)
        self._runner = runner or (
            lambda command, call_timeout: subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                timeout=call_timeout,
                check=False,
            )
        )
        self.timeout = float(timeout)

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------
    def _run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
        json_output: bool = False,
    ):
        command = [str(self.cli), *args]
        try:
            result = self._runner(command, timeout or self.timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise VastCommandError(f"Could not run vastai: {error}") from error
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise VastCommandError(
                f"vastai {' '.join(args)} failed: {detail or result.returncode}"
            )
        if json_output:
            try:
                return json.loads(result.stdout or "null")
            except ValueError as error:
                raise VastCommandError(
                    f"vastai returned invalid JSON for {' '.join(args)}"
                ) from error
        return result.stdout or ""

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------
    def balance(self) -> float:
        data = self._run(["show", "user", "--raw"], json_output=True)
        try:
            return float((data or {}).get("credit") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # ------------------------------------------------------------------
    # Offers
    # ------------------------------------------------------------------
    def search_offers(
        self,
        query: str,
        *,
        order: str = "dph",
        limit: int = 30,
    ) -> list[VastOffer]:
        data = self._run(
            ["search", "offers", query, "-o", order, "--raw"], json_output=True
        )
        offers = [VastOffer.from_dict(item) for item in (data or []) if isinstance(item, dict)]
        return offers[: max(1, int(limit))]

    def choose_offers(
        self,
        gpu_profile: str,
        *,
        count: int,
        max_price_per_hour: float = 0.0,
        min_disk_gb: int = DEFAULT_DISK_GB,
        min_reliability: float = 0.95,
        min_cuda: str = "12.8",
        preferred_region: str = "prefer_americas",
        min_inet_down_mbps: float = 0.0,
        min_inet_up_mbps: float = 0.0,
        min_cpu_ram_gb: float = 0.0,
        fill_similar: bool = False,
        similar_mode: str = "floor",
        allow_less_vram: bool = False,
    ) -> list[VastOffer]:
        profile = GPU_PROFILES.get(gpu_profile)
        if profile is None:
            raise VastOfferError(f"Unknown GPU profile: {gpu_profile}")
        wanted = max(1, int(count or 1))
        offers, diagnostics = self._evaluate_profile(
            profile,
            max_price_per_hour=max_price_per_hour,
            min_disk_gb=min_disk_gb,
            min_reliability=min_reliability,
            min_cuda=min_cuda,
            preferred_region=preferred_region,
            min_inet_down_mbps=min_inet_down_mbps,
            min_inet_up_mbps=min_inet_up_mbps,
            min_cpu_ram_gb=min_cpu_ram_gb,
        )
        selected = list(offers)
        seen = {offer.id for offer in selected}
        if fill_similar and len(selected) < wanted:
            for key in similar_gpu_profiles(
                gpu_profile,
                similar_mode,
                allow_less_vram=allow_less_vram,
            ):
                fallback = GPU_PROFILES.get(key)
                if fallback is None:
                    continue
                extra, _fallback_diagnostics = self._evaluate_profile(
                    fallback,
                    max_price_per_hour=max_price_per_hour,
                    min_disk_gb=min_disk_gb,
                    min_reliability=min_reliability,
                    min_cuda=min_cuda,
                    preferred_region=preferred_region,
                    min_inet_down_mbps=min_inet_down_mbps,
                    min_inet_up_mbps=min_inet_up_mbps,
                    min_cpu_ram_gb=min_cpu_ram_gb,
                )
                for offer in extra:
                    if offer.id in seen:
                        continue
                    selected.append(offer)
                    seen.add(offer.id)
                    if len(selected) >= wanted:
                        break
                if len(selected) >= wanted:
                    break
        if not selected:
            raise VastOfferError(
                _diagnostics_message(diagnostics),
                diagnostics=diagnostics,
            )
        return selected[:wanted]

    def search_other_profiles(
        self,
        gpu_profile: str,
        *,
        count: int = 1,
        max_price_per_hour: float = 0.0,
        min_disk_gb: int = DEFAULT_DISK_GB,
        min_reliability: float = 0.95,
        min_cuda: str = "12.8",
        preferred_region: str = "prefer_americas",
        min_inet_down_mbps: float = 0.0,
        min_inet_up_mbps: float = 0.0,
        min_cpu_ram_gb: float = 0.0,
    ) -> list[OfferAlternative]:
        """Find valid offers in every GPU profile except ``gpu_profile``."""
        alternatives: list[OfferAlternative] = []
        for key, profile in GPU_PROFILES.items():
            if key == gpu_profile:
                continue
            offers, _diagnostics = self._evaluate_profile(
                profile,
                max_price_per_hour=max_price_per_hour,
                min_disk_gb=min_disk_gb,
                min_reliability=min_reliability,
                min_cuda=min_cuda,
                preferred_region=preferred_region,
                min_inet_down_mbps=min_inet_down_mbps,
                min_inet_up_mbps=min_inet_up_mbps,
                min_cpu_ram_gb=min_cpu_ram_gb,
            )
            if offers:
                alternatives.append(
                    OfferAlternative(
                        gpu_profile=key,
                        gpu_label=profile.label,
                        offer=offers[0].snapshot(),
                    )
                )
        alternatives.sort(key=lambda item: item.offer.price_per_hour)
        return alternatives[: max(1, int(count))]

    def _evaluate_profile(
        self,
        profile,
        *,
        max_price_per_hour: float,
        min_disk_gb: int,
        min_reliability: float,
        min_cuda: str,
        preferred_region: str,
        min_inet_down_mbps: float,
        min_inet_up_mbps: float,
        min_cpu_ram_gb: float,
    ) -> tuple[list[VastOffer], OfferDiagnostics]:
        query = (
            "num_gpus=1 rentable=true "
            f"gpu_name in [{profile.vast_gpu_name}] "
            f"disk_space>={max(10, int(min_disk_gb))} "
            f"cuda_vers>={min_cuda}"
        )
        candidates = self.search_offers(query, limit=100)
        region = (preferred_region or "").strip().lower()
        us_only = region in ("us", "us_only", "us-only")
        prefer_us = region in (
            "prefer_us",
            "prefer-us",
            "prefer",
            "prefer_americas",
            "prefer-americas",
        )
        limits = OfferLimits(
            gpu_profile=profile.key,
            gpu_label=profile.label,
            min_gpu_ram_gb=float(profile.vram_gb),
            max_price_per_hour=float(max_price_per_hour or 0.0),
            min_reliability=float(min_reliability),
            min_cpu_ram_gb=float(min_cpu_ram_gb or 0.0),
            min_inet_down_mbps=float(min_inet_down_mbps or 0.0),
            min_inet_up_mbps=float(min_inet_up_mbps or 0.0),
            preferred_region=str(preferred_region or ""),
            us_only=us_only,
            min_disk_gb=int(min_disk_gb),
            min_cuda=str(min_cuda),
        )
        snapshots = [
            replace(
                offer.snapshot(),
                gpu_profile=profile.key,
                gpu_label=profile.label,
            )
            for offer in candidates
            if offer.id
        ]
        diagnostics = build_diagnostics(snapshots, limits, query=query)
        passing_ids = {
            report.offer.offer_id
            for report in diagnostics.candidates
            if report.passing
        }
        filtered = [
            replace(
                offer,
                gpu_profile=profile.key,
                gpu_label=profile.label,
            )
            for offer in candidates
            if offer.id in passing_ids
        ]
        filtered.sort(
            key=lambda offer: (
                0 if (prefer_us and is_us_geolocation(offer.geolocation)) else 1,
                offer.price_per_hour,
                -offer.reliability,
            )
        )
        return filtered, diagnostics

    # ------------------------------------------------------------------
    # Instances
    # ------------------------------------------------------------------
    def create_instance(
        self,
        offer_id: int,
        *,
        label: str,
        image: str = DEFAULT_IMAGE,
        disk_gb: int = DEFAULT_DISK_GB,
        onstart: str = "",
    ) -> VastInstance:
        args = [
            "create",
            "instance",
            str(offer_id),
            "--image",
            image,
            "--disk",
            str(max(10, int(disk_gb))),
            "--ssh",
            "--direct",
            "--label",
            label,
            "--raw",
        ]
        if onstart:
            args.extend(["--onstart-cmd", onstart])
        data = self._run(args, json_output=True)
        instance_id = int(
            (data or {}).get("new_contract") or (data or {}).get("instance_id") or 0
        )
        if not instance_id:
            raise VastCommandError("vastai did not return an instance id")
        return self.show_instance(instance_id)

    def show_instance(self, instance_id: int) -> VastInstance:
        data = self._run(["show", "instance", str(instance_id), "--raw"], json_output=True)
        if not isinstance(data, dict):
            raise VastCommandError(f"Instance {instance_id} was not found")
        return VastInstance.from_dict(data)

    def list_instances(self) -> list[VastInstance]:
        data = self._run(["show", "instances", "--raw"], json_output=True)
        return [VastInstance.from_dict(item) for item in (data or []) if isinstance(item, dict)]

    def wait_running(
        self,
        instance_id: int,
        *,
        timeout: float = 900.0,
        interval: float = 10.0,
        progress: Callable[[str], None] | None = None,
    ) -> VastInstance:
        deadline = time.monotonic() + max(1.0, timeout)
        last_status = ""
        while time.monotonic() < deadline:
            instance = self.show_instance(instance_id)
            if instance.status != last_status:
                last_status = instance.status
                if progress is not None:
                    progress(f"instance {instance_id}: {instance.status or 'unknown'}")
            if instance.status == "running":
                return instance
            time.sleep(max(1.0, interval))
        raise VastCommandError(f"Instance {instance_id} did not reach running in time")

    def destroy_instance(self, instance_id: int) -> None:
        self._run(["destroy", "instance", str(instance_id), "-y"])

    def destroy_by_label_prefix(self, prefix: str) -> int:
        destroyed = 0
        for instance in self.list_instances():
            if instance.label.startswith(prefix):
                try:
                    self.destroy_instance(instance.id)
                    destroyed += 1
                except VastError:
                    continue
        return destroyed


def _diagnostics_message(diagnostics: OfferDiagnostics) -> str:
    near = diagnostics.near_offers[0] if diagnostics.near_offers else None
    if near is None:
        return diagnostics.message
    return (
        f"{diagnostics.message} Nearest: offer {near.offer.offer_id} at "
        f"${near.offer.price_per_hour:.3f}/h — {near.failure_text}."
    )
