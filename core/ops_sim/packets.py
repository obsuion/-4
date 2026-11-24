"""Deterministic V3.8 command/telemetry packet proxies.

V3.8A translates authoritative simulator events into passive KB-scale
diagnostics. V3.8B adds a bounded seeded delivery gate. Neither model implements
a packet queue, propagation delay, RF physics, protocols, modulation, a link
budget, a ground network, or flight software.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite

from .config import DEFAULT_CONFIG, SimulationConfig


PACKET_MODELS = ("legacy", "packet_proxy")
PACKET_DELIVERY_MODELS = ("ideal", "loss_retry_proxy")


@dataclass(frozen=True)
class PacketDeliveryAssessment:
    """One stable delivery outcome for an already-eligible transfer."""

    attempted: bool
    delivered: bool
    failed: bool
    packet_kind: str
    direction: str
    delivery_draw: float | None
    drop_threshold_proxy: float
    reason: str


def assess_packet_delivery(
    *,
    packet_delivery_model: str,
    attempted: bool,
    packet_delivery_seed: int,
    hour: int,
    packet_kind: str,
    direction: str,
    packet_drop_fraction_proxy: float,
    stable_identifier: str | None = None,
) -> PacketDeliveryAssessment:
    """Return a repeatable delivery gate without mutating simulator state."""
    if packet_delivery_model not in PACKET_DELIVERY_MODELS:
        choices = ", ".join(PACKET_DELIVERY_MODELS)
        raise ValueError(
            f"packet_delivery_model must be one of: {choices}"
        )
    if not isinstance(attempted, bool):
        raise ValueError("attempted must be a boolean")
    if not isinstance(packet_delivery_seed, int) or isinstance(
        packet_delivery_seed, bool
    ):
        raise ValueError("packet_delivery_seed must be an integer")
    if not isinstance(hour, int) or isinstance(hour, bool) or hour < 0:
        raise ValueError("hour must be a non-negative integer")
    if not packet_kind:
        raise ValueError("packet_kind must be non-empty")
    if direction not in ("downlink", "uplink"):
        raise ValueError("direction must be 'downlink' or 'uplink'")
    if (
        not isinstance(packet_drop_fraction_proxy, (int, float))
        or isinstance(packet_drop_fraction_proxy, bool)
        or not isfinite(packet_drop_fraction_proxy)
        or not 0.0 <= packet_drop_fraction_proxy <= 1.0
    ):
        raise ValueError("packet_drop_fraction_proxy must be in [0, 1]")

    if not attempted:
        return PacketDeliveryAssessment(
            attempted=False,
            delivered=False,
            failed=False,
            packet_kind=packet_kind,
            direction=direction,
            delivery_draw=None,
            drop_threshold_proxy=packet_drop_fraction_proxy,
            reason="no_eligible_transfer_attempt",
        )
    if packet_delivery_model == "ideal":
        return PacketDeliveryAssessment(
            attempted=True,
            delivered=True,
            failed=False,
            packet_kind=packet_kind,
            direction=direction,
            delivery_draw=None,
            drop_threshold_proxy=packet_drop_fraction_proxy,
            reason="ideal_delivery",
        )

    canonical = "|".join((
        str(packet_delivery_seed),
        str(hour),
        packet_kind,
        direction,
        stable_identifier or "",
    ))
    digest = sha256(canonical.encode("utf-8")).digest()
    integer = int.from_bytes(digest[:8], "big", signed=False)
    draw = integer / (1 << 64)
    delivered = draw >= packet_drop_fraction_proxy
    return PacketDeliveryAssessment(
        attempted=True,
        delivered=delivered,
        failed=not delivered,
        packet_kind=packet_kind,
        direction=direction,
        delivery_draw=draw,
        drop_threshold_proxy=packet_drop_fraction_proxy,
        reason=(
            "delivery_succeeded_at_eligible_contact"
            if delivered
            else "delivery_failed_retry_at_later_contact"
        ),
    )


@dataclass(frozen=True)
class PacketHourAssessment:
    packet_model: str
    packet_delivery_model: str
    telemetry_packet_generated_this_hour: bool | None
    telemetry_packet_delivery_attempted_this_hour: bool | None
    telemetry_packet_downlinked_this_hour: bool | None
    telemetry_packet_delivery_failed_this_hour: bool | None
    command_packets_attempted_this_hour: int
    command_packets_uploaded_this_hour: int
    command_packets_failed_this_hour: int
    daily_plan_packet_delivery_attempted_this_hour: bool | None
    daily_plan_packet_uploaded_this_hour: bool | None
    daily_plan_packet_delivery_failed_this_hour: bool | None
    packet_uplink_kb_this_hour: float
    packet_downlink_kb_this_hour: float
    packet_reason_this_hour: str | None
    packet_delivery_reason_this_hour: str | None


def assess_packets_for_hour(
    *,
    packet_model: str,
    packet_delivery_model: str = "ideal",
    telemetry_updated_this_hour: bool,
    telemetry_delivery_attempted_this_hour: bool | None = None,
    plan_uploaded_this_hour: bool,
    daily_plan_delivery_attempted_this_hour: bool | None = None,
    lifecycle_response_upload_count: int = 0,
    lifecycle_response_attempt_count: int | None = None,
    contingency_plan_uploaded_this_hour: bool = False,
    contingency_plan_delivery_attempted_this_hour: bool | None = None,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> PacketHourAssessment:
    """Account for existing upload/refresh events without changing them."""
    if packet_model not in PACKET_MODELS:
        choices = ", ".join(PACKET_MODELS)
        raise ValueError(f"packet_model must be one of: {choices}")
    if packet_delivery_model not in PACKET_DELIVERY_MODELS:
        choices = ", ".join(PACKET_DELIVERY_MODELS)
        raise ValueError(
            f"packet_delivery_model must be one of: {choices}"
        )
    if packet_model == "legacy" and packet_delivery_model != "ideal":
        raise ValueError(
            "non-ideal packet delivery requires packet_model='packet_proxy'"
        )
    for name, value in (
        ("telemetry_updated_this_hour", telemetry_updated_this_hour),
        ("plan_uploaded_this_hour", plan_uploaded_this_hour),
        (
            "contingency_plan_uploaded_this_hour",
            contingency_plan_uploaded_this_hour,
        ),
    ):
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
    if (
        not isinstance(lifecycle_response_upload_count, int)
        or isinstance(lifecycle_response_upload_count, bool)
        or lifecycle_response_upload_count < 0
    ):
        raise ValueError(
            "lifecycle_response_upload_count must be a non-negative integer"
        )
    if packet_model == "legacy":
        return PacketHourAssessment(
            packet_model=packet_model,
            packet_delivery_model=packet_delivery_model,
            telemetry_packet_generated_this_hour=None,
            telemetry_packet_delivery_attempted_this_hour=None,
            telemetry_packet_downlinked_this_hour=None,
            telemetry_packet_delivery_failed_this_hour=None,
            command_packets_attempted_this_hour=0,
            command_packets_uploaded_this_hour=0,
            command_packets_failed_this_hour=0,
            daily_plan_packet_delivery_attempted_this_hour=None,
            daily_plan_packet_uploaded_this_hour=None,
            daily_plan_packet_delivery_failed_this_hour=None,
            packet_uplink_kb_this_hour=0.0,
            packet_downlink_kb_this_hour=0.0,
            packet_reason_this_hour=None,
            packet_delivery_reason_this_hour=None,
        )
    telemetry_attempted = (
        telemetry_updated_this_hour
        if telemetry_delivery_attempted_this_hour is None
        else telemetry_delivery_attempted_this_hour
    )
    daily_plan_attempted = (
        plan_uploaded_this_hour
        if daily_plan_delivery_attempted_this_hour is None
        else daily_plan_delivery_attempted_this_hour
    )
    lifecycle_attempts = (
        lifecycle_response_upload_count
        if lifecycle_response_attempt_count is None
        else lifecycle_response_attempt_count
    )
    contingency_attempted = (
        contingency_plan_uploaded_this_hour
        if contingency_plan_delivery_attempted_this_hour is None
        else contingency_plan_delivery_attempted_this_hour
    )
    for name, value in (
        ("telemetry_delivery_attempted_this_hour", telemetry_attempted),
        ("daily_plan_delivery_attempted_this_hour", daily_plan_attempted),
        (
            "contingency_plan_delivery_attempted_this_hour",
            contingency_attempted,
        ),
    ):
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
    if (
        not isinstance(lifecycle_attempts, int)
        or isinstance(lifecycle_attempts, bool)
        or lifecycle_attempts < lifecycle_response_upload_count
    ):
        raise ValueError(
            "lifecycle_response_attempt_count must be a non-negative integer "
            "at least as large as the upload count"
        )
    if telemetry_updated_this_hour and not telemetry_attempted:
        raise ValueError("telemetry delivery cannot succeed without an attempt")
    if plan_uploaded_this_hour and not daily_plan_attempted:
        raise ValueError("daily-plan delivery cannot succeed without an attempt")
    if contingency_plan_uploaded_this_hour and not contingency_attempted:
        raise ValueError("contingency delivery cannot succeed without an attempt")
    command_packets = lifecycle_response_upload_count + int(
        contingency_plan_uploaded_this_hour
    )
    command_attempts = lifecycle_attempts + int(contingency_attempted)
    command_failures = command_attempts - command_packets
    telemetry_failed = telemetry_attempted and not telemetry_updated_this_hour
    daily_plan_failed = daily_plan_attempted and not plan_uploaded_this_hour
    uplink_kb = (
        command_packets * config.command_packet_kb
        + int(plan_uploaded_this_hour) * config.daily_plan_packet_kb
    )
    downlink_kb = (
        config.housekeeping_telemetry_packet_kb
        if telemetry_updated_this_hour
        else 0.0
    )
    reasons = ["housekeeping_generated"]
    if telemetry_updated_this_hour:
        reasons.append("existing_telemetry_refresh")
    if lifecycle_response_upload_count:
        reasons.append("lifecycle_response_upload")
    if contingency_plan_uploaded_this_hour:
        reasons.append("contingency_plan_upload")
    if plan_uploaded_this_hour:
        reasons.append("daily_plan_upload")
    delivery_reasons = []
    if telemetry_failed:
        delivery_reasons.append("telemetry_delivery_failed")
    if command_failures:
        delivery_reasons.append("command_delivery_failed")
    if daily_plan_failed:
        delivery_reasons.append("daily_plan_delivery_failed")
    if not delivery_reasons:
        delivery_reasons.append("no_delivery_failure")
    return PacketHourAssessment(
        packet_model=packet_model,
        packet_delivery_model=packet_delivery_model,
        telemetry_packet_generated_this_hour=True,
        telemetry_packet_delivery_attempted_this_hour=telemetry_attempted,
        telemetry_packet_downlinked_this_hour=telemetry_updated_this_hour,
        telemetry_packet_delivery_failed_this_hour=telemetry_failed,
        command_packets_attempted_this_hour=command_attempts,
        command_packets_uploaded_this_hour=command_packets,
        command_packets_failed_this_hour=command_failures,
        daily_plan_packet_delivery_attempted_this_hour=daily_plan_attempted,
        daily_plan_packet_uploaded_this_hour=plan_uploaded_this_hour,
        daily_plan_packet_delivery_failed_this_hour=daily_plan_failed,
        packet_uplink_kb_this_hour=uplink_kb,
        packet_downlink_kb_this_hour=downlink_kb,
        packet_reason_this_hour=";".join(reasons),
        packet_delivery_reason_this_hour=";".join(delivery_reasons),
    )


__all__ = [
    "PACKET_MODELS",
    "PACKET_DELIVERY_MODELS",
    "PacketDeliveryAssessment",
    "PacketHourAssessment",
    "assess_packet_delivery",
    "assess_packets_for_hour",
]
