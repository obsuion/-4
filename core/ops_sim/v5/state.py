"""Authoritative spacecraft and onboard runtime state for V5."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Real

from .ids import AuthorityId, PlanId, ThermalNodeId
from .onboard_data import OnboardAcquisitionDataRecord


class OperationalMode(str, Enum):
    """Current spacecraft execution or activity mode."""

    SAFE = "safe"
    STANDBY = "standby"
    IMAGING = "imaging"
    DOWNLINK = "downlink"
    MANEUVER = "maneuver"
    BACKUP = "backup"
    EMERGENCY_BEACON = "emergency-beacon"


class FDIRState(str, Enum):
    """Current onboard fallback and protection regime."""

    NORMAL = "normal"
    BACKUP = "backup"
    EMERGENCY_BEACON = "emergency-beacon"


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


def _validate_positive_real(name: str, value: object) -> None:
    _validate_nonnegative_real(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _validate_optional_timestamp(name: str, value: object) -> None:
    if value is None:
        return
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer or None")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


@dataclass(slots=True)
class BatteryState:
    """Authoritative onboard battery energy state."""

    energy_wh: float

    def __post_init__(self) -> None:
        _validate_nonnegative_real("energy_wh", self.energy_wh)


@dataclass(slots=True)
class BatteryDegradationState:
    """Authoritative battery capability retention and physical history."""

    usable_capacity_retention: float
    cumulative_energy_throughput_wh: float

    def __post_init__(self) -> None:
        _validate_positive_real(
            "usable_capacity_retention",
            self.usable_capacity_retention,
        )
        if self.usable_capacity_retention > 1:
            raise ValueError(
                "usable_capacity_retention must be less than or equal to one"
            )
        _validate_nonnegative_real(
            "cumulative_energy_throughput_wh",
            self.cumulative_energy_throughput_wh,
        )


@dataclass(slots=True)
class SolarDegradationState:
    """Authoritative retained solar-generation capability."""

    generation_retention: float

    def __post_init__(self) -> None:
        _validate_positive_real(
            "generation_retention", self.generation_retention
        )
        if self.generation_retention > 1:
            raise ValueError(
                "generation_retention must be less than or equal to one"
            )


@dataclass(slots=True)
class DegradationState:
    """Authoritative named physical degradation state."""

    battery: BatteryDegradationState
    solar: SolarDegradationState

    def __post_init__(self) -> None:
        if type(self.battery) is not BatteryDegradationState:
            raise TypeError("battery must be a BatteryDegradationState")
        if type(self.solar) is not SolarDegradationState:
            raise TypeError("solar must be a SolarDegradationState")
        BatteryDegradationState(
            self.battery.usable_capacity_retention,
            self.battery.cumulative_energy_throughput_wh,
        )
        SolarDegradationState(self.solar.generation_retention)


@dataclass(slots=True)
class PropulsionState:
    """Authoritative remaining propulsion capability state."""

    delta_v_remaining_m_per_s: float

    def __post_init__(self) -> None:
        _validate_nonnegative_real(
            "delta_v_remaining_m_per_s",
            self.delta_v_remaining_m_per_s,
        )


@dataclass(slots=True)
class ThermalNodeState:
    """Authoritative current temperature for one identified thermal node."""

    node_id: ThermalNodeId
    temperature_k: float

    def __post_init__(self) -> None:
        if type(self.node_id) is not ThermalNodeId:
            raise TypeError("node_id must be a ThermalNodeId")
        _validate_positive_real("temperature_k", self.temperature_k)


@dataclass(slots=True)
class ThermalState:
    """Authoritative temperatures for an extensible set of thermal nodes."""

    node_states: tuple[ThermalNodeState, ...]

    def __post_init__(self) -> None:
        if type(self.node_states) is not tuple:
            raise TypeError("node_states must be a tuple")
        if not self.node_states:
            raise ValueError("node_states must not be empty")
        if not all(
            type(node_state) is ThermalNodeState
            for node_state in self.node_states
        ):
            raise TypeError(
                "node_states must contain only ThermalNodeState values"
            )
        for node_state in self.node_states:
            ThermalNodeState(node_state.node_id, node_state.temperature_k)
        node_ids = tuple(node_state.node_id for node_state in self.node_states)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("thermal node state IDs must be unique")


@dataclass(slots=True)
class OnboardOperationsState:
    """Authoritative onboard activity, FDIR, and accepted-authority state."""

    operational_mode: OperationalMode
    fdir_state: FDIRState
    accepted_plan_id: PlanId | None
    accepted_authority_id: AuthorityId | None
    last_qualifying_contact_time_seconds: int | None
    critical_energy_since_seconds: int | None

    def __post_init__(self) -> None:
        if type(self.operational_mode) is not OperationalMode:
            raise TypeError("operational_mode must be an OperationalMode")
        if type(self.fdir_state) is not FDIRState:
            raise TypeError("fdir_state must be an FDIRState")
        if (
            self.accepted_plan_id is not None
            and type(self.accepted_plan_id) is not PlanId
        ):
            raise TypeError("accepted_plan_id must be a PlanId or None")
        if (
            self.accepted_authority_id is not None
            and type(self.accepted_authority_id) is not AuthorityId
        ):
            raise TypeError(
                "accepted_authority_id must be an AuthorityId or None"
            )
        _validate_optional_timestamp(
            "last_qualifying_contact_time_seconds",
            self.last_qualifying_contact_time_seconds,
        )
        _validate_optional_timestamp(
            "critical_energy_since_seconds",
            self.critical_energy_since_seconds,
        )


@dataclass(slots=True)
class DataStorageState:
    """Authoritative ordered onboard acquisition-data records."""

    stored_records: tuple[OnboardAcquisitionDataRecord, ...]

    def __post_init__(self) -> None:
        if type(self.stored_records) is not tuple:
            raise TypeError("stored_records must be a built-in tuple")
        if not all(
            type(record) is OnboardAcquisitionDataRecord
            for record in self.stored_records
        ):
            raise TypeError(
                "stored_records must contain only "
                "OnboardAcquisitionDataRecord values"
            )
        for record in self.stored_records:
            OnboardAcquisitionDataRecord(
                record.record_id,
                record.imaging_request_id,
                record.observation_opportunity_id,
                record.scheduled_start_seconds,
                record.acquisition_duration_seconds,
                record.channel_selection,
                record.uncompressed_equivalent_bits,
                record.stored_equivalent_bits,
            )
        record_ids = tuple(record.record_id for record in self.stored_records)
        if len(set(record_ids)) != len(record_ids):
            raise ValueError("stored record IDs must be unique")


@dataclass(slots=True)
class SpacecraftState:
    """Aggregate only authoritative spacecraft and onboard truth."""

    battery: BatteryState
    propulsion: PropulsionState
    thermal: ThermalState
    degradation: DegradationState
    onboard: OnboardOperationsState
    data_storage: DataStorageState

    def __post_init__(self) -> None:
        if type(self.battery) is not BatteryState:
            raise TypeError("battery must be a BatteryState")
        if type(self.propulsion) is not PropulsionState:
            raise TypeError("propulsion must be a PropulsionState")
        if type(self.thermal) is not ThermalState:
            raise TypeError("thermal must be a ThermalState")
        if type(self.degradation) is not DegradationState:
            raise TypeError("degradation must be a DegradationState")
        if type(self.onboard) is not OnboardOperationsState:
            raise TypeError("onboard must be an OnboardOperationsState")
        if type(self.data_storage) is not DataStorageState:
            raise TypeError("data_storage must be a DataStorageState")
        DataStorageState(self.data_storage.stored_records)


__all__ = [
    "BatteryDegradationState",
    "BatteryState",
    "DataStorageState",
    "DegradationState",
    "FDIRState",
    "OnboardOperationsState",
    "OperationalMode",
    "PropulsionState",
    "SpacecraftState",
    "SolarDegradationState",
    "ThermalNodeState",
    "ThermalState",
]
