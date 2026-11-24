"""Portable immutable checkpoints for completed V5 simulation steps."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Integral, Real
from typing import TypeVar

from .communications import ServiceableGroundContact
from .context import SimulationContext, SimulationInputs, _validate_inputs
from .controller_state import ControllerState
from .data_delivery import (
    CompletedAcquisitionDelivery,
    DownlinkTransferProgress,
    GroundDataDeliveryState,
    _validate_delivery_state_against_storage_and_time,
)
from .diagnostics import Diagnostics
from .ids import (
    AcquisitionDataRecordId,
    AuthorityId,
    CommandId,
    ControllerId,
    DataProductId,
    EnvironmentId,
    FlightRulesId,
    GroundContactId,
    GroundStationId,
    ImagingRequestId,
    MissionRequestId,
    ModelManifestId,
    NumericalConfigId,
    ObservationOpportunityId,
    PlanId,
    ScenarioId,
    SpacecraftConfigurationId,
    StableId,
    TelemetrySnapshotId,
    ThermalNodeId,
    WorldEventId,
    WorldId,
)
from .knowledge import GroundKnowledgeState, TelemetrySnapshot
from .mission import MissionState
from .onboard_data import OnboardAcquisitionDataRecord
from .payload import OpticalAcquisitionChannelSelection
from .state import (
    BatteryDegradationState,
    BatteryState,
    DataStorageState,
    DegradationState,
    FDIRState,
    OnboardOperationsState,
    OperationalMode,
    PropulsionState,
    SolarDegradationState,
    SpacecraftState,
    ThermalNodeState,
    ThermalState,
)


CURRENT_CHECKPOINT_SCHEMA_VERSION = 5

_StableIdType = TypeVar("_StableIdType", bound=StableId)
_EnumType = TypeVar("_EnumType", bound=Enum)


def _validate_timestamp_not_future(
    name: str,
    value: int | None,
    simulation_time_seconds: int,
) -> None:
    if value is not None and value > simulation_time_seconds:
        raise ValueError(f"{name} cannot be in the future")


def _json_numeric(value: object, name: str) -> int | float:
    """Return one admitted finite Real as a JSON-native numeric primitive."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = isfinite(value)
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} must be finite") from error
    if not finite:
        raise ValueError(f"{name} must be finite")
    try:
        if isinstance(value, Integral):
            normalized = int(value)
            if type(normalized) is not int:
                raise TypeError(f"{name} must normalize to a Python int")
            return normalized
        normalized = float(value)
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{name} cannot be represented as a JSON number"
        ) from error
    if not isfinite(normalized):
        raise ValueError(f"{name} cannot be represented as a JSON number")
    return normalized


@dataclass(frozen=True, slots=True)
class ThermalNodeStateSnapshot:
    """Immutable checkpoint value for one identified thermal node."""

    node_id: ThermalNodeId
    temperature_k: float

    def __post_init__(self) -> None:
        ThermalNodeState(self.node_id, self.temperature_k)

    @classmethod
    def from_state(
        cls, state: ThermalNodeState
    ) -> ThermalNodeStateSnapshot:
        """Capture one thermal node after validating its current values."""
        if type(state) is not ThermalNodeState:
            raise TypeError("state must be a ThermalNodeState")
        return cls(state.node_id, state.temperature_k)

    def restore(self) -> ThermalNodeState:
        """Create a fresh mutable thermal node state."""
        return ThermalNodeState(self.node_id, self.temperature_k)


@dataclass(frozen=True, slots=True)
class ThermalStateSnapshot:
    """Immutable checkpoint value for generic thermal runtime truth."""

    node_states: tuple[ThermalNodeStateSnapshot, ...]

    def __post_init__(self) -> None:
        if type(self.node_states) is not tuple:
            raise TypeError("node_states must be a tuple")
        if not self.node_states:
            raise ValueError("node_states must not be empty")
        if not all(
            type(node_state) is ThermalNodeStateSnapshot
            for node_state in self.node_states
        ):
            raise TypeError(
                "node_states must contain only ThermalNodeStateSnapshot values"
            )
        for node_state in self.node_states:
            ThermalNodeStateSnapshot(
                node_state.node_id,
                node_state.temperature_k,
            )
        node_ids = tuple(node_state.node_id for node_state in self.node_states)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("thermal node snapshot IDs must be unique")

    @classmethod
    def from_state(cls, state: ThermalState) -> ThermalStateSnapshot:
        """Capture thermal state after validating every current node."""
        if type(state) is not ThermalState:
            raise TypeError("state must be a ThermalState")
        ThermalState(state.node_states)
        return cls(
            tuple(
                ThermalNodeStateSnapshot.from_state(node_state)
                for node_state in state.node_states
            )
        )

    def restore(self) -> ThermalState:
        """Create fresh mutable thermal state and node objects."""
        return ThermalState(
            tuple(node_state.restore() for node_state in self.node_states)
        )


@dataclass(frozen=True, slots=True)
class BatteryDegradationStateSnapshot:
    """Immutable battery degradation truth for a portable checkpoint."""

    usable_capacity_retention: float
    cumulative_energy_throughput_wh: float

    def __post_init__(self) -> None:
        BatteryDegradationState(
            self.usable_capacity_retention,
            self.cumulative_energy_throughput_wh,
        )

    @classmethod
    def from_state(
        cls, state: BatteryDegradationState
    ) -> BatteryDegradationStateSnapshot:
        if type(state) is not BatteryDegradationState:
            raise TypeError("state must be a BatteryDegradationState")
        return cls(
            state.usable_capacity_retention,
            state.cumulative_energy_throughput_wh,
        )

    def restore(self) -> BatteryDegradationState:
        return BatteryDegradationState(
            self.usable_capacity_retention,
            self.cumulative_energy_throughput_wh,
        )


@dataclass(frozen=True, slots=True)
class SolarDegradationStateSnapshot:
    """Immutable solar degradation truth for a portable checkpoint."""

    generation_retention: float

    def __post_init__(self) -> None:
        SolarDegradationState(self.generation_retention)

    @classmethod
    def from_state(
        cls, state: SolarDegradationState
    ) -> SolarDegradationStateSnapshot:
        if type(state) is not SolarDegradationState:
            raise TypeError("state must be a SolarDegradationState")
        return cls(state.generation_retention)

    def restore(self) -> SolarDegradationState:
        return SolarDegradationState(self.generation_retention)


@dataclass(frozen=True, slots=True)
class DegradationStateSnapshot:
    """Immutable named physical degradation state."""

    battery: BatteryDegradationStateSnapshot
    solar: SolarDegradationStateSnapshot

    def __post_init__(self) -> None:
        if type(self.battery) is not BatteryDegradationStateSnapshot:
            raise TypeError(
                "battery must be a BatteryDegradationStateSnapshot"
            )
        if type(self.solar) is not SolarDegradationStateSnapshot:
            raise TypeError("solar must be a SolarDegradationStateSnapshot")
        BatteryDegradationStateSnapshot(
            self.battery.usable_capacity_retention,
            self.battery.cumulative_energy_throughput_wh,
        )
        SolarDegradationStateSnapshot(self.solar.generation_retention)

    @classmethod
    def from_state(cls, state: DegradationState) -> DegradationStateSnapshot:
        if type(state) is not DegradationState:
            raise TypeError("state must be a DegradationState")
        DegradationState(state.battery, state.solar)
        return cls(
            BatteryDegradationStateSnapshot.from_state(state.battery),
            SolarDegradationStateSnapshot.from_state(state.solar),
        )

    def restore(self) -> DegradationState:
        return DegradationState(
            self.battery.restore(),
            self.solar.restore(),
        )


@dataclass(frozen=True, slots=True)
class DataStorageStateSnapshot:
    """Immutable checkpoint value for ordered onboard data records."""

    stored_records: tuple[OnboardAcquisitionDataRecord, ...]

    def __post_init__(self) -> None:
        DataStorageState(self.stored_records)

    @classmethod
    def from_state(cls, state: DataStorageState) -> DataStorageStateSnapshot:
        """Capture persistent records after validating current storage state."""
        if type(state) is not DataStorageState:
            raise TypeError("state must be a DataStorageState")
        DataStorageState(state.stored_records)
        return cls(state.stored_records)

    def restore(self) -> DataStorageState:
        """Create a fresh mutable storage-state peer."""
        return DataStorageState(self.stored_records)


@dataclass(frozen=True, slots=True)
class SpacecraftStateSnapshot:
    """Immutable copy of all authoritative spacecraft runtime state."""

    battery_energy_wh: float
    delta_v_remaining_m_per_s: float
    thermal: ThermalStateSnapshot
    degradation: DegradationStateSnapshot
    operational_mode: OperationalMode
    fdir_state: FDIRState
    accepted_plan_id: PlanId | None
    accepted_authority_id: AuthorityId | None
    last_qualifying_contact_time_seconds: int | None
    critical_energy_since_seconds: int | None
    data_storage: DataStorageStateSnapshot

    def __post_init__(self) -> None:
        BatteryState(self.battery_energy_wh)
        PropulsionState(self.delta_v_remaining_m_per_s)
        if type(self.thermal) is not ThermalStateSnapshot:
            raise TypeError("thermal must be a ThermalStateSnapshot")
        ThermalStateSnapshot(self.thermal.node_states)
        if type(self.degradation) is not DegradationStateSnapshot:
            raise TypeError("degradation must be a DegradationStateSnapshot")
        DegradationStateSnapshot(
            self.degradation.battery,
            self.degradation.solar,
        )
        OnboardOperationsState(
            self.operational_mode,
            self.fdir_state,
            self.accepted_plan_id,
            self.accepted_authority_id,
            self.last_qualifying_contact_time_seconds,
            self.critical_energy_since_seconds,
        )
        if type(self.data_storage) is not DataStorageStateSnapshot:
            raise TypeError(
                "data_storage must be a DataStorageStateSnapshot"
            )
        DataStorageStateSnapshot(self.data_storage.stored_records)

    @classmethod
    def from_state(cls, state: SpacecraftState) -> SpacecraftStateSnapshot:
        """Capture one spacecraft state after validating its current values."""
        if type(state) is not SpacecraftState:
            raise TypeError("state must be a SpacecraftState")
        if type(state.battery) is not BatteryState:
            raise TypeError("state.battery must be a BatteryState")
        if type(state.propulsion) is not PropulsionState:
            raise TypeError("state.propulsion must be a PropulsionState")
        if type(state.thermal) is not ThermalState:
            raise TypeError("state.thermal must be a ThermalState")
        if type(state.degradation) is not DegradationState:
            raise TypeError("state.degradation must be a DegradationState")
        if type(state.onboard) is not OnboardOperationsState:
            raise TypeError("state.onboard must be an OnboardOperationsState")
        if type(state.data_storage) is not DataStorageState:
            raise TypeError("state.data_storage must be a DataStorageState")
        return cls(
            state.battery.energy_wh,
            state.propulsion.delta_v_remaining_m_per_s,
            ThermalStateSnapshot.from_state(state.thermal),
            DegradationStateSnapshot.from_state(state.degradation),
            state.onboard.operational_mode,
            state.onboard.fdir_state,
            state.onboard.accepted_plan_id,
            state.onboard.accepted_authority_id,
            state.onboard.last_qualifying_contact_time_seconds,
            state.onboard.critical_energy_since_seconds,
            DataStorageStateSnapshot.from_state(state.data_storage),
        )

    def restore(self) -> SpacecraftState:
        """Create a fresh mutable spacecraft state from this snapshot."""
        return SpacecraftState(
            BatteryState(self.battery_energy_wh),
            PropulsionState(self.delta_v_remaining_m_per_s),
            self.thermal.restore(),
            self.degradation.restore(),
            OnboardOperationsState(
                self.operational_mode,
                self.fdir_state,
                self.accepted_plan_id,
                self.accepted_authority_id,
                self.last_qualifying_contact_time_seconds,
                self.critical_energy_since_seconds,
            ),
            self.data_storage.restore(),
        )


@dataclass(frozen=True, slots=True)
class GroundKnowledgeSnapshot:
    """Immutable copy of explicit ground knowledge."""

    latest_telemetry: TelemetrySnapshot | None
    known_world_event_ids: tuple[WorldEventId, ...]

    def __post_init__(self) -> None:
        GroundKnowledgeState(
            self.latest_telemetry,
            self.known_world_event_ids,
        )

    @classmethod
    def from_state(
        cls, state: GroundKnowledgeState
    ) -> GroundKnowledgeSnapshot:
        """Capture ground knowledge after validating its current values."""
        if type(state) is not GroundKnowledgeState:
            raise TypeError("state must be a GroundKnowledgeState")
        return cls(state.latest_telemetry, state.known_world_event_ids)

    def restore(self) -> GroundKnowledgeState:
        """Create fresh mutable ground knowledge from this snapshot."""
        return GroundKnowledgeState(
            self.latest_telemetry,
            self.known_world_event_ids,
        )


@dataclass(frozen=True, slots=True)
class GroundDataDeliveryStateSnapshot:
    """Immutable checkpoint value for ordered ground delivery truth."""

    partial_transfers: tuple[DownlinkTransferProgress, ...]
    completed_deliveries: tuple[CompletedAcquisitionDelivery, ...]

    def __post_init__(self) -> None:
        GroundDataDeliveryState(
            self.partial_transfers,
            self.completed_deliveries,
        )

    @classmethod
    def from_state(
        cls,
        state: GroundDataDeliveryState,
    ) -> GroundDataDeliveryStateSnapshot:
        """Capture delivery truth after validating current local values."""
        if type(state) is not GroundDataDeliveryState:
            raise TypeError("state must be a GroundDataDeliveryState")
        GroundDataDeliveryState(
            state.partial_transfers,
            state.completed_deliveries,
        )
        return cls(state.partial_transfers, state.completed_deliveries)

    def restore(self) -> GroundDataDeliveryState:
        """Create a fresh mutable ground-delivery state peer."""
        return GroundDataDeliveryState(
            self.partial_transfers,
            self.completed_deliveries,
        )


@dataclass(frozen=True, slots=True)
class MissionStateSnapshot:
    """Immutable copy of all authoritative mission identity state."""

    pending_request_ids: tuple[MissionRequestId, ...]
    completed_request_ids: tuple[MissionRequestId, ...]
    data_product_ids: tuple[DataProductId, ...]
    active_plan_id: PlanId | None
    command_ids: tuple[CommandId, ...]
    resolved_world_event_ids: tuple[WorldEventId, ...]

    def __post_init__(self) -> None:
        MissionState(
            self.pending_request_ids,
            self.completed_request_ids,
            self.data_product_ids,
            self.active_plan_id,
            self.command_ids,
            self.resolved_world_event_ids,
        )

    @classmethod
    def from_state(cls, state: MissionState) -> MissionStateSnapshot:
        """Capture mission state after validating its current values."""
        if type(state) is not MissionState:
            raise TypeError("state must be a MissionState")
        return cls(
            state.pending_request_ids,
            state.completed_request_ids,
            state.data_product_ids,
            state.active_plan_id,
            state.command_ids,
            state.resolved_world_event_ids,
        )

    def restore(self) -> MissionState:
        """Create fresh mutable mission state from this snapshot."""
        return MissionState(
            self.pending_request_ids,
            self.completed_request_ids,
            self.data_product_ids,
            self.active_plan_id,
            self.command_ids,
            self.resolved_world_event_ids,
        )


@dataclass(frozen=True, slots=True)
class ControllerStateSnapshot:
    """Immutable copy of authoritative planner memory."""

    controller_id: ControllerId
    latest_plan_id: PlanId | None
    replan_count: int

    def __post_init__(self) -> None:
        ControllerState(
            self.controller_id,
            self.latest_plan_id,
            self.replan_count,
        )

    @classmethod
    def from_state(
        cls, state: ControllerState
    ) -> ControllerStateSnapshot:
        """Capture controller state after validating its current values."""
        if type(state) is not ControllerState:
            raise TypeError("state must be a ControllerState")
        return cls(
            state.controller_id,
            state.latest_plan_id,
            state.replan_count,
        )

    def restore(self) -> ControllerState:
        """Create fresh mutable controller state from this snapshot."""
        return ControllerState(
            self.controller_id,
            self.latest_plan_id,
            self.replan_count,
        )


@dataclass(frozen=True, slots=True)
class DiagnosticsSnapshot:
    """Immutable copy of cumulative non-causal diagnostics."""

    completed_steps: int

    def __post_init__(self) -> None:
        Diagnostics(self.completed_steps)

    @classmethod
    def from_state(cls, state: Diagnostics) -> DiagnosticsSnapshot:
        """Capture diagnostics after validating its current value."""
        if type(state) is not Diagnostics:
            raise TypeError("state must be Diagnostics")
        return cls(state.completed_steps)

    def restore(self) -> Diagnostics:
        """Create fresh mutable diagnostics from this snapshot."""
        return Diagnostics(self.completed_steps)


@dataclass(frozen=True, slots=True)
class CheckpointState:
    """Portable completed-step snapshot plus stable immutable-input identity."""

    schema_version: int
    simulation_time_seconds: int
    model_manifest_id: ModelManifestId
    spacecraft_configuration_id: SpacecraftConfigurationId
    numerical_config_id: NumericalConfigId
    environment_id: EnvironmentId
    flight_rules_id: FlightRulesId
    scenario_id: ScenarioId
    world_id: WorldId
    controller_id: ControllerId
    spacecraft: SpacecraftStateSnapshot
    ground_knowledge: GroundKnowledgeSnapshot
    ground_data_delivery: GroundDataDeliveryStateSnapshot
    mission: MissionStateSnapshot
    controller: ControllerStateSnapshot
    diagnostics: DiagnosticsSnapshot

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise TypeError("schema_version must be an integer")
        if self.schema_version != CURRENT_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError(
                "unsupported checkpoint schema_version "
                f"{self.schema_version}; expected "
                f"{CURRENT_CHECKPOINT_SCHEMA_VERSION}"
            )
        if type(self.simulation_time_seconds) is not int:
            raise TypeError("simulation_time_seconds must be an integer")
        if self.simulation_time_seconds < 0:
            raise ValueError(
                "simulation_time_seconds must be greater than or equal to zero"
            )
        id_contracts = (
            ("model_manifest_id", self.model_manifest_id, ModelManifestId),
            (
                "spacecraft_configuration_id",
                self.spacecraft_configuration_id,
                SpacecraftConfigurationId,
            ),
            (
                "numerical_config_id",
                self.numerical_config_id,
                NumericalConfigId,
            ),
            ("environment_id", self.environment_id, EnvironmentId),
            ("flight_rules_id", self.flight_rules_id, FlightRulesId),
            ("scenario_id", self.scenario_id, ScenarioId),
            ("world_id", self.world_id, WorldId),
            ("controller_id", self.controller_id, ControllerId),
        )
        for field_name, value, expected_type in id_contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )
        snapshot_contracts = (
            ("spacecraft", self.spacecraft, SpacecraftStateSnapshot),
            (
                "ground_knowledge",
                self.ground_knowledge,
                GroundKnowledgeSnapshot,
            ),
            (
                "ground_data_delivery",
                self.ground_data_delivery,
                GroundDataDeliveryStateSnapshot,
            ),
            ("mission", self.mission, MissionStateSnapshot),
            ("controller", self.controller, ControllerStateSnapshot),
            ("diagnostics", self.diagnostics, DiagnosticsSnapshot),
        )
        for field_name, value, expected_type in snapshot_contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )
        if self.controller.controller_id != self.controller_id:
            raise ValueError("checkpoint controller identity mismatch")
        _validate_timestamp_not_future(
            "last qualifying contact time",
            self.spacecraft.last_qualifying_contact_time_seconds,
            self.simulation_time_seconds,
        )
        _validate_timestamp_not_future(
            "critical energy start time",
            self.spacecraft.critical_energy_since_seconds,
            self.simulation_time_seconds,
        )
        telemetry = self.ground_knowledge.latest_telemetry
        if telemetry is not None:
            _validate_timestamp_not_future(
                "telemetry sample time",
                telemetry.sampled_at_seconds,
                self.simulation_time_seconds,
            )
            _validate_timestamp_not_future(
                "telemetry receipt time",
                telemetry.received_at_seconds,
                self.simulation_time_seconds,
            )
        _validate_delivery_state_against_storage_and_time(
            self.ground_data_delivery.restore(),
            self.spacecraft.data_storage.stored_records,
            self.simulation_time_seconds,
        )

    @classmethod
    def from_context(cls, context: SimulationContext) -> CheckpointState:
        """Capture every authoritative domain at a completed-step boundary."""
        if type(context) is not SimulationContext:
            raise TypeError("context must be a SimulationContext")
        # Reconstruct the completed-context contract so mutable runtime values
        # receive all authoritative cross-domain validation before capture.
        SimulationContext(
            context.simulation_time_seconds,
            context.inputs,
            context.spacecraft_state,
            context.ground_knowledge_state,
            context.ground_data_delivery_state,
            context.mission_state,
            context.controller_state,
            context.diagnostics,
        )
        manifest = context.inputs.model_manifest
        return cls(
            CURRENT_CHECKPOINT_SCHEMA_VERSION,
            context.simulation_time_seconds,
            manifest.manifest_id,
            manifest.spacecraft_configuration_id,
            manifest.numerical_config_id,
            manifest.environment_id,
            manifest.flight_rules_id,
            manifest.scenario_id,
            manifest.world_id,
            manifest.controller_id,
            SpacecraftStateSnapshot.from_state(context.spacecraft_state),
            GroundKnowledgeSnapshot.from_state(
                context.ground_knowledge_state
            ),
            GroundDataDeliveryStateSnapshot.from_state(
                context.ground_data_delivery_state
            ),
            MissionStateSnapshot.from_state(context.mission_state),
            ControllerStateSnapshot.from_state(context.controller_state),
            DiagnosticsSnapshot.from_state(context.diagnostics),
        )

    def restore(self, inputs: SimulationInputs) -> SimulationContext:
        """Restore fresh mutable runtime state using matching immutable inputs."""
        if type(inputs) is not SimulationInputs:
            raise TypeError("inputs must be SimulationInputs")
        # Check the current content binding before any mutable snapshot restore.
        _validate_inputs(inputs)
        manifest = inputs.model_manifest
        identity_contracts = (
            ("model manifest", self.model_manifest_id, manifest.manifest_id),
            (
                "spacecraft configuration",
                self.spacecraft_configuration_id,
                manifest.spacecraft_configuration_id,
            ),
            (
                "numerical configuration",
                self.numerical_config_id,
                manifest.numerical_config_id,
            ),
            ("environment", self.environment_id, manifest.environment_id),
            ("flight rules", self.flight_rules_id, manifest.flight_rules_id),
            ("scenario", self.scenario_id, manifest.scenario_id),
            ("world", self.world_id, manifest.world_id),
            ("controller", self.controller_id, manifest.controller_id),
        )
        for name, actual, expected in identity_contracts:
            if actual != expected:
                raise ValueError(f"{name} identity mismatch")
        # Construction applies the authoritative completed-context contract,
        # including invariants that depend on the supplied immutable inputs.
        return SimulationContext(
            self.simulation_time_seconds,
            inputs,
            self.spacecraft.restore(),
            self.ground_knowledge.restore(),
            self.ground_data_delivery.restore(),
            self.mission.restore(),
            self.controller.restore(),
            self.diagnostics.restore(),
        )

    def to_dict(self) -> dict[str, object]:
        """Return the fixed JSON-safe portable checkpoint representation."""
        telemetry = self.ground_knowledge.latest_telemetry
        telemetry_payload = (
            None
            if telemetry is None
            else {
                "snapshot_id": telemetry.snapshot_id.canonical,
                "sampled_at_seconds": telemetry.sampled_at_seconds,
                "received_at_seconds": telemetry.received_at_seconds,
                "battery_energy_wh": _json_numeric(
                    telemetry.battery_energy_wh,
                    "telemetry battery_energy_wh",
                ),
                "delta_v_remaining_m_per_s": (
                    _json_numeric(
                        telemetry.delta_v_remaining_m_per_s,
                        "telemetry delta_v_remaining_m_per_s",
                    )
                ),
                "operational_mode": telemetry.operational_mode.value,
            }
        )
        return {
            "schema_version": self.schema_version,
            "simulation_time_seconds": self.simulation_time_seconds,
            "input_ids": {
                "model_manifest_id": self.model_manifest_id.canonical,
                "spacecraft_configuration_id": (
                    self.spacecraft_configuration_id.canonical
                ),
                "numerical_config_id": self.numerical_config_id.canonical,
                "environment_id": self.environment_id.canonical,
                "flight_rules_id": self.flight_rules_id.canonical,
                "scenario_id": self.scenario_id.canonical,
                "world_id": self.world_id.canonical,
                "controller_id": self.controller_id.canonical,
            },
            "spacecraft": {
                "battery_energy_wh": _json_numeric(
                    self.spacecraft.battery_energy_wh,
                    "spacecraft battery_energy_wh",
                ),
                "delta_v_remaining_m_per_s": (
                    _json_numeric(
                        self.spacecraft.delta_v_remaining_m_per_s,
                        "spacecraft delta_v_remaining_m_per_s",
                    )
                ),
                "thermal": {
                    "nodes": [
                        {
                            "node_id": node_state.node_id.canonical,
                            "temperature_k": _json_numeric(
                                node_state.temperature_k,
                                "thermal temperature_k",
                            ),
                        }
                        for node_state in self.spacecraft.thermal.node_states
                    ]
                },
                "degradation": {
                    "battery": {
                        "usable_capacity_retention": _json_numeric(
                            self.spacecraft.degradation.battery
                            .usable_capacity_retention,
                            "battery usable_capacity_retention",
                        ),
                        "cumulative_energy_throughput_wh": _json_numeric(
                            self.spacecraft.degradation.battery
                            .cumulative_energy_throughput_wh,
                            "battery cumulative_energy_throughput_wh",
                        ),
                    },
                    "solar": {
                        "generation_retention": _json_numeric(
                            self.spacecraft.degradation.solar
                            .generation_retention,
                            "solar generation_retention",
                        )
                    },
                },
                "operational_mode": self.spacecraft.operational_mode.value,
                "fdir_state": self.spacecraft.fdir_state.value,
                "accepted_plan_id": _optional_id_to_text(
                    self.spacecraft.accepted_plan_id
                ),
                "accepted_authority_id": _optional_id_to_text(
                    self.spacecraft.accepted_authority_id
                ),
                "last_qualifying_contact_time_seconds": (
                    self.spacecraft.last_qualifying_contact_time_seconds
                ),
                "critical_energy_since_seconds": (
                    self.spacecraft.critical_energy_since_seconds
                ),
                "data_storage": {
                    "stored_records": [
                        _acquisition_record_to_dict(
                            record,
                            "spacecraft.data_storage.stored record",
                        )
                        for record in (
                            self.spacecraft.data_storage.stored_records
                        )
                    ]
                },
            },
            "ground_knowledge": {
                "latest_telemetry": telemetry_payload,
                "known_world_event_ids": [
                    item.canonical
                    for item in self.ground_knowledge.known_world_event_ids
                ],
            },
            "ground_data_delivery": {
                "partial_transfers": [
                    {
                        "record_id": progress.record_id.canonical,
                        "transmitted_equivalent_bits": _json_numeric(
                            progress.transmitted_equivalent_bits,
                            "partial transfer transmitted_equivalent_bits",
                        ),
                    }
                    for progress in (
                        self.ground_data_delivery.partial_transfers
                    )
                ],
                "completed_deliveries": [
                    {
                        "record": _acquisition_record_to_dict(
                            delivery.record,
                            "completed delivery record",
                        ),
                        "completing_contact": _serviceable_contact_to_dict(
                            delivery.completing_contact,
                        ),
                    }
                    for delivery in (
                        self.ground_data_delivery.completed_deliveries
                    )
                ],
            },
            "mission": {
                "pending_request_ids": [
                    item.canonical for item in self.mission.pending_request_ids
                ],
                "completed_request_ids": [
                    item.canonical
                    for item in self.mission.completed_request_ids
                ],
                "data_product_ids": [
                    item.canonical for item in self.mission.data_product_ids
                ],
                "active_plan_id": _optional_id_to_text(
                    self.mission.active_plan_id
                ),
                "command_ids": [
                    item.canonical for item in self.mission.command_ids
                ],
                "resolved_world_event_ids": [
                    item.canonical
                    for item in self.mission.resolved_world_event_ids
                ],
            },
            "controller": {
                "controller_id": self.controller.controller_id.canonical,
                "latest_plan_id": _optional_id_to_text(
                    self.controller.latest_plan_id
                ),
                "replan_count": self.controller.replan_count,
            },
            "diagnostics": {
                "completed_steps": self.diagnostics.completed_steps,
            },
        }

    @classmethod
    def from_dict(cls, payload: object) -> CheckpointState:
        """Strictly parse the fixed portable checkpoint representation."""
        if type(payload) is not dict:
            raise TypeError("checkpoint must be a dict")
        if "schema_version" not in payload:
            raise ValueError("checkpoint must contain schema_version")
        schema_version = _require_int(
            payload["schema_version"],
            "schema_version",
        )
        if schema_version != CURRENT_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError(
                "unsupported checkpoint schema_version "
                f"{schema_version}; expected "
                f"{CURRENT_CHECKPOINT_SCHEMA_VERSION}"
            )
        root = _require_dict(
            payload,
            "checkpoint",
            (
                "schema_version",
                "simulation_time_seconds",
                "input_ids",
                "spacecraft",
                "ground_knowledge",
                "ground_data_delivery",
                "mission",
                "controller",
                "diagnostics",
            ),
        )
        input_ids = _require_dict(
            root["input_ids"],
            "input_ids",
            (
                "model_manifest_id",
                "spacecraft_configuration_id",
                "numerical_config_id",
                "environment_id",
                "flight_rules_id",
                "scenario_id",
                "world_id",
                "controller_id",
            ),
        )
        spacecraft_payload = _require_dict(
            root["spacecraft"],
            "spacecraft",
            (
                "battery_energy_wh",
                "delta_v_remaining_m_per_s",
                "thermal",
                "degradation",
                "operational_mode",
                "fdir_state",
                "accepted_plan_id",
                "accepted_authority_id",
                "last_qualifying_contact_time_seconds",
                "critical_energy_since_seconds",
                "data_storage",
            ),
        )
        thermal_payload = _require_dict(
            spacecraft_payload["thermal"],
            "spacecraft.thermal",
            ("nodes",),
        )
        degradation_payload = _require_dict(
            spacecraft_payload["degradation"],
            "spacecraft.degradation",
            ("battery", "solar"),
        )
        battery_degradation_payload = _require_dict(
            degradation_payload["battery"],
            "spacecraft.degradation.battery",
            (
                "usable_capacity_retention",
                "cumulative_energy_throughput_wh",
            ),
        )
        solar_degradation_payload = _require_dict(
            degradation_payload["solar"],
            "spacecraft.degradation.solar",
            ("generation_retention",),
        )
        data_storage_payload = _require_dict(
            spacecraft_payload["data_storage"],
            "spacecraft.data_storage",
            ("stored_records",),
        )
        ground_payload = _require_dict(
            root["ground_knowledge"],
            "ground_knowledge",
            ("latest_telemetry", "known_world_event_ids"),
        )
        ground_data_delivery_payload = _require_dict(
            root["ground_data_delivery"],
            "ground_data_delivery",
            ("partial_transfers", "completed_deliveries"),
        )
        mission_payload = _require_dict(
            root["mission"],
            "mission",
            (
                "pending_request_ids",
                "completed_request_ids",
                "data_product_ids",
                "active_plan_id",
                "command_ids",
                "resolved_world_event_ids",
            ),
        )
        controller_payload = _require_dict(
            root["controller"],
            "controller",
            ("controller_id", "latest_plan_id", "replan_count"),
        )
        diagnostics_payload = _require_dict(
            root["diagnostics"],
            "diagnostics",
            ("completed_steps",),
        )
        telemetry = _parse_telemetry(ground_payload["latest_telemetry"])
        return cls(
            schema_version,
            _require_int(
                root["simulation_time_seconds"],
                "simulation_time_seconds",
            ),
            _parse_id(
                input_ids["model_manifest_id"],
                ModelManifestId,
                "model_manifest_id",
            ),
            _parse_id(
                input_ids["spacecraft_configuration_id"],
                SpacecraftConfigurationId,
                "spacecraft_configuration_id",
            ),
            _parse_id(
                input_ids["numerical_config_id"],
                NumericalConfigId,
                "numerical_config_id",
            ),
            _parse_id(
                input_ids["environment_id"],
                EnvironmentId,
                "environment_id",
            ),
            _parse_id(
                input_ids["flight_rules_id"],
                FlightRulesId,
                "flight_rules_id",
            ),
            _parse_id(input_ids["scenario_id"], ScenarioId, "scenario_id"),
            _parse_id(input_ids["world_id"], WorldId, "world_id"),
            _parse_id(
                input_ids["controller_id"],
                ControllerId,
                "controller_id",
            ),
            SpacecraftStateSnapshot(
                spacecraft_payload["battery_energy_wh"],
                spacecraft_payload["delta_v_remaining_m_per_s"],
                _parse_thermal_state_snapshot(thermal_payload),
                DegradationStateSnapshot(
                    BatteryDegradationStateSnapshot(
                        battery_degradation_payload[
                            "usable_capacity_retention"
                        ],
                        battery_degradation_payload[
                            "cumulative_energy_throughput_wh"
                        ],
                    ),
                    SolarDegradationStateSnapshot(
                        solar_degradation_payload["generation_retention"]
                    ),
                ),
                _parse_enum(
                    spacecraft_payload["operational_mode"],
                    OperationalMode,
                    "operational_mode",
                ),
                _parse_enum(
                    spacecraft_payload["fdir_state"],
                    FDIRState,
                    "fdir_state",
                ),
                _parse_optional_id(
                    spacecraft_payload["accepted_plan_id"],
                    PlanId,
                    "accepted_plan_id",
                ),
                _parse_optional_id(
                    spacecraft_payload["accepted_authority_id"],
                    AuthorityId,
                    "accepted_authority_id",
                ),
                _require_optional_int(
                    spacecraft_payload[
                        "last_qualifying_contact_time_seconds"
                    ],
                    "last_qualifying_contact_time_seconds",
                ),
                _require_optional_int(
                    spacecraft_payload["critical_energy_since_seconds"],
                    "critical_energy_since_seconds",
                ),
                _parse_data_storage_state_snapshot(data_storage_payload),
            ),
            GroundKnowledgeSnapshot(
                telemetry,
                _parse_id_list(
                    ground_payload["known_world_event_ids"],
                    WorldEventId,
                    "known_world_event_ids",
                ),
            ),
            _parse_ground_data_delivery_state_snapshot(
                ground_data_delivery_payload
            ),
            MissionStateSnapshot(
                _parse_id_list(
                    mission_payload["pending_request_ids"],
                    MissionRequestId,
                    "pending_request_ids",
                ),
                _parse_id_list(
                    mission_payload["completed_request_ids"],
                    MissionRequestId,
                    "completed_request_ids",
                ),
                _parse_id_list(
                    mission_payload["data_product_ids"],
                    DataProductId,
                    "data_product_ids",
                ),
                _parse_optional_id(
                    mission_payload["active_plan_id"],
                    PlanId,
                    "active_plan_id",
                ),
                _parse_id_list(
                    mission_payload["command_ids"],
                    CommandId,
                    "command_ids",
                ),
                _parse_id_list(
                    mission_payload["resolved_world_event_ids"],
                    WorldEventId,
                    "resolved_world_event_ids",
                ),
            ),
            ControllerStateSnapshot(
                _parse_id(
                    controller_payload["controller_id"],
                    ControllerId,
                    "controller.controller_id",
                ),
                _parse_optional_id(
                    controller_payload["latest_plan_id"],
                    PlanId,
                    "latest_plan_id",
                ),
                _require_int(
                    controller_payload["replan_count"],
                    "replan_count",
                ),
            ),
            DiagnosticsSnapshot(
                _require_int(
                    diagnostics_payload["completed_steps"],
                    "completed_steps",
                )
            ),
        )


def _optional_id_to_text(value: StableId | None) -> str | None:
    return None if value is None else value.canonical


def _acquisition_record_to_dict(
    record: OnboardAcquisitionDataRecord,
    name: str,
) -> dict[str, object]:
    return {
        "record_id": record.record_id.canonical,
        "imaging_request_id": record.imaging_request_id.canonical,
        "observation_opportunity_id": (
            record.observation_opportunity_id.canonical
        ),
        "scheduled_start_seconds": record.scheduled_start_seconds,
        "acquisition_duration_seconds": record.acquisition_duration_seconds,
        "channel_selection": record.channel_selection.value,
        "uncompressed_equivalent_bits": _json_numeric(
            record.uncompressed_equivalent_bits,
            f"{name} uncompressed_equivalent_bits",
        ),
        "stored_equivalent_bits": _json_numeric(
            record.stored_equivalent_bits,
            f"{name} stored_equivalent_bits",
        ),
    }


def _serviceable_contact_to_dict(
    contact: ServiceableGroundContact,
) -> dict[str, object]:
    return {
        "contact_id": contact.contact_id.canonical,
        "ground_station_id": contact.ground_station_id.canonical,
        "start_time_seconds": contact.start_time_seconds,
        "end_time_seconds": contact.end_time_seconds,
    }


def _require_dict(
    value: object,
    name: str,
    expected_keys: tuple[str, ...],
) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{name} must be a dict")
    if set(value) != set(expected_keys):
        missing = sorted(set(expected_keys) - set(value))
        extra = sorted(set(value) - set(expected_keys))
        raise ValueError(
            f"{name} has invalid keys; missing={missing}, extra={extra}"
        )
    return value


def _require_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return value


def _require_optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, name)


def _require_float(value: object, name: str) -> float:
    if type(value) is not float:
        raise TypeError(f"{name} must be a built-in float")
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _parse_id(
    value: object,
    id_type: type[_StableIdType],
    name: str,
) -> _StableIdType:
    if type(value) is not str:
        raise TypeError(f"{name} must be a canonical identifier string")
    return id_type.from_canonical(value)


def _parse_optional_id(
    value: object,
    id_type: type[_StableIdType],
    name: str,
) -> _StableIdType | None:
    if value is None:
        return None
    return _parse_id(value, id_type, name)


def _parse_id_list(
    value: object,
    id_type: type[_StableIdType],
    name: str,
) -> tuple[_StableIdType, ...]:
    if type(value) is not list:
        raise TypeError(f"{name} must be a list")
    return tuple(
        _parse_id(item, id_type, f"{name}[{index}]")
        for index, item in enumerate(value)
    )


def _parse_enum(
    value: object,
    enum_type: type[_EnumType],
    name: str,
) -> _EnumType:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    return enum_type(value)


def _parse_telemetry(value: object) -> TelemetrySnapshot | None:
    if value is None:
        return None
    payload = _require_dict(
        value,
        "latest_telemetry",
        (
            "snapshot_id",
            "sampled_at_seconds",
            "received_at_seconds",
            "battery_energy_wh",
            "delta_v_remaining_m_per_s",
            "operational_mode",
        ),
    )
    return TelemetrySnapshot(
        _parse_id(
            payload["snapshot_id"],
            TelemetrySnapshotId,
            "snapshot_id",
        ),
        _require_int(payload["sampled_at_seconds"], "sampled_at_seconds"),
        _require_int(payload["received_at_seconds"], "received_at_seconds"),
        payload["battery_energy_wh"],
        payload["delta_v_remaining_m_per_s"],
        _parse_enum(
            payload["operational_mode"],
            OperationalMode,
            "telemetry operational_mode",
        ),
    )


def _parse_thermal_state_snapshot(
    payload: dict[str, object],
) -> ThermalStateSnapshot:
    node_payloads = payload["nodes"]
    if type(node_payloads) is not list:
        raise TypeError("spacecraft.thermal.nodes must be a list")
    node_states = []
    for index, value in enumerate(node_payloads):
        node = _require_dict(
            value,
            f"spacecraft.thermal.nodes[{index}]",
            ("node_id", "temperature_k"),
        )
        node_states.append(
            ThermalNodeStateSnapshot(
                _parse_id(
                    node["node_id"],
                    ThermalNodeId,
                    f"thermal node_id[{index}]",
                ),
                node["temperature_k"],
            )
        )
    return ThermalStateSnapshot(tuple(node_states))


def _parse_data_storage_state_snapshot(
    payload: dict[str, object],
) -> DataStorageStateSnapshot:
    record_payloads = payload["stored_records"]
    if type(record_payloads) is not list:
        raise TypeError("spacecraft.data_storage.stored_records must be a list")
    records = []
    for index, value in enumerate(record_payloads):
        records.append(
            _parse_acquisition_record(
                value,
                f"spacecraft.data_storage.stored_records[{index}]",
            )
        )
    return DataStorageStateSnapshot(tuple(records))


def _parse_acquisition_record(
    value: object,
    name: str,
) -> OnboardAcquisitionDataRecord:
    payload = _require_dict(
        value,
        name,
        (
            "record_id",
            "imaging_request_id",
            "observation_opportunity_id",
            "scheduled_start_seconds",
            "acquisition_duration_seconds",
            "channel_selection",
            "uncompressed_equivalent_bits",
            "stored_equivalent_bits",
        ),
    )
    return OnboardAcquisitionDataRecord(
        _parse_id(
            payload["record_id"],
            AcquisitionDataRecordId,
            f"{name}.record_id",
        ),
        _parse_id(
            payload["imaging_request_id"],
            ImagingRequestId,
            f"{name}.imaging_request_id",
        ),
        _parse_id(
            payload["observation_opportunity_id"],
            ObservationOpportunityId,
            f"{name}.observation_opportunity_id",
        ),
        _require_int(
            payload["scheduled_start_seconds"],
            f"{name}.scheduled_start_seconds",
        ),
        _require_int(
            payload["acquisition_duration_seconds"],
            f"{name}.acquisition_duration_seconds",
        ),
        _parse_enum(
            payload["channel_selection"],
            OpticalAcquisitionChannelSelection,
            f"{name}.channel_selection",
        ),
        _require_float(
            payload["uncompressed_equivalent_bits"],
            f"{name}.uncompressed_equivalent_bits",
        ),
        _require_float(
            payload["stored_equivalent_bits"],
            f"{name}.stored_equivalent_bits",
        ),
    )


def _parse_serviceable_contact(
    value: object,
    name: str,
) -> ServiceableGroundContact:
    payload = _require_dict(
        value,
        name,
        (
            "contact_id",
            "ground_station_id",
            "start_time_seconds",
            "end_time_seconds",
        ),
    )
    return ServiceableGroundContact(
        _parse_id(
            payload["contact_id"],
            GroundContactId,
            f"{name}.contact_id",
        ),
        _parse_id(
            payload["ground_station_id"],
            GroundStationId,
            f"{name}.ground_station_id",
        ),
        _require_int(
            payload["start_time_seconds"],
            f"{name}.start_time_seconds",
        ),
        _require_int(
            payload["end_time_seconds"],
            f"{name}.end_time_seconds",
        ),
    )


def _parse_ground_data_delivery_state_snapshot(
    payload: dict[str, object],
) -> GroundDataDeliveryStateSnapshot:
    partial_payloads = payload["partial_transfers"]
    if type(partial_payloads) is not list:
        raise TypeError("ground_data_delivery.partial_transfers must be a list")
    partial_transfers = []
    for index, value in enumerate(partial_payloads):
        name = f"ground_data_delivery.partial_transfers[{index}]"
        progress_payload = _require_dict(
            value,
            name,
            ("record_id", "transmitted_equivalent_bits"),
        )
        partial_transfers.append(
            DownlinkTransferProgress(
                _parse_id(
                    progress_payload["record_id"],
                    AcquisitionDataRecordId,
                    f"{name}.record_id",
                ),
                _require_float(
                    progress_payload["transmitted_equivalent_bits"],
                    f"{name}.transmitted_equivalent_bits",
                ),
            )
        )

    completed_payloads = payload["completed_deliveries"]
    if type(completed_payloads) is not list:
        raise TypeError(
            "ground_data_delivery.completed_deliveries must be a list"
        )
    completed_deliveries = []
    for index, value in enumerate(completed_payloads):
        name = f"ground_data_delivery.completed_deliveries[{index}]"
        delivery_payload = _require_dict(
            value,
            name,
            ("record", "completing_contact"),
        )
        completed_deliveries.append(
            CompletedAcquisitionDelivery(
                _parse_acquisition_record(
                    delivery_payload["record"],
                    f"{name}.record",
                ),
                _parse_serviceable_contact(
                    delivery_payload["completing_contact"],
                    f"{name}.completing_contact",
                ),
            )
        )
    return GroundDataDeliveryStateSnapshot(
        tuple(partial_transfers),
        tuple(completed_deliveries),
    )


__all__ = [
    "BatteryDegradationStateSnapshot",
    "CURRENT_CHECKPOINT_SCHEMA_VERSION",
    "CheckpointState",
    "ControllerStateSnapshot",
    "DataStorageStateSnapshot",
    "DiagnosticsSnapshot",
    "DegradationStateSnapshot",
    "GroundDataDeliveryStateSnapshot",
    "GroundKnowledgeSnapshot",
    "MissionStateSnapshot",
    "SpacecraftStateSnapshot",
    "SolarDegradationStateSnapshot",
    "ThermalNodeStateSnapshot",
    "ThermalStateSnapshot",
]
