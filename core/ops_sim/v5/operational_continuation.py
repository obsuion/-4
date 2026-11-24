"""Version 3: bounded requests, explicit outcomes and replay-validated restart.

The immutable origin is an experimental initial condition. Current physical
truth remains exclusively in the schema-5 checkpoint. Replaying at most 128
requests validates history, including denials; it is not online scheduling.
"""

from dataclasses import dataclass

from .checkpoint import CheckpointState
from .context import SimulationContext
from .continuation import (ImagingAction, CoupledDownlinkAction, MAX_SCRIPT_ACTIONS,
                           _exact, _label, checked_checkpoint)
from .observation_feasibility import ScheduledObservationExecution
from .operational_protection import (ActionKind, OperationalOutcome, ProtectedRequest,
    ProtectionPolicy, StandbyAction, execute_protected_request, validate_policy, validate_request_bindings)


OPERATIONAL_SCRIPT_VERSION = 3


@dataclass(frozen=True, slots=True)
class OperationalProgram:
    version: int
    initial_checkpoint: CheckpointState
    initial_previous_execution: ScheduledObservationExecution
    policy: ProtectionPolicy
    requests: tuple[ProtectedRequest, ...]
    assumptions: tuple[str, ...]

    def __post_init__(self):
        _exact(self.version, int, "operational script version")
        if self.version != OPERATIONAL_SCRIPT_VERSION:
            raise ValueError("unsupported operational script version")
        _exact(self.initial_checkpoint, CheckpointState, "initial checkpoint")
        _exact(self.initial_previous_execution, ScheduledObservationExecution, "initial previous execution")
        _exact(self.policy, ProtectionPolicy, "policy")
        _exact(self.requests, tuple, "requests")
        if len(self.requests) > MAX_SCRIPT_ACTIONS:
            raise ValueError("operational script exceeds bounded request limit")
        for request in self.requests:
            _exact(request, ProtectedRequest, "request")
            request.__post_init__()
        ids = [r.action.action_id for r in self.requests]
        if len(set(ids)) != len(ids):
            raise ValueError("request IDs must be unique")
        _exact(self.assumptions, tuple, "assumptions")
        if not self.assumptions:
            raise ValueError("explicit assumptions required")
        for assumption in self.assumptions:
            _label(assumption, "assumption")


@dataclass(frozen=True, slots=True)
class OperationalMemory:
    outcomes: tuple[OperationalOutcome, ...]
    previous_execution: ScheduledObservationExecution

    def __post_init__(self):
        _exact(self.outcomes, tuple, "outcomes")
        if len(self.outcomes) > MAX_SCRIPT_ACTIONS:
            raise ValueError("outcome history exceeds bounded request limit")
        for outcome in self.outcomes:
            _exact(outcome, OperationalOutcome, "outcome")
            outcome.__post_init__()
        _exact(self.previous_execution, ScheduledObservationExecution, "previous execution")


def _validate_program(inputs, program):
    origin = program.initial_checkpoint.restore(inputs)
    validate_policy(program.policy, origin)
    if inputs.common_world.event_ids:
        raise ValueError("world-event execution unsupported in operational script")
    previous = program.initial_previous_execution
    if previous.scheduled_start_seconds + previous.candidate.opportunity.imaging_duration_seconds > origin.simulation_time_seconds:
        raise ValueError("initial previous acquisition ends after origin")
    # Initially carried data are legitimate reference targets. New acquisitions
    # reserve IDs even when denied; they cannot masquerade as another producer.
    produced = {r.record_id for r in origin.spacecraft_state.data_storage.stored_records}
    used = produced | {d.record.record_id for d in origin.ground_data_delivery_state.completed_deliveries}
    dt = inputs.numerical_config.timestep_seconds
    for i, request in enumerate(program.requests):
        validate_request_bindings(request, origin)
        action = request.action
        start = origin.simulation_time_seconds + i * dt
        if start + dt > inputs.common_world.horizon_seconds:
            raise ValueError("operational script exceeds horizon")
        if type(action) is ImagingAction:
            if (action.execution.scheduled_start_seconds != start
                    or action.execution.candidate.acquisition_input.imaging_duration_seconds != dt):
                raise ValueError("imaging request must match full script interval")
            if action.record_id in used:
                raise ValueError("acquisition record ID already has a producer")
            used.add(action.record_id)
            produced.add(action.record_id)
        elif type(action) is CoupledDownlinkAction:
            if (action.contact.start_time_seconds != start or action.contact.end_time_seconds != start + dt):
                raise ValueError("contact must match full script interval")
            if action.record_id not in produced:
                raise ValueError("structurally invalid data reference: no preceding producer")
        elif type(action) is not StandbyAction:
            raise TypeError("unsupported operational request")
    return origin


def _next(previous, request, outcome):
    if outcome.actual_kind is ActionKind.IMAGING:
        execution = request.action.execution
        return ScheduledObservationExecution(execution.candidate.maneuver_candidate, execution.scheduled_start_seconds)
    return previous


def validate_operational_continuation(context, program, memory):
    """Recompute outcomes and all runtime truth; rehashed inconsistencies fail."""
    from .experiment_codec import canonical_copy, canonical_content
    _exact(program, OperationalProgram, "program")
    _exact(memory, OperationalMemory, "memory")
    program, memory = canonical_copy(program), canonical_copy(memory)
    actual = checked_checkpoint(context)
    replay = _validate_program(context.inputs, program)
    cursor = len(memory.outcomes)
    if cursor > len(program.requests):
        raise ValueError("outcome cursor exceeds program")
    previous = program.initial_previous_execution
    for request, recorded in zip(program.requests[:cursor], memory.outcomes):
        result = execute_protected_request(replay, previous, request, policy=program.policy)
        if canonical_content(recorded) != canonical_content(result.outcome):
            raise ValueError("outcome history disagrees with deterministic protected execution")
        previous = _next(previous, request, result.outcome)
    if canonical_content(memory.previous_execution) != canonical_content(previous):
        raise ValueError("previous successful acquisition disagrees with outcome history")
    if canonical_content(actual) != canonical_content(checked_checkpoint(replay)):
        raise ValueError("checkpoint disagrees with protected outcome replay")


@dataclass(frozen=True, slots=True)
class OperationalState:
    context: SimulationContext
    program: OperationalProgram
    memory: OperationalMemory

    def __post_init__(self):
        validate_operational_continuation(self.context, self.program, self.memory)


def advance_operational_continuation(state):
    """Consume exactly one request/forcing interval on fresh state, atomically."""
    from .experiment_codec import canonical_copy
    _exact(state, OperationalState, "state")
    validate_operational_continuation(state.context, state.program, state.memory)
    cursor = len(state.memory.outcomes)
    if cursor == len(state.program.requests):
        raise ValueError("operational script is complete")
    program, memory = canonical_copy(state.program), canonical_copy(state.memory)
    context = checked_checkpoint(state.context).restore(canonical_copy(state.context.inputs))
    request = program.requests[cursor]
    result = execute_protected_request(context, memory.previous_execution, request, policy=program.policy)
    memory = OperationalMemory((*memory.outcomes, result.outcome), _next(memory.previous_execution, request, result.outcome))
    return OperationalState(context, program, memory)


__all__ = ["OperationalProgram", "OperationalMemory", "OperationalState", "advance_operational_continuation"]
