"""Stateless seconds-based execution skeleton for completed V5 steps."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import TypeVar

from .checkpoint import CheckpointState
from .communications import ServiceableGroundContact
from .context import SimulationContext, SimulationInputs
from .controller_state import ControllerState
from .coupled_downlink import (
    CoupledDownlinkAttempt,
    CoupledDownlinkInputs,
    evaluate_coupled_downlink_resources,
    validate_coupled_downlink_inputs,
)
from .data_delivery import (
    CompletedAcquisitionDelivery,
    DownlinkTransferProgress,
    GroundDataDeliveryState,
)
from .degradation import (
    BatteryDegradationIntervalInput,
    BatteryDegradationSubstepInput,
    BatteryDegradationSubstepTransition,
    BatteryDegradationTransition,
    SolarDegradationForcingInput,
    SolarDegradationTransition,
    compute_battery_degradation_transition,
    compute_battery_degradation_substep,
    compute_battery_substep_throughput,
    compute_battery_throughput_increment,
    compute_explicit_solar_degradation_transition,
)
from .diagnostics import Diagnostics
from .downlink import (
    DownlinkTransmissionResult,
    DownlinkTransmissionStatus,
    evaluate_downlink_transmission,
)
from .eps_capability import (
    BatteryCapacityReconciliationResult,
    EPSCapabilityResult,
    compute_battery_capacity_reconciliation,
    compute_eps_capability,
)
from .eps_system import (
    EPSIntervalInputs,
    EPSIntervalResult,
    EPSSubstepResult,
    compute_eps_interval_transition,
)
from .integration_time import checked_duration
from .ids import AcquisitionDataRecordId
from .imaging_authorization import (
    ImagingExecutionAuthorizationResult,
    evaluate_imaging_engine_step_authorization,
)
from .imaging_execution import (
    ImagingExecutionAuthorizationStatus,
    ScheduledObservationAcquisitionExecution,
)
from .imaging_resources import AcquisitionEPSIntervalEnvironment
from .imaging_storage import (
    ImagingStorageAuthorizationResult,
    ImagingStorageAuthorizationStatus,
    authorize_imaging_storage_execution,
)
from .knowledge import GroundKnowledgeState, TelemetrySnapshot
from .mission import MissionState
from .observation_feasibility import ScheduledObservationExecution
from .state import (
    BatteryDegradationState,
    BatteryState,
    DegradationState,
    OnboardOperationsState,
    PropulsionState,
    SolarDegradationState,
    SpacecraftState,
    ThermalNodeState,
    ThermalState,
)
from .thermal import ThermalIntervalInputs
from .thermal_coupling import (
    EPSThermalCouplingResult,
    EPSThermalSubstepResult,
    ThermalHeatSourceInputs,
    compute_eps_thermal_interval_transition,
)
from .thermal_routing import ComponentHeatRoutingConfig


class SimulationPhase(str, Enum):
    """One phase in the canonical V5 completed-step execution order."""

    WORLD_ENVIRONMENT = "world-environment"
    KNOWLEDGE_UPDATE = "knowledge-update"
    PLANNING = "planning"
    ONBOARD_ARBITRATION = "onboard-arbitration"
    ACTION_EXECUTION = "action-execution"
    PHYSICAL_INTEGRATION = "physical-integration"
    FAILURE_CAPABILITY_RESOLUTION = "failure-capability-resolution"
    DIAGNOSTICS = "diagnostics"
    ADVANCE_CLOCK = "advance-clock"


STEP_PHASE_ORDER: tuple[SimulationPhase, ...] = (
    SimulationPhase.WORLD_ENVIRONMENT,
    SimulationPhase.KNOWLEDGE_UPDATE,
    SimulationPhase.PLANNING,
    SimulationPhase.ONBOARD_ARBITRATION,
    SimulationPhase.ACTION_EXECUTION,
    SimulationPhase.PHYSICAL_INTEGRATION,
    SimulationPhase.FAILURE_CAPABILITY_RESOLUTION,
    SimulationPhase.DIAGNOSTICS,
    SimulationPhase.ADVANCE_CLOCK,
)


@dataclass(frozen=True, slots=True)
class StepInterval:
    """One authoritative half-open main-step interval: [start, end)."""

    start_time_seconds: int
    end_time_seconds: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("start_time_seconds", self.start_time_seconds),
            ("end_time_seconds", self.end_time_seconds),
        ):
            if type(value) is not int:
                raise TypeError(f"{field_name} must be an integer")
        if self.start_time_seconds < 0:
            raise ValueError(
                "start_time_seconds must be greater than or equal to zero"
            )
        if self.end_time_seconds <= self.start_time_seconds:
            raise ValueError(
                "end_time_seconds must be greater than start_time_seconds"
            )

    @property
    def dt_seconds(self) -> int:
        """Return the derived interval duration in integer seconds."""
        return self.end_time_seconds - self.start_time_seconds

    def contains(self, timestamp_seconds: int) -> bool:
        """Return whether a timestamp lies in this half-open interval."""
        if type(timestamp_seconds) is not int:
            raise TypeError("timestamp_seconds must be an integer")
        if timestamp_seconds < 0:
            raise ValueError(
                "timestamp_seconds must be greater than or equal to zero"
            )
        return (
            self.start_time_seconds
            <= timestamp_seconds
            < self.end_time_seconds
        )


@dataclass(frozen=True, slots=True)
class StepResult:
    """Transient report of one successfully completed engine step."""

    start_time_seconds: int
    end_time_seconds: int
    dt_seconds: int
    executed_phases: tuple[SimulationPhase, ...]
    eps_result: EPSIntervalResult | None = None
    thermal_coupling_result: EPSThermalCouplingResult | None = None
    battery_degradation_result: BatteryDegradationTransition | None = None
    solar_degradation_result: SolarDegradationTransition | None = None
    eps_capability_result: EPSCapabilityResult | None = None
    battery_capacity_reconciliation_result: (
        BatteryCapacityReconciliationResult | None
    ) = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("start_time_seconds", self.start_time_seconds),
            ("end_time_seconds", self.end_time_seconds),
            ("dt_seconds", self.dt_seconds),
        ):
            if type(value) is not int:
                raise TypeError(f"{field_name} must be an integer")
        if self.start_time_seconds < 0:
            raise ValueError(
                "start_time_seconds must be greater than or equal to zero"
            )
        if self.dt_seconds <= 0:
            raise ValueError("dt_seconds must be greater than zero")
        if self.end_time_seconds != (
            self.start_time_seconds + self.dt_seconds
        ):
            raise ValueError(
                "end_time_seconds must equal start_time_seconds + dt_seconds"
            )
        if type(self.executed_phases) is not tuple:
            raise TypeError("executed_phases must be a tuple")
        if not all(
            type(phase) is SimulationPhase for phase in self.executed_phases
        ):
            raise TypeError(
                "executed_phases must contain only SimulationPhase values"
            )
        if self.executed_phases != STEP_PHASE_ORDER:
            raise ValueError("executed_phases must equal STEP_PHASE_ORDER")
        if self.eps_result is not None and type(self.eps_result) is not (
            EPSIntervalResult
        ):
            raise TypeError("eps_result must be an EPSIntervalResult or None")
        if (
            self.thermal_coupling_result is not None
            and type(self.thermal_coupling_result)
            is not EPSThermalCouplingResult
        ):
            raise TypeError(
                "thermal_coupling_result must be an "
                "EPSThermalCouplingResult or None"
            )
        if (
            self.battery_degradation_result is not None
            and type(self.battery_degradation_result)
            is not BatteryDegradationTransition
        ):
            raise TypeError(
                "battery_degradation_result must be a "
                "BatteryDegradationTransition or None"
            )
        if (
            self.solar_degradation_result is not None
            and type(self.solar_degradation_result)
            is not SolarDegradationTransition
        ):
            raise TypeError(
                "solar_degradation_result must be a "
                "SolarDegradationTransition or None"
            )
        if (
            self.eps_capability_result is not None
            and type(self.eps_capability_result) is not EPSCapabilityResult
        ):
            raise TypeError(
                "eps_capability_result must be an EPSCapabilityResult or None"
            )
        if (
            self.battery_capacity_reconciliation_result is not None
            and type(self.battery_capacity_reconciliation_result)
            is not BatteryCapacityReconciliationResult
        ):
            raise TypeError(
                "battery_capacity_reconciliation_result must be a "
                "BatteryCapacityReconciliationResult or None"
            )

    @property
    def interval(self) -> StepInterval:
        """Return the derived half-open interval executed by this step."""
        return StepInterval(
            self.start_time_seconds,
            self.end_time_seconds,
        )


@dataclass(frozen=True, slots=True)
class DownlinkEngineStepResult:
    """Committed engine-step and pure downlink-transmission evidence."""

    transmission_result: DownlinkTransmissionResult
    step_result: StepResult

    def __post_init__(self) -> None:
        if type(self.transmission_result) is not DownlinkTransmissionResult:
            raise TypeError(
                "transmission_result must be a DownlinkTransmissionResult"
            )
        if type(self.step_result) is not StepResult:
            raise TypeError("step_result must be a StepResult")
        self.transmission_result.__post_init__()
        self.step_result.__post_init__()

        contact = self.transmission_result.capacity_proposal.contact
        if self.step_result.start_time_seconds != contact.start_time_seconds:
            raise ValueError(
                "step_result start must equal the downlink contact start"
            )
        if self.step_result.end_time_seconds != contact.end_time_seconds:
            raise ValueError(
                "step_result end must equal the downlink contact end"
            )
        if self.step_result.executed_phases != STEP_PHASE_ORDER:
            raise ValueError(
                "downlink step_result must contain STEP_PHASE_ORDER"
            )
        physical_fields = (
            self.step_result.eps_result,
            self.step_result.thermal_coupling_result,
            self.step_result.battery_degradation_result,
            self.step_result.solar_degradation_result,
            self.step_result.eps_capability_result,
            self.step_result.battery_capacity_reconciliation_result,
        )
        if any(value is not None for value in physical_fields):
            raise ValueError(
                "downlink step_result physical evidence fields must be None"
            )


@dataclass(frozen=True, slots=True)
class ImagingEngineStepAttempt:
    """Transient outcome of one scheduled imaging transaction attempt."""

    authorization_result: ImagingExecutionAuthorizationResult
    step_result: StepResult | None

    def __post_init__(self) -> None:
        if type(self.authorization_result) is not (
            ImagingExecutionAuthorizationResult
        ):
            raise TypeError(
                "authorization_result must be an "
                "ImagingExecutionAuthorizationResult"
            )
        if self.step_result is not None and type(self.step_result) is not (
            StepResult
        ):
            raise TypeError("step_result must be a StepResult or None")

        self.authorization_result.__post_init__()
        if self.step_result is not None:
            self.step_result.__post_init__()

        status = self.authorization_result.status
        if status is not ImagingExecutionAuthorizationStatus.AUTHORIZED:
            if self.step_result is not None:
                raise ValueError(
                    "a non-authorized imaging attempt requires "
                    "step_result to be None"
                )
            return

        if self.step_result is None:
            raise ValueError("AUTHORIZED requires a step_result")

        execution = self.authorization_result.execution
        if self.step_result.start_time_seconds != (
            execution.scheduled_start_seconds
        ):
            raise ValueError(
                "step_result start must equal the scheduled imaging start"
            )
        acquisition_duration_seconds = (
            execution.candidate.acquisition_input.imaging_duration_seconds
        )
        if self.step_result.dt_seconds != acquisition_duration_seconds:
            raise ValueError(
                "step_result duration must equal the acquisition duration"
            )

        electrical_result = self.authorization_result.electrical_result
        if self.step_result.eps_result is not electrical_result.eps_result:
            raise ValueError(
                "step_result must contain the authorized EPS result"
            )
        if self.step_result.eps_capability_result is not (
            electrical_result.eps_capability_result
        ):
            raise ValueError(
                "step_result must contain the authorized EPS capability "
                "result"
            )
        thermal_proposal = self.authorization_result.thermal_proposal
        if thermal_proposal is None:
            raise ValueError("AUTHORIZED requires a thermal proposal")
        if self.step_result.thermal_coupling_result is not (
            thermal_proposal.eps_thermal_coupling_result
        ):
            raise ValueError(
                "step_result must contain the authorized thermal coupling "
                "result"
            )


@dataclass(frozen=True, slots=True)
class ImagingStorageEngineAttempt:
    """Transient outcome of one imaging-to-storage transaction attempt."""

    authorization_result: ImagingStorageAuthorizationResult
    step_result: StepResult | None

    def __post_init__(self) -> None:
        if type(self.authorization_result) is not (
            ImagingStorageAuthorizationResult
        ):
            raise TypeError(
                "authorization_result must be an "
                "ImagingStorageAuthorizationResult"
            )
        if self.step_result is not None and type(self.step_result) is not (
            StepResult
        ):
            raise TypeError("step_result must be a StepResult or None")

        self.authorization_result.__post_init__()
        if self.step_result is not None:
            self.step_result.__post_init__()

        status = self.authorization_result.status
        if status in {
            ImagingStorageAuthorizationStatus.IMAGING_NOT_AUTHORIZED,
            ImagingStorageAuthorizationStatus.INSUFFICIENT_STORAGE_CAPACITY,
        }:
            if self.step_result is not None:
                raise ValueError(
                    "a non-authorized imaging-storage attempt requires "
                    "step_result to be None"
                )
            return

        if self.step_result is None:
            raise ValueError("AUTHORIZED requires a step_result")

        imaging_result = self.authorization_result.imaging_authorization_result
        execution = imaging_result.execution
        if self.step_result.start_time_seconds != (
            execution.scheduled_start_seconds
        ):
            raise ValueError(
                "step_result start must equal the scheduled imaging start"
            )
        acquisition_duration_seconds = (
            execution.candidate.acquisition_input.imaging_duration_seconds
        )
        if self.step_result.dt_seconds != acquisition_duration_seconds:
            raise ValueError(
                "step_result duration must equal the acquisition duration"
            )
        if self.step_result.end_time_seconds != (
            self.step_result.start_time_seconds + self.step_result.dt_seconds
        ):
            raise ValueError(
                "step_result end must equal its start plus its duration"
            )

        electrical_result = imaging_result.electrical_result
        if self.step_result.eps_result is not electrical_result.eps_result:
            raise ValueError(
                "step_result must contain the authorized EPS result"
            )
        if self.step_result.eps_capability_result is not (
            electrical_result.eps_capability_result
        ):
            raise ValueError(
                "step_result must contain the authorized EPS capability "
                "result"
            )
        thermal_proposal = imaging_result.thermal_proposal
        if thermal_proposal is None:
            raise ValueError("AUTHORIZED requires a thermal proposal")
        if self.step_result.thermal_coupling_result is not (
            thermal_proposal.eps_thermal_coupling_result
        ):
            raise ValueError(
                "step_result must contain the authorized thermal coupling "
                "result"
            )


class _ImagingExecutionNotAuthorized(Exception):
    """Abort one imaging transaction for a supported nonauthorization."""

    __slots__ = ("authorization_result",)

    def __init__(
        self,
        authorization_result: ImagingExecutionAuthorizationResult,
    ) -> None:
        if type(authorization_result) is not (
            ImagingExecutionAuthorizationResult
        ):
            raise TypeError(
                "authorization_result must be an "
                "ImagingExecutionAuthorizationResult"
            )
        if authorization_result.status is (
            ImagingExecutionAuthorizationStatus.AUTHORIZED
        ):
            raise ValueError(
                "_ImagingExecutionNotAuthorized requires a non-authorized "
                "result"
            )
        self.authorization_result = authorization_result
        super().__init__(authorization_result.status.value)


class _ImagingStorageExecutionNotAuthorized(Exception):
    """Abort one imaging-storage transaction for a supported outcome."""

    __slots__ = ("authorization_result",)

    def __init__(
        self,
        authorization_result: ImagingStorageAuthorizationResult,
    ) -> None:
        if type(authorization_result) is not (
            ImagingStorageAuthorizationResult
        ):
            raise TypeError(
                "authorization_result must be an "
                "ImagingStorageAuthorizationResult"
            )
        authorization_result.__post_init__()
        if authorization_result.status is (
            ImagingStorageAuthorizationStatus.AUTHORIZED
        ):
            raise ValueError(
                "_ImagingStorageExecutionNotAuthorized requires a "
                "non-authorized result"
            )
        self.authorization_result = authorization_result
        super().__init__(authorization_result.status.value)


@dataclass(frozen=True, slots=True)
class _CoupledPhysicalIntegrationInputs:
    """Private complete input bundle passed through existing phase hooks."""

    eps_interval_inputs: EPSIntervalInputs
    thermal_inputs: ThermalIntervalInputs
    heat_source_inputs: ThermalHeatSourceInputs
    solar_degradation_forcing: SolarDegradationForcingInput | None

    def __post_init__(self) -> None:
        if type(self.eps_interval_inputs) is not EPSIntervalInputs:
            raise TypeError("eps_interval_inputs must be an EPSIntervalInputs")
        if type(self.thermal_inputs) is not ThermalIntervalInputs:
            raise TypeError("thermal_inputs must be a ThermalIntervalInputs")
        if type(self.heat_source_inputs) is not ThermalHeatSourceInputs:
            raise TypeError(
                "heat_source_inputs must be a ThermalHeatSourceInputs"
            )
        if (
            self.solar_degradation_forcing is not None
            and type(self.solar_degradation_forcing)
            is not SolarDegradationForcingInput
        ):
            raise TypeError(
                "solar_degradation_forcing must be a "
                "SolarDegradationForcingInput or None"
            )


@dataclass(frozen=True, slots=True)
class _EPSPhysicalIntegrationResult:
    """Private carrier for one capability-aware EPS-only proposal."""

    eps_result: EPSIntervalResult
    eps_capability_result: EPSCapabilityResult

    def __post_init__(self) -> None:
        if type(self.eps_result) is not EPSIntervalResult:
            raise TypeError("eps_result must be an EPSIntervalResult")
        if type(self.eps_capability_result) is not EPSCapabilityResult:
            raise TypeError(
                "eps_capability_result must be an EPSCapabilityResult"
            )


@dataclass(frozen=True, slots=True)
class _CoupledPhysicalIntegrationResult:
    """Private carrier for one coupled phase's validated proposals."""

    eps_result: EPSIntervalResult
    thermal_coupling_result: EPSThermalCouplingResult
    battery_degradation_result: BatteryDegradationTransition
    solar_degradation_result: SolarDegradationTransition | None
    eps_capability_result: EPSCapabilityResult
    battery_capacity_reconciliation_result: (
        BatteryCapacityReconciliationResult
    )

    def __post_init__(self) -> None:
        if type(self.eps_result) is not self._result_types()[0]:
            raise TypeError("eps_result must be an EPSIntervalResult")
        if type(self.thermal_coupling_result) is not self._result_types()[1]:
            raise TypeError(
                "thermal_coupling_result must be an "
                "EPSThermalCouplingResult"
            )
        if type(self.battery_degradation_result) is not (
            self._result_types()[2]
        ):
            raise TypeError(
                "battery_degradation_result must be a "
                "BatteryDegradationTransition"
            )
        if (
            self.solar_degradation_result is not None
            and type(self.solar_degradation_result)
            is not SolarDegradationTransition
        ):
            raise TypeError(
                "solar_degradation_result must be a "
                "SolarDegradationTransition or None"
            )
        if type(self.eps_capability_result) is not EPSCapabilityResult:
            raise TypeError(
                "eps_capability_result must be an EPSCapabilityResult"
            )
        if type(self.battery_capacity_reconciliation_result) is not (
            BatteryCapacityReconciliationResult
        ):
            raise TypeError(
                "battery_capacity_reconciliation_result must be a "
                "BatteryCapacityReconciliationResult"
            )

    def _result_types(self):
        return EPSIntervalResult, EPSThermalCouplingResult, BatteryDegradationTransition


@dataclass(frozen=True, slots=True)
class CoupledPhysicalSubstepResult(_CoupledPhysicalIntegrationResult):
    """Transient internal proposal; never a completed schema-5 boundary."""
    eps_result: EPSSubstepResult
    thermal_coupling_result: EPSThermalSubstepResult
    battery_degradation_result: BatteryDegradationSubstepTransition

    def _result_types(self):
        return EPSSubstepResult, EPSThermalSubstepResult, BatteryDegradationSubstepTransition

    def __post_init__(self):
        _CoupledPhysicalIntegrationResult.__post_init__(self)
        for value in (self.eps_result, self.eps_result.battery, self.thermal_coupling_result,
                      self.battery_degradation_result, self.eps_capability_result,
                      self.battery_capacity_reconciliation_result):
            value.__post_init__()
        duration = self.eps_result.battery.duration
        if (self.thermal_coupling_result.thermal_result.duration != duration
                or self.battery_degradation_result.duration != duration):
            raise ValueError("coupled substep durations disagree")


_PhysicalIntegrationResult = (
    _EPSPhysicalIntegrationResult
    | _CoupledPhysicalIntegrationResult
    | None
)
_PhysicalIntegrationHandler = Callable[
    [SimulationContext, StepInterval],
    _PhysicalIntegrationResult,
]
_PhysicalIntegrationHandlerFactory = Callable[
    [],
    _PhysicalIntegrationHandler,
]
_TransactionResultT = TypeVar("_TransactionResultT")


def _validate_completed_context(context: object) -> SimulationContext:
    """Revalidate all mutable completed-step state before phase mutation."""
    if type(context) is not SimulationContext:
        raise TypeError("context must be a SimulationContext")

    top_level_contracts = (
        ("inputs", context.inputs, SimulationInputs),
        ("spacecraft_state", context.spacecraft_state, SpacecraftState),
        (
            "ground_knowledge_state",
            context.ground_knowledge_state,
            GroundKnowledgeState,
        ),
        (
            "ground_data_delivery_state",
            context.ground_data_delivery_state,
            GroundDataDeliveryState,
        ),
        ("mission_state", context.mission_state, MissionState),
        ("controller_state", context.controller_state, ControllerState),
        ("diagnostics", context.diagnostics, Diagnostics),
    )
    for field_name, value, expected_type in top_level_contracts:
        if type(value) is not expected_type:
            raise TypeError(
                f"{field_name} must be a {expected_type.__name__}"
            )

    inputs = context.inputs
    SimulationInputs(
        inputs.spacecraft_configuration,
        inputs.numerical_config,
        inputs.environment_config,
        inputs.flight_rules_config,
        inputs.scenario_config,
        inputs.common_world,
        inputs.model_manifest,
        coast_orbit=inputs.coast_orbit,
    )

    spacecraft = context.spacecraft_state
    SpacecraftState(
        spacecraft.battery,
        spacecraft.propulsion,
        spacecraft.thermal,
        spacecraft.degradation,
        spacecraft.onboard,
        spacecraft.data_storage,
    )
    BatteryState(spacecraft.battery.energy_wh)
    PropulsionState(spacecraft.propulsion.delta_v_remaining_m_per_s)
    ThermalState(spacecraft.thermal.node_states)
    DegradationState(
        spacecraft.degradation.battery,
        spacecraft.degradation.solar,
    )
    onboard = spacecraft.onboard
    OnboardOperationsState(
        onboard.operational_mode,
        onboard.fdir_state,
        onboard.accepted_plan_id,
        onboard.accepted_authority_id,
        onboard.last_qualifying_contact_time_seconds,
        onboard.critical_energy_since_seconds,
    )

    knowledge = context.ground_knowledge_state
    GroundKnowledgeState(
        knowledge.latest_telemetry,
        knowledge.known_world_event_ids,
    )
    telemetry = knowledge.latest_telemetry
    if telemetry is not None:
        TelemetrySnapshot(
            telemetry.snapshot_id,
            telemetry.sampled_at_seconds,
            telemetry.received_at_seconds,
            telemetry.battery_energy_wh,
            telemetry.delta_v_remaining_m_per_s,
            telemetry.operational_mode,
        )

    delivery = context.ground_data_delivery_state
    GroundDataDeliveryState(
        delivery.partial_transfers,
        delivery.completed_deliveries,
    )

    mission = context.mission_state
    MissionState(
        mission.pending_request_ids,
        mission.completed_request_ids,
        mission.data_product_ids,
        mission.active_plan_id,
        mission.command_ids,
        mission.resolved_world_event_ids,
    )
    controller = context.controller_state
    ControllerState(
        controller.controller_id,
        controller.latest_plan_id,
        controller.replan_count,
    )
    Diagnostics(context.diagnostics.completed_steps)

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
    return context


def _complete_coupled_physical_integration(
    context: SimulationContext,
    interval: StepInterval,
    *,
    eps_result: EPSIntervalResult,
    thermal_coupling_result: EPSThermalCouplingResult,
    eps_capability_result: EPSCapabilityResult,
    solar_degradation_forcing: SolarDegradationForcingInput | None,
) -> _CoupledPhysicalIntegrationResult:
    """Complete one validated coupled proposal on a working context."""
    return _complete_coupled_physical_core(context, interval.dt_seconds,
        eps_result=eps_result, thermal_coupling_result=thermal_coupling_result,
        eps_capability_result=eps_capability_result, solar_degradation_forcing=solar_degradation_forcing)


def complete_coupled_physical_substep(context, duration, *, eps_result, thermal_coupling_result,
                                      eps_capability_result, solar_degradation_forcing):
    """Apply the shared completion owner to private state, without clock/data changes."""
    return _complete_coupled_physical_core(context, checked_duration(duration),
        eps_result=eps_result, thermal_coupling_result=thermal_coupling_result,
        eps_capability_result=eps_capability_result, solar_degradation_forcing=solar_degradation_forcing,
        _duration=duration)


def _complete_coupled_physical_core(context, dt_seconds, *, eps_result, thermal_coupling_result,
                                  eps_capability_result, solar_degradation_forcing, _duration=None):
    spacecraft_config = context.inputs.spacecraft_configuration
    active_eps_config = spacecraft_config.eps
    thermal_network = spacecraft_config.thermal.network
    transition_by_id = {
        transition.node_id: transition
        for transition in (
            thermal_coupling_result.thermal_result.node_transitions
        )
    }
    runtime_thermal = context.spacecraft_state.thermal
    runtime_node_ids = {
        node_state.node_id for node_state in runtime_thermal.node_states
    }
    if set(transition_by_id) != runtime_node_ids:
        raise ValueError(
            "thermal transition node IDs must exactly match runtime "
            "thermal node IDs"
        )

    runtime_node_by_id = {
        node_state.node_id: node_state
        for node_state in runtime_thermal.node_states
    }
    if _duration is None:
        throughput_increment = compute_battery_throughput_increment(eps_result, active_eps_config.battery)
    else:
        throughput_increment = compute_battery_substep_throughput(eps_result, active_eps_config.battery)
    battery_node_id = thermal_network.battery_node_id
    start_battery_temperature_k = runtime_node_by_id[
        battery_node_id
    ].temperature_k
    end_battery_temperature_k = transition_by_id[
        battery_node_id
    ].end_temperature_k
    representative_battery_temperature_k = (
        start_battery_temperature_k
        + (end_battery_temperature_k - start_battery_temperature_k) / 2
    )
    if _duration is None:
        battery_degradation_result = compute_battery_degradation_transition(
            context.spacecraft_state.degradation.battery, active_eps_config.battery,
            spacecraft_config.degradation.battery_ageing_model,
            BatteryDegradationIntervalInput(representative_battery_temperature_k,
                throughput_increment, dt_seconds))
    else:
        battery_degradation_result = compute_battery_degradation_substep(
            context.spacecraft_state.degradation.battery, active_eps_config.battery,
            spacecraft_config.degradation.battery_ageing_model,
            BatteryDegradationSubstepInput(representative_battery_temperature_k,
                throughput_increment, dt_seconds, _duration))
    solar_degradation_result = None
    if solar_degradation_forcing is not None:
        solar_degradation_result = (
            compute_explicit_solar_degradation_transition(
                context.spacecraft_state.degradation.solar,
                solar_degradation_forcing,
            )
        )
    battery_capacity_reconciliation_result = (
        compute_battery_capacity_reconciliation(
            eps_result.battery.end_energy_wh,
            active_eps_config.battery,
            battery_degradation_result.end_usable_capacity_retention,
        )
    )
    result_type = _CoupledPhysicalIntegrationResult if _duration is None else CoupledPhysicalSubstepResult
    coupled_result = result_type(
        eps_result,
        thermal_coupling_result,
        battery_degradation_result,
        solar_degradation_result,
        eps_capability_result,
        battery_capacity_reconciliation_result,
    )

    BatteryState(
        battery_capacity_reconciliation_result.authoritative_end_energy_wh
    )
    for node_state in runtime_thermal.node_states:
        ThermalNodeState(
            node_state.node_id,
            transition_by_id[node_state.node_id].end_temperature_k,
        )
    BatteryDegradationState(
        battery_degradation_result.end_usable_capacity_retention,
        battery_degradation_result.end_cumulative_energy_throughput_wh,
    )
    if solar_degradation_result is not None:
        SolarDegradationState(
            solar_degradation_result.end_generation_retention
        )

    context.spacecraft_state.battery.energy_wh = (
        battery_capacity_reconciliation_result.authoritative_end_energy_wh
    )
    for node_state in runtime_thermal.node_states:
        node_state.temperature_k = (
            transition_by_id[node_state.node_id].end_temperature_k
        )
    battery_degradation_state = context.spacecraft_state.degradation.battery
    battery_degradation_state.usable_capacity_retention = (
        battery_degradation_result.end_usable_capacity_retention
    )
    battery_degradation_state.cumulative_energy_throughput_wh = (
        battery_degradation_result.end_cumulative_energy_throughput_wh
    )
    if solar_degradation_result is not None:
        context.spacecraft_state.degradation.solar.generation_retention = (
            solar_degradation_result.end_generation_retention
        )
    return coupled_result


class SimulationEngine:
    """Execute fixed V5 phases without retaining state between steps."""

    __slots__ = ()

    def step(
        self,
        context: SimulationContext,
        *,
        eps_inputs: EPSIntervalInputs | None = None,
        thermal_inputs: ThermalIntervalInputs | None = None,
        heat_source_inputs: ThermalHeatSourceInputs | None = None,
        solar_degradation_forcing: SolarDegradationForcingInput | None = None,
    ) -> StepResult:
        """Transactionally advance one complete configured simulation step."""
        return self._run_transaction(
            context,
            physical_integration_handler_factory=lambda: (
                self._prepare_generic_physical_integration_handler(
                    eps_inputs,
                    thermal_inputs,
                    heat_source_inputs,
                    solar_degradation_forcing,
                )
            ),
        )

    def step_downlink(
        self,
        context: SimulationContext,
        contact: ServiceableGroundContact,
        *,
        record_id: AcquisitionDataRecordId,
    ) -> DownlinkEngineStepResult:
        """Atomically service one caller-selected onboard record."""
        if type(context) is not SimulationContext:
            raise TypeError("context must be a SimulationContext")
        if type(contact) is not ServiceableGroundContact:
            raise TypeError("contact must be a ServiceableGroundContact")
        if type(record_id) is not AcquisitionDataRecordId:
            raise TypeError("record_id must be an AcquisitionDataRecordId")
        ServiceableGroundContact(
            contact.contact_id,
            contact.ground_station_id,
            contact.start_time_seconds,
            contact.end_time_seconds,
        )
        AcquisitionDataRecordId(record_id.value)
        _validate_completed_context(context)

        start_time_seconds = context.simulation_time_seconds
        end_time_seconds = (
            start_time_seconds
            + context.inputs.numerical_config.timestep_seconds
        )
        if contact.start_time_seconds != start_time_seconds:
            raise ValueError(
                "downlink contact start must equal simulation time"
            )
        if contact.end_time_seconds != end_time_seconds:
            raise ValueError(
                "downlink contact end must equal the full step end"
            )
        if contact.end_time_seconds > context.inputs.common_world.horizon_seconds:
            raise ValueError(
                "downlink contact would cross the common-world horizon"
            )

        transmission_result: DownlinkTransmissionResult | None = None

        def retain_transmission_result(
            result: DownlinkTransmissionResult,
        ) -> None:
            nonlocal transmission_result
            transmission_result = result

        def build_result(step_result: StepResult) -> DownlinkEngineStepResult:
            if transmission_result is None:
                raise RuntimeError(
                    "downlink physical integration did not retain a "
                    "transmission result"
                )
            transmission_result.__post_init__()
            return DownlinkEngineStepResult(
                transmission_result,
                step_result,
            )

        return self._run_transaction(
            context,
            physical_integration_handler_factory=lambda: (
                self._prepare_downlink_physical_integration_handler(
                    contact,
                    record_id,
                    retain_transmission_result,
                )
            ),
            precommit_result_factory=build_result,
        )

    def step_coupled_downlink(
        self,
        context: SimulationContext,
        contact: ServiceableGroundContact,
        *,
        record_id: AcquisitionDataRecordId,
        physical_inputs: CoupledDownlinkInputs,
    ) -> CoupledDownlinkAttempt:
        """Commit one full-service physical/data interval, or deny without time.

        Data bookkeeping is first proposed on the transaction's private clone;
        this preserves all legacy selection/chronology checks even on electrical
        denial. Nothing from that proposal is committed or delivered on denial.
        """
        _validate_completed_context(context)
        if type(contact) is not ServiceableGroundContact:
            raise TypeError("contact must be a ServiceableGroundContact")
        contact.__post_init__()
        if type(record_id) is not AcquisitionDataRecordId:
            raise TypeError("record_id must be an AcquisitionDataRecordId")
        AcquisitionDataRecordId(record_id.value)
        start = context.simulation_time_seconds
        end = start + context.inputs.numerical_config.timestep_seconds
        if contact.start_time_seconds != start or contact.end_time_seconds != end:
            raise ValueError("downlink contact must equal the full current engine step")
        if end > context.inputs.common_world.horizon_seconds:
            raise ValueError("downlink contact would cross the common-world horizon")
        physical_inputs = validate_coupled_downlink_inputs(
            physical_inputs, context.inputs.spacecraft_configuration.thermal.network,
        )
        transmission = eps = capability = routed_heat = None

        class ElectricalDenial(Exception):
            """Private non-committing exit from the shared transaction runner."""

        def retain_transmission(result):
            nonlocal transmission
            transmission = result

        data_handler = self._prepare_downlink_physical_integration_handler(
            contact, record_id, retain_transmission,
        )

        def integrate(working_context, interval):
            nonlocal eps, capability, routed_heat
            data_handler(working_context, interval)
            configuration = working_context.inputs.spacecraft_configuration
            spacecraft = working_context.spacecraft_state
            proposal = evaluate_coupled_downlink_resources(
                spacecraft.battery, spacecraft.degradation, spacecraft.thermal,
                configuration.eps, configuration.thermal.network, physical_inputs,
                dt_seconds=interval.dt_seconds,
            )
            eps, capability = proposal.eps_result, proposal.eps_capability_result
            if not proposal.authorized:
                raise ElectricalDenial
            routed_heat = proposal.routed_heat_result
            return _complete_coupled_physical_integration(
                working_context, interval, eps_result=eps,
                thermal_coupling_result=proposal.thermal_coupling_result,
                eps_capability_result=capability,
                solar_degradation_forcing=physical_inputs.solar_degradation_forcing,
            )

        def build_attempt(step):
            return CoupledDownlinkAttempt(
                contact, physical_inputs, eps, capability, transmission, routed_heat, step,
            )

        try:
            return self._run_transaction(
                context, physical_integration_handler_factory=lambda: integrate,
                precommit_result_factory=build_attempt,
            )
        except ElectricalDenial:
            return CoupledDownlinkAttempt(
                contact, physical_inputs, eps, capability, None, None, None,
            )

    def step_imaging(
        self,
        context: SimulationContext,
        previous_execution: ScheduledObservationExecution,
        execution: ScheduledObservationAcquisitionExecution,
        *,
        environment: AcquisitionEPSIntervalEnvironment,
        routing_config: ComponentHeatRoutingConfig,
        thermal_inputs: ThermalIntervalInputs,
        external_heat_sources: ThermalHeatSourceInputs,
        solar_degradation_forcing: (
            SolarDegradationForcingInput | None
        ) = None,
    ) -> ImagingEngineStepAttempt:
        """Attempt one scheduled imaging interval transactionally."""
        authorization_result: ImagingExecutionAuthorizationResult | None = None

        def retain_authorization_result(
            result: ImagingExecutionAuthorizationResult,
        ) -> None:
            nonlocal authorization_result
            authorization_result = result

        def build_attempt(
            step_result: StepResult,
        ) -> ImagingEngineStepAttempt:
            if authorization_result is None:
                raise RuntimeError(
                    "imaging physical integration did not retain "
                    "authorization"
                )
            authorization_result.__post_init__()
            return ImagingEngineStepAttempt(
                authorization_result,
                step_result,
            )

        try:
            return self._run_transaction(
                context,
                physical_integration_handler_factory=lambda: (
                    self._prepare_imaging_physical_integration_handler(
                        previous_execution,
                        execution,
                        environment,
                        routing_config,
                        thermal_inputs,
                        external_heat_sources,
                        solar_degradation_forcing,
                        retain_authorization_result,
                    )
                ),
                precommit_result_factory=build_attempt,
            )
        except _ImagingExecutionNotAuthorized as error:
            return ImagingEngineStepAttempt(
                error.authorization_result,
                None,
            )

    def step_imaging_to_storage(
        self,
        context: SimulationContext,
        previous_execution: ScheduledObservationExecution,
        execution: ScheduledObservationAcquisitionExecution,
        *,
        record_id: AcquisitionDataRecordId,
        environment: AcquisitionEPSIntervalEnvironment,
        routing_config: ComponentHeatRoutingConfig,
        thermal_inputs: ThermalIntervalInputs,
        external_heat_sources: ThermalHeatSourceInputs,
        solar_degradation_forcing: (
            SolarDegradationForcingInput | None
        ) = None,
    ) -> ImagingStorageEngineAttempt:
        """Atomically attempt one imaging interval and storage append."""
        authorization_result: ImagingStorageAuthorizationResult | None = None

        def retain_authorization_result(
            result: ImagingStorageAuthorizationResult,
        ) -> None:
            nonlocal authorization_result
            authorization_result = result

        def build_attempt(
            step_result: StepResult,
        ) -> ImagingStorageEngineAttempt:
            if authorization_result is None:
                raise RuntimeError(
                    "imaging-storage physical integration did not retain "
                    "authorization"
                )
            authorization_result.__post_init__()
            if authorization_result.status is not (
                ImagingStorageAuthorizationStatus.AUTHORIZED
            ):
                raise ValueError(
                    "successful imaging-storage integration requires "
                    "authorization"
                )
            return ImagingStorageEngineAttempt(
                authorization_result,
                step_result,
            )

        try:
            return self._run_transaction(
                context,
                physical_integration_handler_factory=lambda: (
                    self._prepare_imaging_storage_physical_integration_handler(
                        previous_execution,
                        execution,
                        record_id,
                        environment,
                        routing_config,
                        thermal_inputs,
                        external_heat_sources,
                        solar_degradation_forcing,
                        retain_authorization_result,
                    )
                ),
                precommit_result_factory=build_attempt,
            )
        except _ImagingStorageExecutionNotAuthorized as error:
            return ImagingStorageEngineAttempt(
                error.authorization_result,
                None,
            )

    def _prepare_generic_physical_integration_handler(
        self,
        eps_inputs: EPSIntervalInputs | None,
        thermal_inputs: ThermalIntervalInputs | None,
        heat_source_inputs: ThermalHeatSourceInputs | None,
        solar_degradation_forcing: SolarDegradationForcingInput | None,
    ) -> _PhysicalIntegrationHandler:
        """Validate and bind the current generic physical inputs."""
        if eps_inputs is not None and type(eps_inputs) is not EPSIntervalInputs:
            raise TypeError("eps_inputs must be EPSIntervalInputs or None")
        if (
            thermal_inputs is not None
            and type(thermal_inputs) is not ThermalIntervalInputs
        ):
            raise TypeError(
                "thermal_inputs must be a ThermalIntervalInputs or None"
            )
        if (
            heat_source_inputs is not None
            and type(heat_source_inputs) is not ThermalHeatSourceInputs
        ):
            raise TypeError(
                "heat_source_inputs must be a ThermalHeatSourceInputs or None"
            )
        if (
            solar_degradation_forcing is not None
            and type(solar_degradation_forcing)
            is not SolarDegradationForcingInput
        ):
            raise TypeError(
                "solar_degradation_forcing must be a "
                "SolarDegradationForcingInput or None"
            )
        supplied_physics_inputs = (
            eps_inputs is not None,
            thermal_inputs is not None,
            heat_source_inputs is not None,
        )
        if (
            solar_degradation_forcing is not None
            and supplied_physics_inputs != (True, True, True)
        ):
            raise ValueError(
                "solar_degradation_forcing requires complete coupled EPS "
                "and thermal inputs"
            )
        if supplied_physics_inputs not in {
            (False, False, False),
            (True, False, False),
            (True, True, True),
        }:
            raise ValueError(
                "coupled thermal integration requires eps_inputs, "
                "thermal_inputs, and heat_source_inputs together"
            )
        physical_inputs: (
            EPSIntervalInputs | _CoupledPhysicalIntegrationInputs | None
        ) = eps_inputs
        if supplied_physics_inputs == (True, True, True):
            physical_inputs = _CoupledPhysicalIntegrationInputs(
                eps_inputs,
                thermal_inputs,
                heat_source_inputs,
                solar_degradation_forcing,
            )

        def physical_integration_handler(
            working_context: SimulationContext,
            interval: StepInterval,
        ) -> _PhysicalIntegrationResult:
            return self._physical_integration(
                working_context,
                interval,
                physical_inputs,
            )

        return physical_integration_handler

    def _prepare_downlink_physical_integration_handler(
        self,
        contact: ServiceableGroundContact,
        record_id: AcquisitionDataRecordId,
        retain_transmission_result: Callable[
            [DownlinkTransmissionResult],
            None,
        ],
    ) -> _PhysicalIntegrationHandler:
        """Bind one caller-selected downlink transaction request."""

        def downlink_physical_integration_handler(
            working_context: SimulationContext,
            interval: StepInterval,
        ) -> _PhysicalIntegrationResult:
            delivery = working_context.ground_data_delivery_state
            if any(
                completed.record.record_id == record_id
                for completed in delivery.completed_deliveries
            ):
                raise ValueError("requested record ID is already delivered")

            storage = working_context.spacecraft_state.data_storage
            record_positions = tuple(
                index
                for index, record in enumerate(storage.stored_records)
                if record.record_id == record_id
            )
            if not record_positions:
                raise ValueError("requested record ID is not onboard")
            if len(record_positions) != 1:
                raise ValueError(
                    "requested record ID must identify exactly one onboard record"
                )
            record_position = record_positions[0]
            record = storage.stored_records[record_position]

            progress_positions = tuple(
                index
                for index, progress_value in enumerate(
                    delivery.partial_transfers
                )
                if progress_value.record_id == record_id
            )
            if len(progress_positions) > 1:
                raise ValueError(
                    "requested record ID must identify at most one partial "
                    "transfer"
                )
            progress_position = (
                None if not progress_positions else progress_positions[0]
            )
            progress = (
                None
                if progress_position is None
                else delivery.partial_transfers[progress_position]
            )

            result = evaluate_downlink_transmission(
                working_context.inputs.spacecraft_configuration.communications,
                contact,
                record,
                progress,
            )
            if type(result) is not DownlinkTransmissionResult:
                raise TypeError(
                    "C must return a DownlinkTransmissionResult"
                )
            result.__post_init__()
            if result.record is not record:
                raise ValueError(
                    "transmission result must retain the selected onboard record"
                )
            if result.capacity_proposal.contact is not contact:
                raise ValueError(
                    "transmission result must retain the caller contact"
                )
            expected_progress_before = (
                0.0
                if progress is None
                else progress.transmitted_equivalent_bits
            )
            if result.progress_before_equivalent_bits != expected_progress_before:
                raise ValueError(
                    "transmission progress_before must equal persistent progress"
                )
            retain_transmission_result(result)

            if result.status is DownlinkTransmissionStatus.PARTIAL:
                if result.storage_freed_equivalent_bits != 0.0:
                    raise ValueError(
                        "PARTIAL transmission must not free onboard storage"
                    )
                next_progress = DownlinkTransferProgress(
                    record.record_id,
                    result.progress_after_equivalent_bits,
                )
                if progress_position is None:
                    delivery.partial_transfers = (
                        delivery.partial_transfers + (next_progress,)
                    )
                else:
                    delivery.partial_transfers = (
                        delivery.partial_transfers[:progress_position]
                        + (next_progress,)
                        + delivery.partial_transfers[progress_position + 1 :]
                    )
                return None

            if result.status is not DownlinkTransmissionStatus.COMPLETE:
                raise ValueError("unsupported downlink transmission status")
            if result.storage_freed_equivalent_bits != (
                record.stored_equivalent_bits
            ):
                raise ValueError(
                    "COMPLETE storage freed must equal the selected record total"
                )
            storage.stored_records = (
                storage.stored_records[:record_position]
                + storage.stored_records[record_position + 1 :]
            )
            if progress_position is not None:
                delivery.partial_transfers = (
                    delivery.partial_transfers[:progress_position]
                    + delivery.partial_transfers[progress_position + 1 :]
                )
            delivery.completed_deliveries = (
                delivery.completed_deliveries
                + (CompletedAcquisitionDelivery(record, contact),)
            )
            return None

        return downlink_physical_integration_handler

    def _prepare_imaging_physical_integration_handler(
        self,
        previous_execution: ScheduledObservationExecution,
        execution: ScheduledObservationAcquisitionExecution,
        environment: AcquisitionEPSIntervalEnvironment,
        routing_config: ComponentHeatRoutingConfig,
        thermal_inputs: ThermalIntervalInputs,
        external_heat_sources: ThermalHeatSourceInputs,
        solar_degradation_forcing: SolarDegradationForcingInput | None,
        retain_authorization_result: Callable[
            [ImagingExecutionAuthorizationResult],
            None,
        ],
    ) -> _PhysicalIntegrationHandler:
        """Validate and bind one scheduled imaging transaction request."""
        contracts = (
            (
                "previous_execution",
                previous_execution,
                ScheduledObservationExecution,
            ),
            (
                "execution",
                execution,
                ScheduledObservationAcquisitionExecution,
            ),
            (
                "environment",
                environment,
                AcquisitionEPSIntervalEnvironment,
            ),
            (
                "routing_config",
                routing_config,
                ComponentHeatRoutingConfig,
            ),
            ("thermal_inputs", thermal_inputs, ThermalIntervalInputs),
            (
                "external_heat_sources",
                external_heat_sources,
                ThermalHeatSourceInputs,
            ),
        )
        for field_name, value, expected_type in contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )
        if (
            solar_degradation_forcing is not None
            and type(solar_degradation_forcing)
            is not SolarDegradationForcingInput
        ):
            raise TypeError(
                "solar_degradation_forcing must be a "
                "SolarDegradationForcingInput or None"
            )

        previous_execution.__post_init__()
        execution.__post_init__()
        environment.__post_init__()
        routing_config.__post_init__()
        for route in routing_config.routes:
            replace(route.retained_heat_fraction)
        thermal_inputs.__post_init__()
        external_heat_sources.__post_init__()
        if solar_degradation_forcing is not None:
            solar_degradation_forcing.__post_init__()

        def imaging_physical_integration_handler(
            working_context: SimulationContext,
            interval: StepInterval,
        ) -> _PhysicalIntegrationResult:
            authorization_result = (
                evaluate_imaging_engine_step_authorization(
                    working_context,
                    previous_execution,
                    execution,
                    environment,
                    routing_config,
                    thermal_inputs,
                    external_heat_sources,
                )
            )
            if type(authorization_result) is not (
                ImagingExecutionAuthorizationResult
            ):
                raise TypeError(
                    "F2 must return an "
                    "ImagingExecutionAuthorizationResult"
                )
            authorization_result.__post_init__()
            retain_authorization_result(authorization_result)
            if authorization_result.status is not (
                ImagingExecutionAuthorizationStatus.AUTHORIZED
            ):
                raise _ImagingExecutionNotAuthorized(authorization_result)

            electrical_result = authorization_result.electrical_result
            thermal_proposal = authorization_result.thermal_proposal
            if thermal_proposal is None:
                raise ValueError(
                    "AUTHORIZED imaging requires a thermal proposal"
                )
            return _complete_coupled_physical_integration(
                working_context,
                interval,
                eps_result=electrical_result.eps_result,
                thermal_coupling_result=(
                    thermal_proposal.eps_thermal_coupling_result
                ),
                eps_capability_result=(
                    electrical_result.eps_capability_result
                ),
                solar_degradation_forcing=solar_degradation_forcing,
            )

        return imaging_physical_integration_handler

    def _prepare_imaging_storage_physical_integration_handler(
        self,
        previous_execution: ScheduledObservationExecution,
        execution: ScheduledObservationAcquisitionExecution,
        record_id: AcquisitionDataRecordId,
        environment: AcquisitionEPSIntervalEnvironment,
        routing_config: ComponentHeatRoutingConfig,
        thermal_inputs: ThermalIntervalInputs,
        external_heat_sources: ThermalHeatSourceInputs,
        solar_degradation_forcing: SolarDegradationForcingInput | None,
        retain_authorization_result: Callable[
            [ImagingStorageAuthorizationResult],
            None,
        ],
    ) -> _PhysicalIntegrationHandler:
        """Validate and bind one imaging-to-storage transaction request."""
        contracts = (
            (
                "previous_execution",
                previous_execution,
                ScheduledObservationExecution,
            ),
            (
                "execution",
                execution,
                ScheduledObservationAcquisitionExecution,
            ),
            ("record_id", record_id, AcquisitionDataRecordId),
            (
                "environment",
                environment,
                AcquisitionEPSIntervalEnvironment,
            ),
            (
                "routing_config",
                routing_config,
                ComponentHeatRoutingConfig,
            ),
            ("thermal_inputs", thermal_inputs, ThermalIntervalInputs),
            (
                "external_heat_sources",
                external_heat_sources,
                ThermalHeatSourceInputs,
            ),
        )
        for field_name, value, expected_type in contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )
        if (
            solar_degradation_forcing is not None
            and type(solar_degradation_forcing)
            is not SolarDegradationForcingInput
        ):
            raise TypeError(
                "solar_degradation_forcing must be a "
                "SolarDegradationForcingInput or None"
            )

        previous_execution.__post_init__()
        execution.__post_init__()
        AcquisitionDataRecordId(record_id.value)
        environment.__post_init__()
        routing_config.__post_init__()
        for route in routing_config.routes:
            replace(route.retained_heat_fraction)
        thermal_inputs.__post_init__()
        external_heat_sources.__post_init__()
        if solar_degradation_forcing is not None:
            solar_degradation_forcing.__post_init__()

        def imaging_storage_physical_integration_handler(
            working_context: SimulationContext,
            interval: StepInterval,
        ) -> _PhysicalIntegrationResult:
            c_result = authorize_imaging_storage_execution(
                working_context,
                previous_execution,
                execution,
                record_id=record_id,
                environment=environment,
                routing_config=routing_config,
                thermal_inputs=thermal_inputs,
                external_heat_sources=external_heat_sources,
            )
            if type(c_result) is not (
                ImagingStorageAuthorizationResult
            ):
                raise TypeError(
                    "C must return an ImagingStorageAuthorizationResult"
                )
            c_result.__post_init__()
            retain_authorization_result(c_result)
            if c_result.status is not (
                ImagingStorageAuthorizationStatus.AUTHORIZED
            ):
                raise _ImagingStorageExecutionNotAuthorized(
                    c_result
                )

            f2 = c_result.imaging_authorization_result
            electrical_result = f2.electrical_result
            thermal_proposal = f2.thermal_proposal
            if thermal_proposal is None:
                raise ValueError(
                    "AUTHORIZED imaging-storage execution requires a "
                    "thermal proposal"
                )
            physical_result = _complete_coupled_physical_integration(
                working_context,
                interval,
                eps_result=electrical_result.eps_result,
                thermal_coupling_result=(
                    thermal_proposal.eps_thermal_coupling_result
                ),
                eps_capability_result=(
                    electrical_result.eps_capability_result
                ),
                solar_degradation_forcing=solar_degradation_forcing,
            )

            storage_admission_result = c_result.storage_admission_result
            if storage_admission_result is None:
                raise ValueError(
                    "AUTHORIZED imaging-storage execution requires storage "
                    "admission evidence"
                )
            record = c_result.storage_admission_result.proposed_record
            storage = working_context.spacecraft_state.data_storage
            storage.stored_records = storage.stored_records + (record,)
            return physical_result

        return imaging_storage_physical_integration_handler

    def _run_transaction(
        self,
        context: SimulationContext,
        *,
        physical_integration_handler_factory: (
            _PhysicalIntegrationHandlerFactory
        ),
        precommit_result_factory: (
            Callable[[StepResult], _TransactionResultT] | None
        ) = None,
    ) -> StepResult | _TransactionResultT:
        """Run one checkpoint-isolated engine transaction."""
        context = _validate_completed_context(context)
        if (
            precommit_result_factory is not None
            and not callable(precommit_result_factory)
        ):
            raise TypeError(
                "precommit_result_factory must be callable or None"
            )
        physical_integration_handler = (
            physical_integration_handler_factory()
        )
        start_time_seconds = context.simulation_time_seconds
        dt_seconds = context.inputs.numerical_config.timestep_seconds
        interval = StepInterval(
            start_time_seconds,
            start_time_seconds + dt_seconds,
        )
        if (
            interval.end_time_seconds
            > context.inputs.common_world.horizon_seconds
        ):
            raise ValueError("step would cross the common-world horizon")

        original_completed_steps = context.diagnostics.completed_steps
        checkpoint = CheckpointState.from_context(context)
        working_context = checkpoint.restore(context.inputs)
        executed_phases: list[SimulationPhase] = []
        physical_phase_result: object = None
        for phase in STEP_PHASE_ORDER:
            phase_result = self._execute_phase(
                phase,
                working_context,
                interval,
                physical_integration_handler,
            )
            if phase is SimulationPhase.PHYSICAL_INTEGRATION:
                physical_phase_result = phase_result
            executed_phases.append(phase)

        _validate_completed_context(working_context)
        if working_context.simulation_time_seconds != interval.end_time_seconds:
            raise ValueError("proposed step did not advance to the interval end")
        if working_context.diagnostics.completed_steps != (
            original_completed_steps + 1
        ):
            raise ValueError(
                "proposed step did not increment completed_steps exactly once"
            )
        eps_result = None
        thermal_coupling_result = None
        battery_degradation_result = None
        solar_degradation_result = None
        eps_capability_result = None
        battery_capacity_reconciliation_result = None
        if type(physical_phase_result) is _EPSPhysicalIntegrationResult:
            eps_result = physical_phase_result.eps_result
            eps_capability_result = (
                physical_phase_result.eps_capability_result
            )
        elif type(physical_phase_result) is _CoupledPhysicalIntegrationResult:
            eps_result = physical_phase_result.eps_result
            thermal_coupling_result = (
                physical_phase_result.thermal_coupling_result
            )
            battery_degradation_result = (
                physical_phase_result.battery_degradation_result
            )
            solar_degradation_result = (
                physical_phase_result.solar_degradation_result
            )
            eps_capability_result = (
                physical_phase_result.eps_capability_result
            )
            battery_capacity_reconciliation_result = (
                physical_phase_result.battery_capacity_reconciliation_result
            )
        elif physical_phase_result is not None:
            raise TypeError(
                "PHYSICAL_INTEGRATION must return a capability-aware "
                "EPSIntervalResult carrier, a coupled physical result, or "
                "None"
            )
        proposed_result = StepResult(
            interval.start_time_seconds,
            interval.end_time_seconds,
            interval.dt_seconds,
            tuple(executed_phases),
            eps_result=eps_result,
            thermal_coupling_result=thermal_coupling_result,
            battery_degradation_result=battery_degradation_result,
            solar_degradation_result=solar_degradation_result,
            eps_capability_result=eps_capability_result,
            battery_capacity_reconciliation_result=(
                battery_capacity_reconciliation_result
            ),
        )
        completion_result = (
            proposed_result
            if precommit_result_factory is None
            else precommit_result_factory(proposed_result)
        )
        self._commit(context, working_context)
        return completion_result

    def _execute_phase(
        self,
        phase: SimulationPhase,
        context: SimulationContext,
        interval: StepInterval,
        physical_integration_handler: _PhysicalIntegrationHandler,
    ) -> _PhysicalIntegrationResult:
        if phase is SimulationPhase.WORLD_ENVIRONMENT:
            return self._world_environment(context, interval)
        elif phase is SimulationPhase.KNOWLEDGE_UPDATE:
            return self._knowledge_update(context, interval)
        elif phase is SimulationPhase.PLANNING:
            return self._planning(context, interval)
        elif phase is SimulationPhase.ONBOARD_ARBITRATION:
            return self._onboard_arbitration(context, interval)
        elif phase is SimulationPhase.ACTION_EXECUTION:
            return self._action_execution(context, interval)
        elif phase is SimulationPhase.PHYSICAL_INTEGRATION:
            return physical_integration_handler(context, interval)
        elif phase is SimulationPhase.FAILURE_CAPABILITY_RESOLUTION:
            return self._failure_capability_resolution(context, interval)
        elif phase is SimulationPhase.DIAGNOSTICS:
            return self._diagnostics(context, interval)
        elif phase is SimulationPhase.ADVANCE_CLOCK:
            return self._advance_clock(context, interval)
        else:
            raise ValueError(f"unsupported simulation phase {phase!r}")

    @staticmethod
    def _world_environment(
        context: SimulationContext,
        interval: StepInterval,
    ) -> None:
        return None

    @staticmethod
    def _knowledge_update(
        context: SimulationContext,
        interval: StepInterval,
    ) -> None:
        return None

    @staticmethod
    def _planning(
        context: SimulationContext,
        interval: StepInterval,
    ) -> None:
        return None

    @staticmethod
    def _onboard_arbitration(
        context: SimulationContext,
        interval: StepInterval,
    ) -> None:
        return None

    @staticmethod
    def _action_execution(
        context: SimulationContext,
        interval: StepInterval,
    ) -> None:
        return None

    @staticmethod
    def _physical_integration(
        context: SimulationContext,
        interval: StepInterval,
        eps_inputs: EPSIntervalInputs | _CoupledPhysicalIntegrationInputs | None,
    ) -> _PhysicalIntegrationResult:
        if eps_inputs is None:
            return None
        if type(eps_inputs) is _CoupledPhysicalIntegrationInputs:
            coupled_inputs = eps_inputs
            eps_interval_inputs = coupled_inputs.eps_interval_inputs
        else:
            coupled_inputs = None
            eps_interval_inputs = eps_inputs
        spacecraft_config = context.inputs.spacecraft_configuration
        active_eps_config = spacecraft_config.eps
        thermal_network = spacecraft_config.thermal.network
        eps_capability_result = compute_eps_capability(
            active_eps_config,
            context.spacecraft_state.degradation,
        )
        eps_result = compute_eps_interval_transition(
            context.spacecraft_state.battery,
            active_eps_config,
            eps_interval_inputs,
            dt_seconds=interval.dt_seconds,
            capability=eps_capability_result,
        )
        if coupled_inputs is None:
            BatteryState(eps_result.battery.end_energy_wh)
            context.spacecraft_state.battery.energy_wh = (
                eps_result.battery.end_energy_wh
            )
            return _EPSPhysicalIntegrationResult(
                eps_result,
                eps_capability_result,
            )

        thermal_coupling_result = compute_eps_thermal_interval_transition(
            context.spacecraft_state.thermal,
            thermal_network,
            coupled_inputs.thermal_inputs,
            coupled_inputs.heat_source_inputs,
            eps_result,
            dt_seconds=interval.dt_seconds,
        )
        return _complete_coupled_physical_integration(
            context,
            interval,
            eps_result=eps_result,
            thermal_coupling_result=thermal_coupling_result,
            eps_capability_result=eps_capability_result,
            solar_degradation_forcing=(
                coupled_inputs.solar_degradation_forcing
            ),
        )

    @staticmethod
    def _failure_capability_resolution(
        context: SimulationContext,
        interval: StepInterval,
    ) -> None:
        return None

    @staticmethod
    def _diagnostics(
        context: SimulationContext,
        interval: StepInterval,
    ) -> None:
        context.diagnostics.completed_steps += 1

    @staticmethod
    def _advance_clock(
        context: SimulationContext,
        interval: StepInterval,
    ) -> None:
        context.simulation_time_seconds += interval.dt_seconds

    @staticmethod
    def _commit(
        original_context: SimulationContext,
        working_context: SimulationContext,
    ) -> None:
        original_context.simulation_time_seconds = (
            working_context.simulation_time_seconds
        )
        original_context.spacecraft_state = working_context.spacecraft_state
        original_context.ground_knowledge_state = (
            working_context.ground_knowledge_state
        )
        original_context.ground_data_delivery_state = (
            working_context.ground_data_delivery_state
        )
        original_context.mission_state = working_context.mission_state
        original_context.controller_state = working_context.controller_state
        original_context.diagnostics = working_context.diagnostics


__all__ = [
    "STEP_PHASE_ORDER",
    "DownlinkEngineStepResult",
    "ImagingEngineStepAttempt",
    "ImagingStorageEngineAttempt",
    "SimulationEngine",
    "SimulationPhase",
    "StepResult",
]
