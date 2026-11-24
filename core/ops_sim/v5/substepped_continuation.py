"""Version 4: explicit physical intervals and bounded dyadic execution.

Only completed actions restart. Schema 5 remains the physical/data authority;
bounded deterministic replay validates the recorded sampled outcomes/memory.
Versions 1/2/3 retain their original fixed-step interpretation.
"""

from dataclasses import dataclass

from .checkpoint import CheckpointState
from .context import SimulationContext
from .continuation import (ImagingAction, CoupledDownlinkAction, MAX_SCRIPT_ACTIONS,
                           _exact, _label, checked_checkpoint)
from .integration_time import IntegrationPolicy, MAX_PROGRAM_SUBSTEPS
from .observation_feasibility import ScheduledObservationExecution
from .operational_protection import ProtectionPolicy, validate_policy, validate_request_bindings
from .substepped_execution import TimedRequest, SubsteppedOutcome, execute_substepped_request


SUBSTEPPED_SCRIPT_VERSION = 4


@dataclass(frozen=True, slots=True)
class SubsteppedProgram:
    version: int
    initial_checkpoint: CheckpointState
    initial_previous_execution: ScheduledObservationExecution
    policy: ProtectionPolicy
    integration: IntegrationPolicy
    requests: tuple[TimedRequest, ...]
    assumptions: tuple[str, ...]

    def __post_init__(self):
        _exact(self.version, int, "substepped script version")
        if self.version != SUBSTEPPED_SCRIPT_VERSION:
            raise ValueError("unsupported substepped script version")
        _exact(self.initial_checkpoint, CheckpointState, "initial checkpoint")
        _exact(self.initial_previous_execution, ScheduledObservationExecution, "initial previous execution")
        _exact(self.policy, ProtectionPolicy, "policy")
        _exact(self.integration, IntegrationPolicy, "integration")
        self.integration.__post_init__()
        _exact(self.requests, tuple, "requests")
        if len(self.requests) > MAX_SCRIPT_ACTIONS:
            raise ValueError("script exceeds bounded request limit")
        if 2 * len(self.requests) * self.integration.substeps > MAX_PROGRAM_SUBSTEPS:
            raise ValueError("script exceeds bounded replay work; not a convergence result")
        for request in self.requests:
            _exact(request, TimedRequest, "timed request")
            request.__post_init__()
            self.integration.duration(request.duration_seconds)
        ids = [r.request.action.action_id for r in self.requests]
        if len(set(ids)) != len(ids):
            raise ValueError("request IDs must be unique")
        _exact(self.assumptions, tuple, "assumptions")
        if not self.assumptions:
            raise ValueError("explicit assumptions required")
        for assumption in self.assumptions:
            _label(assumption, "assumption")


@dataclass(frozen=True, slots=True)
class SubsteppedMemory:
    outcomes: tuple[SubsteppedOutcome, ...]
    previous_execution: ScheduledObservationExecution

    def __post_init__(self):
        _exact(self.outcomes, tuple, "outcomes")
        if len(self.outcomes) > MAX_SCRIPT_ACTIONS:
            raise ValueError("outcome history exceeds bounded request limit")
        for outcome in self.outcomes:
            _exact(outcome, SubsteppedOutcome, "outcome")
            outcome.__post_init__()
        _exact(self.previous_execution, ScheduledObservationExecution, "previous execution")

    @property
    def numerical_substeps(self):
        return sum(o.accounting.numerical_substeps for o in self.outcomes)

    @property
    def evaluated_eps_substeps(self):
        return sum(o.evaluated_eps_substeps for o in self.outcomes)

    @property
    def evaluated_thermal_substeps(self):
        return sum(o.evaluated_thermal_substeps for o in self.outcomes)


def _validate_program(inputs, program):
    origin = program.initial_checkpoint.restore(inputs)
    validate_policy(program.policy, origin)
    if inputs.common_world.event_ids:
        raise ValueError("world-event execution unsupported in substepped script")
    previous = program.initial_previous_execution
    if previous.scheduled_start_seconds + previous.candidate.opportunity.imaging_duration_seconds > origin.simulation_time_seconds:
        raise ValueError("initial previous acquisition ends after origin")
    produced = {r.record_id for r in origin.spacecraft_state.data_storage.stored_records}
    used = produced | {d.record.record_id for d in origin.ground_data_delivery_state.completed_deliveries}
    boundary = origin.simulation_time_seconds
    for timed in program.requests:
        validate_request_bindings(timed.request, origin)
        if timed.start_time_seconds != boundary or timed.end_time_seconds > inputs.common_world.horizon_seconds:
            raise ValueError("script must cover consecutive physical intervals within the horizon")
        boundary = timed.end_time_seconds
        action = timed.request.action
        if type(action) is ImagingAction:
            if action.record_id in used:
                raise ValueError("acquisition record ID already has a producer")
            used.add(action.record_id)
            produced.add(action.record_id)
        elif type(action) is CoupledDownlinkAction and action.record_id not in produced:
            raise ValueError("structurally invalid data reference: no preceding producer")
    return origin


def validate_substepped_continuation(context, program, memory):
    from .experiment_codec import canonical_copy, canonical_content
    _exact(program, SubsteppedProgram, "program")
    _exact(memory, SubsteppedMemory, "memory")
    program, memory = canonical_copy(program), canonical_copy(memory)
    actual = checked_checkpoint(context)
    replay = _validate_program(context.inputs, program)
    cursor = len(memory.outcomes)
    if cursor > len(program.requests):
        raise ValueError("outcome cursor exceeds program")
    previous = program.initial_previous_execution
    for request, recorded in zip(program.requests[:cursor], memory.outcomes):
        result = execute_substepped_request(replay, previous, request,
            policy=program.policy, integration=program.integration)
        if canonical_content(recorded) != canonical_content(result.outcome):
            raise ValueError("outcome history disagrees with deterministic substepped execution")
        previous = result.previous_execution
    if canonical_content(memory.previous_execution) != canonical_content(previous):
        raise ValueError("previous successful acquisition disagrees with history")
    if canonical_content(actual) != canonical_content(checked_checkpoint(replay)):
        raise ValueError("checkpoint disagrees with substepped outcome replay")


@dataclass(frozen=True, slots=True)
class SubsteppedState:
    context: SimulationContext
    program: SubsteppedProgram
    memory: SubsteppedMemory

    def __post_init__(self):
        validate_substepped_continuation(self.context, self.program, self.memory)


def advance_substepped_continuation(state):
    """Return fresh completed state/memory; caller state remains untouched on failure."""
    from .experiment_codec import canonical_copy
    _exact(state, SubsteppedState, "state")
    validate_substepped_continuation(state.context, state.program, state.memory)
    cursor = len(state.memory.outcomes)
    if cursor == len(state.program.requests):
        raise ValueError("substepped script is complete")
    program, memory = canonical_copy(state.program), canonical_copy(state.memory)
    context = checked_checkpoint(state.context).restore(canonical_copy(state.context.inputs))
    result = execute_substepped_request(context, memory.previous_execution, program.requests[cursor],
                                       policy=program.policy, integration=program.integration)
    memory = SubsteppedMemory((*memory.outcomes, result.outcome), result.previous_execution)
    return SubsteppedState(context, program, memory)


__all__ = ["SubsteppedProgram", "SubsteppedMemory", "SubsteppedState", "advance_substepped_continuation"]
