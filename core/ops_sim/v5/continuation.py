"""Bounded deterministic script continuation, not a mission controller.

Full-step imaging-to-storage, legacy data-only downlink and explicitly coupled
downlink are supported. External forcing is explicit per action. No queues,
RNG, callbacks or event processing are inferred.
"""

from dataclasses import dataclass

from .checkpoint import CheckpointState
from .communications import ServiceableGroundContact
from .context import SimulationContext
from .coupled_downlink import CoupledDownlinkAttempt, CoupledDownlinkInputs
from .data_delivery import CompletedAcquisitionDelivery, DownlinkTransferProgress
from .degradation import SolarDegradationForcingInput
from .downlink import DownlinkTransmissionStatus, evaluate_downlink_transmission
from .engine import SimulationEngine
from .ids import AcquisitionDataRecordId
from .imaging_execution import ScheduledObservationAcquisitionExecution
from .imaging_resources import AcquisitionEPSIntervalEnvironment
from .observation_feasibility import ScheduledObservationExecution
from .onboard_data import OnboardAcquisitionDataRecord
from .payload import compute_optical_acquisition
from .thermal import ThermalIntervalInputs
from .thermal_coupling import ThermalHeatSourceInputs
from .thermal_routing import ComponentHeatRoutingConfig


SCRIPT_VERSION = 1
COUPLED_SCRIPT_VERSION = 2
MAX_SCRIPT_ACTIONS = 128
RANDOMNESS_MODE = "deterministic-no-rng"


def _exact(value, owner, name):
    if type(value) is not owner:
        raise TypeError(f"{name} must be an exact {owner.__name__}")


def _label(value, name):
    _exact(value, str, name)
    value.encode("utf-8", errors="strict")
    if not value or value != value.strip():
        raise ValueError(f"{name} must be nonempty canonical text")


@dataclass(frozen=True, slots=True)
class ImagingAction:
    action_id: str
    execution: ScheduledObservationAcquisitionExecution
    record_id: AcquisitionDataRecordId
    environment: AcquisitionEPSIntervalEnvironment
    routing_config: ComponentHeatRoutingConfig
    thermal_inputs: ThermalIntervalInputs
    external_heat_sources: ThermalHeatSourceInputs
    solar_degradation_forcing: SolarDegradationForcingInput | None

    def __post_init__(self):
        _label(self.action_id, "action_id")
        for name, owner in (
            ("execution", ScheduledObservationAcquisitionExecution),
            ("record_id", AcquisitionDataRecordId),
            ("environment", AcquisitionEPSIntervalEnvironment),
            ("routing_config", ComponentHeatRoutingConfig),
            ("thermal_inputs", ThermalIntervalInputs),
            ("external_heat_sources", ThermalHeatSourceInputs),
        ):
            _exact(getattr(self, name), owner, name)
        if self.solar_degradation_forcing is not None:
            _exact(self.solar_degradation_forcing, SolarDegradationForcingInput, "solar forcing")


@dataclass(frozen=True, slots=True)
class DownlinkAction:
    action_id: str
    contact: ServiceableGroundContact
    record_id: AcquisitionDataRecordId

    def __post_init__(self):
        _label(self.action_id, "action_id")
        _exact(self.contact, ServiceableGroundContact, "contact")
        _exact(self.record_id, AcquisitionDataRecordId, "record_id")


@dataclass(frozen=True, slots=True)
class CoupledDownlinkAction:
    action_id: str
    contact: ServiceableGroundContact
    record_id: AcquisitionDataRecordId
    physical_inputs: CoupledDownlinkInputs

    def __post_init__(self):
        _label(self.action_id, "action_id")
        _exact(self.contact, ServiceableGroundContact, "contact")
        _exact(self.record_id, AcquisitionDataRecordId, "record_id")
        _exact(self.physical_inputs, CoupledDownlinkInputs, "physical_inputs")


class ContinuationElectricalDenial(ValueError):
    """Valid denied choice; caller state and executed prefix remain unchanged."""

    def __init__(self, action_id: str, attempt: CoupledDownlinkAttempt):
        self.action_id = action_id
        self.attempt = attempt
        super().__init__(f"action {action_id}: {attempt.denial_reason.value}; time_advanced=False")


@dataclass(frozen=True, slots=True)
class ContinuationProgram:
    version: int
    start_time_seconds: int
    initial_completed_steps: int
    initial_previous_execution: ScheduledObservationExecution
    actions: tuple[ImagingAction | DownlinkAction | CoupledDownlinkAction, ...]
    assumptions: tuple[str, ...]

    def __post_init__(self):
        _exact(self.version, int, "script version")
        if self.version not in (SCRIPT_VERSION, COUPLED_SCRIPT_VERSION):
            raise ValueError("unsupported script version")
        for name in ("start_time_seconds", "initial_completed_steps"):
            _exact(getattr(self, name), int, name)
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        _exact(self.initial_previous_execution, ScheduledObservationExecution, "initial previous execution")
        _exact(self.actions, tuple, "actions")
        if len(self.actions) > MAX_SCRIPT_ACTIONS:
            raise ValueError("script exceeds the bounded action limit")
        for action in self.actions:
            if type(action) not in (ImagingAction, DownlinkAction, CoupledDownlinkAction):
                raise TypeError("unsupported continuation action")
            if type(action) is CoupledDownlinkAction and self.version != COUPLED_SCRIPT_VERSION:
                raise ValueError("coupled downlink requires script version 2")
        ids = [action.action_id for action in self.actions]
        if len(set(ids)) != len(ids):
            raise ValueError("action IDs must be unique")
        _exact(self.assumptions, tuple, "assumptions")
        if not self.assumptions:
            raise ValueError("explicit assumptions are required")
        for assumption in self.assumptions:
            _label(assumption, "assumption")


@dataclass(frozen=True, slots=True)
class ContinuationMemory:
    """Executed prefix owns the action/forcing cursor; prior attitude is required."""

    executed_action_ids: tuple[str, ...]
    previous_execution: ScheduledObservationExecution

    def __post_init__(self):
        _exact(self.executed_action_ids, tuple, "executed_action_ids")
        for action_id in self.executed_action_ids:
            _label(action_id, "executed action ID")
        _exact(self.previous_execution, ScheduledObservationExecution, "previous_execution")


def checked_checkpoint(context: SimulationContext) -> CheckpointState:
    """Reject schema-5 round-trip loss rather than extend its numeric contract."""
    from .experiment_codec import canonical_content

    _exact(context, SimulationContext, "context")
    canonical_content(context.inputs)
    snapshot = CheckpointState.from_context(context)
    reconstructed = CheckpointState.from_dict(snapshot.to_dict())
    if canonical_content(snapshot) != canonical_content(reconstructed):
        raise ValueError("runtime state is not losslessly representable by schema 5")
    reconstructed.restore(context.inputs)
    return reconstructed


def validate_continuation(context, program, memory):
    """Rebuild nested contracts and check prefix, clock, attitude and data ledger."""
    from .experiment_codec import canonical_content, canonical_copy

    _exact(program, ContinuationProgram, "program")
    _exact(memory, ContinuationMemory, "memory")
    program, memory = canonical_copy(program), canonical_copy(memory)
    snapshot = checked_checkpoint(context)
    inputs = context.inputs
    if inputs.common_world.event_ids:
        raise ValueError("world-event execution is unsupported by this script mode")
    dt = inputs.numerical_config.timestep_seconds
    previous = program.initial_previous_execution
    if previous.scheduled_start_seconds + previous.candidate.opportunity.imaging_duration_seconds > program.start_time_seconds:
        raise ValueError("initial previous acquisition ends after script origin")
    produced_ids = set()
    for index, action in enumerate(program.actions):
        start = program.start_time_seconds + index * dt
        if start + dt > inputs.common_world.horizon_seconds:
            raise ValueError("script exceeds the world horizon")
        if type(action) is ImagingAction:
            execution = action.execution
            if execution.scheduled_start_seconds != start or execution.candidate.acquisition_input.imaging_duration_seconds != dt:
                raise ValueError("imaging action must match one complete engine step")
            if action.record_id in produced_ids:
                raise ValueError("script acquisition record IDs must be unique")
            produced_ids.add(action.record_id)
        else:
            if action.contact.start_time_seconds != start or action.contact.end_time_seconds != start + dt:
                raise ValueError("contact must match one complete engine step")
            if action.record_id not in produced_ids:
                raise ValueError("downlink action has no preceding script acquisition")
    cursor = len(memory.executed_action_ids)
    if memory.executed_action_ids != tuple(a.action_id for a in program.actions[:cursor]) or cursor > len(program.actions):
        raise ValueError("memory must identify the exact executed program prefix")
    if context.simulation_time_seconds != program.start_time_seconds + cursor * dt:
        raise ValueError("memory cursor does not match checkpoint time")
    if context.diagnostics.completed_steps != program.initial_completed_steps + cursor:
        raise ValueError("memory cursor does not match checkpoint completed steps")

    # Derived validation ledger only: authoritative custody stays in checkpoint.
    stored, progress, completed = {}, {}, []
    for action in program.actions[:cursor]:
        if type(action) is ImagingAction:
            acquisition = action.execution.candidate
            opportunity = acquisition.maneuver_candidate.opportunity
            proposal = compute_optical_acquisition(
                inputs.spacecraft_configuration.payload.optical_acquisition,
                acquisition.acquisition_input,
            )
            record = OnboardAcquisitionDataRecord(
                action.record_id, opportunity.request_id, opportunity.opportunity_id,
                action.execution.scheduled_start_seconds,
                acquisition.acquisition_input.imaging_duration_seconds,
                acquisition.acquisition_input.channel_selection,
                proposal.uncompressed_equivalent_bits, proposal.uncompressed_equivalent_bits,
            )
            stored[record.record_id] = record
            previous = ScheduledObservationExecution(acquisition.maneuver_candidate, action.execution.scheduled_start_seconds)
        else:
            if action.record_id not in stored:
                raise ValueError("executed prefix services an unavailable record")
            result = evaluate_downlink_transmission(
                inputs.spacecraft_configuration.communications,
                action.contact, stored[action.record_id], progress.get(action.record_id),
            )
            if result.status is DownlinkTransmissionStatus.COMPLETE:
                completed.append(CompletedAcquisitionDelivery(stored.pop(action.record_id), action.contact))
                progress.pop(action.record_id, None)
            else:
                progress[action.record_id] = DownlinkTransferProgress(
                    action.record_id, result.progress_after_equivalent_bits,
                )
    if canonical_content(previous) != canonical_content(memory.previous_execution):
        raise ValueError("previous execution is inconsistent with the executed prefix")
    actual = (snapshot.spacecraft.data_storage.stored_records,
              snapshot.ground_data_delivery.partial_transfers,
              snapshot.ground_data_delivery.completed_deliveries)
    expected = (tuple(stored.values()), tuple(progress.values()), tuple(completed))
    if canonical_content(actual) != canonical_content(expected):
        raise ValueError("checkpoint custody/progress does not match the executed prefix")


@dataclass(frozen=True, slots=True)
class ContinuationState:
    context: SimulationContext
    program: ContinuationProgram
    memory: ContinuationMemory

    def __post_init__(self):
        validate_continuation(self.context, self.program, self.memory)


def advance_continuation(state: ContinuationState) -> ContinuationState:
    """Execute one script choice on fresh state; exceptions never mutate the caller."""
    from .experiment_codec import canonical_copy

    _exact(state, ContinuationState, "state")
    validate_continuation(state.context, state.program, state.memory)
    cursor = len(state.memory.executed_action_ids)
    if cursor == len(state.program.actions):
        raise ValueError("script is complete")
    program, memory = canonical_copy(state.program), canonical_copy(state.memory)
    inputs = canonical_copy(state.context.inputs)
    context = checked_checkpoint(state.context).restore(inputs)
    action = program.actions[cursor]
    previous = memory.previous_execution
    engine = SimulationEngine()
    if type(action) is ImagingAction:
        attempt = engine.step_imaging_to_storage(
            context, previous, action.execution, record_id=action.record_id,
            environment=action.environment, routing_config=action.routing_config,
            thermal_inputs=action.thermal_inputs, external_heat_sources=action.external_heat_sources,
            solar_degradation_forcing=action.solar_degradation_forcing,
        )
        if attempt.step_result is None:
            raise ValueError("script imaging action was not authorized")
        previous = ScheduledObservationExecution(action.execution.candidate.maneuver_candidate, action.execution.scheduled_start_seconds)
    elif type(action) is CoupledDownlinkAction:
        attempt = engine.step_coupled_downlink(
            context, action.contact, record_id=action.record_id,
            physical_inputs=action.physical_inputs,
        )
        if not attempt.authorized:
            raise ContinuationElectricalDenial(action.action_id, attempt)
    else:
        engine.step_downlink(context, action.contact, record_id=action.record_id)
    memory = ContinuationMemory(memory.executed_action_ids + (action.action_id,), previous)
    return ContinuationState(context, program, memory)


__all__ = ["ImagingAction", "DownlinkAction", "CoupledDownlinkAction", "ContinuationElectricalDenial",
           "ContinuationProgram", "ContinuationMemory", "ContinuationState", "advance_continuation"]
