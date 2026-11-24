"""Explicit telemetry and incomplete ground-knowledge state for V5."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real

from .ids import TelemetrySnapshotId, WorldEventId
from .state import OperationalMode


def _validate_timestamp(name: str, value: object) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


def _validate_nonnegative_real(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    """Immutable data explicitly transferred across the telemetry boundary."""

    snapshot_id: TelemetrySnapshotId
    sampled_at_seconds: int
    received_at_seconds: int
    battery_energy_wh: float
    delta_v_remaining_m_per_s: float
    operational_mode: OperationalMode

    def __post_init__(self) -> None:
        if type(self.snapshot_id) is not TelemetrySnapshotId:
            raise TypeError("snapshot_id must be a TelemetrySnapshotId")
        _validate_timestamp("sampled_at_seconds", self.sampled_at_seconds)
        _validate_timestamp("received_at_seconds", self.received_at_seconds)
        if self.received_at_seconds < self.sampled_at_seconds:
            raise ValueError(
                "received_at_seconds must be greater than or equal to "
                "sampled_at_seconds"
            )
        _validate_nonnegative_real(
            "battery_energy_wh", self.battery_energy_wh
        )
        _validate_nonnegative_real(
            "delta_v_remaining_m_per_s",
            self.delta_v_remaining_m_per_s,
        )
        if type(self.operational_mode) is not OperationalMode:
            raise TypeError("operational_mode must be an OperationalMode")


@dataclass(slots=True)
class GroundKnowledgeState:
    """Mutable ground belief assembled only from explicit received knowledge."""

    latest_telemetry: TelemetrySnapshot | None
    known_world_event_ids: tuple[WorldEventId, ...]

    def __post_init__(self) -> None:
        if (
            self.latest_telemetry is not None
            and type(self.latest_telemetry) is not TelemetrySnapshot
        ):
            raise TypeError(
                "latest_telemetry must be a TelemetrySnapshot or None"
            )
        if type(self.known_world_event_ids) is not tuple:
            raise TypeError("known_world_event_ids must be a tuple")
        if not all(
            type(event_id) is WorldEventId
            for event_id in self.known_world_event_ids
        ):
            raise TypeError(
                "known_world_event_ids must contain only WorldEventId values"
            )
        if len(set(self.known_world_event_ids)) != len(
            self.known_world_event_ids
        ):
            raise ValueError(
                "known_world_event_ids must not contain duplicates"
            )


__all__ = ["GroundKnowledgeState", "TelemetrySnapshot"]
