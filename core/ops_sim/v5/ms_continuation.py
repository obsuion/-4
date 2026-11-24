"""Version 6: bounded one-product fixed script, not the Task05B controller.

Schema 5 remains custody/physical state. This owner carries spectral/grid
associations, exact contact outcomes, prior attitude, consumed contacts and the
idempotent product ledger. Every restoration replays the entire bounded prefix.
"""

from dataclasses import dataclass

from .checkpoint import CheckpointState
from .context import SimulationContext
from .continuation import ImagingAction, _exact, _label, checked_checkpoint
from .contact_execution import ContactPlan, ContactOutcome, ConsumedContacts, execute_contact_plan
from .integration_time import IntegrationPolicy, MAX_PROGRAM_SUBSTEPS
from .ms_acquisition import InitialAttitudeEvidence, execute_ms_request, validate_ms_acquisition
from .ms_product import (MSProductSpec, MSAcquisitionPlan, MSAcquisitionEvidence,
                         MSProductAssessment, assess_ms_product, _version)
from .observation_feasibility import ScheduledObservationExecution
from .operational_protection import StandbyAction, ProtectionPolicy, validate_policy, validate_request_bindings
from .substepped_execution import TimedRequest, SubsteppedOutcome


@dataclass(frozen=True, slots=True)
class MSPhysicalRequest:
    timed: TimedRequest
    acquisition: MSAcquisitionPlan | None

    def __post_init__(self):
        _exact(self.timed, TimedRequest, "physical request")
        self.timed.__post_init__()
        if type(self.timed.request.action) is ImagingAction:
            _exact(self.acquisition, MSAcquisitionPlan, "MS acquisition")
            self.acquisition.__post_init__()
        elif type(self.timed.request.action) is not StandbyAction or self.acquisition is not None:
            raise ValueError("version 6 physical requests are explicit MS acquisition or standby")


@dataclass(frozen=True, slots=True)
class MSMissionProgram:
    version: int
    product: MSProductSpec
    initial_checkpoint: CheckpointState
    initial_attitude: InitialAttitudeEvidence
    initial_consumed_contacts: ConsumedContacts
    policy: ProtectionPolicy
    integration: IntegrationPolicy
    actions: tuple[MSPhysicalRequest | ContactPlan, ...]
    assumptions: tuple[str, ...]

    def __post_init__(self):
        _version(self.version, 6)
        for value, owner in ((self.product, MSProductSpec), (self.initial_checkpoint, CheckpointState),
                (self.initial_attitude, InitialAttitudeEvidence), (self.initial_consumed_contacts, ConsumedContacts),
                (self.policy, ProtectionPolicy), (self.integration, IntegrationPolicy)):
            _exact(value, owner, owner.__name__)
            if owner is not CheckpointState:
                value.__post_init__()
        _exact(self.actions, tuple, "actions")
        if not 1 <= len(self.actions) <= 128:
            raise ValueError("mission script exceeds bounded action history")
        boundary = self.initial_checkpoint.simulation_time_seconds
        if self.initial_attitude.at_seconds > boundary:
            raise ValueError("initial attitude is in the future")
        if any(c.end_time_seconds > boundary for c in self.initial_consumed_contacts.contacts):
            raise ValueError("initial consumed history is in the future")
        produced, ids, contacts = set(), set(), []
        work = 0
        for action in self.actions:
            if type(action) is MSPhysicalRequest:
                action.__post_init__()
                t = action.timed
                start, end, identity = t.start_time_seconds, t.end_time_seconds, t.request.action.action_id
                self.integration.duration(t.duration_seconds)
                work += 2*self.integration.substeps
                if type(t.request.action) is ImagingAction:
                    rid = t.request.action.record_id
                    if rid in produced:
                        raise ValueError("record identity already has an acquisition producer")
                    produced.add(rid)
            elif type(action) is ContactPlan:
                action.__post_init__()
                start, end, identity = action.contact.start_time_seconds, action.contact.end_time_seconds, action.contact.contact_id.value
                if not set(action.record_ids) <= produced:
                    raise ValueError("contact record requires a preceding explicit acquisition producer")
                if (len(action.record_ids)+1)*self.integration.substeps > 4096:
                    raise ValueError("contact exceeds bounded physical work")
                work += (2*len(action.record_ids)+1)*self.integration.substeps
                contacts.append(action.contact)
            else:
                raise TypeError("unsupported fixed-script action")
            if start != boundary:
                raise ValueError("physical gaps require explicit standby; actions must be consecutive")
            if identity in ids:
                raise ValueError("duplicate script action identity")
            ids.add(identity)
            boundary = end
        if work > MAX_PROGRAM_SUBSTEPS:
            raise ValueError("mission script exceeds bounded replay work")
        ConsumedContacts((*self.initial_consumed_contacts.contacts, *contacts))
        _exact(self.assumptions, tuple, "assumptions")
        if not self.assumptions:
            raise ValueError("explicit mission/hardware assumptions required")
        for assumption in self.assumptions:
            _label(assumption, "assumption")


@dataclass(frozen=True, slots=True)
class MSMissionMemory:
    outcomes: tuple[SubsteppedOutcome | ContactOutcome, ...]
    acquisitions: tuple[MSAcquisitionEvidence, ...]
    previous_execution: InitialAttitudeEvidence | ScheduledObservationExecution
    consumed_contacts: ConsumedContacts
    assessment: MSProductAssessment

    def __post_init__(self):
        _exact(self.outcomes, tuple, "outcomes")
        _exact(self.acquisitions, tuple, "acquisitions")
        if len(self.outcomes) > 128 or len(self.acquisitions) > 128:
            raise ValueError("mission memory exceeds bounded history")
        for o in self.outcomes:
            if type(o) not in (SubsteppedOutcome, ContactOutcome):
                raise TypeError("unsupported mission outcome")
            o.__post_init__()
        for a in self.acquisitions:
            _exact(a, MSAcquisitionEvidence, "acquisition evidence")
            a.__post_init__()
        if type(self.previous_execution) not in (InitialAttitudeEvidence, ScheduledObservationExecution):
            raise TypeError("explicit previous attitude/execution required")
        self.previous_execution.__post_init__()
        _exact(self.consumed_contacts, ConsumedContacts, "consumed contacts")
        self.consumed_contacts.__post_init__()
        _exact(self.assessment, MSProductAssessment, "product ledger")
        self.assessment.__post_init__()


def _origin(inputs, program):
    context = program.initial_checkpoint.restore(inputs)
    if (context.spacecraft_state.data_storage.stored_records
            or context.ground_data_delivery_state.partial_transfers
            or context.ground_data_delivery_state.completed_deliveries):
        raise ValueError("version 6 starts with empty data custody; no initial target image")
    if inputs.common_world.event_ids:
        raise ValueError("world-event execution unsupported by fixed mission script")
    validate_policy(program.policy, context)
    for action in program.actions:
        if type(action) is MSPhysicalRequest:
            end = action.timed.end_time_seconds
            validate_request_bindings(action.timed.request, context)
            if action.acquisition is not None:
                validate_ms_acquisition(action.timed.request.action,
                    inputs.spacecraft_configuration.payload.optical_acquisition, action.acquisition)
        else:
            end = action.contact.end_time_seconds
        if end > inputs.common_world.horizon_seconds:
            raise ValueError("mission script exceeds common-world horizon")
    assessment = assess_ms_product(program.product, (), context.ground_data_delivery_state, (), context.simulation_time_seconds)
    return context, MSMissionMemory((), (), program.initial_attitude, program.initial_consumed_contacts, assessment)


def _execute_next(context, program, memory):
    action = program.actions[len(memory.outcomes)]
    previous, consumed, acquisitions = memory.previous_execution, memory.consumed_contacts, memory.acquisitions
    if type(action) is MSPhysicalRequest:
        result = execute_ms_request(context, previous, action.timed, acquisition=action.acquisition,
                                    policy=program.policy, integration=program.integration)
        previous = result.previous_execution
        if result.created_record is not None:
            acquisitions += (MSAcquisitionEvidence(result.created_record, action.acquisition),)
    else:
        result = execute_contact_plan(context, action, consumed_contacts=consumed,
                                      policy=program.policy, integration=program.integration)
        consumed = result.consumed_contacts
    outcomes = (*memory.outcomes, result.outcome)
    assessment = assess_ms_product(program.product, acquisitions, context.ground_data_delivery_state,
        tuple(o for o in outcomes if type(o) is ContactOutcome), context.simulation_time_seconds)
    return MSMissionMemory(outcomes, acquisitions, previous, consumed, assessment)


def validate_ms_continuation(context, program, memory):
    from .experiment_codec import canonical_copy, canonical_content
    _exact(context, SimulationContext, "context")
    _exact(program, MSMissionProgram, "program")
    _exact(memory, MSMissionMemory, "memory")
    program, memory = canonical_copy((program, memory))
    actual = checked_checkpoint(context)
    replay, expected = _origin(context.inputs, program)
    if len(memory.outcomes) > len(program.actions):
        raise ValueError("mission cursor exceeds script")
    for _ in memory.outcomes:
        expected = _execute_next(replay, program, expected)
    if canonical_content(memory) != canonical_content(expected):
        raise ValueError("mission causal memory/credit disagrees with execution replay")
    if canonical_content(actual) != canonical_content(checked_checkpoint(replay)):
        raise ValueError("mission checkpoint disagrees with execution replay")


@dataclass(frozen=True, slots=True)
class MSMissionState:
    context: SimulationContext
    program: MSMissionProgram
    memory: MSMissionMemory

    def __post_init__(self):
        validate_ms_continuation(self.context, self.program, self.memory)


def start_ms_mission(inputs, program):
    from .experiment_codec import canonical_copy
    _exact(program, MSMissionProgram, "program")
    inputs, program = canonical_copy((inputs, program))
    context, memory = _origin(inputs, program)
    return MSMissionState(context, program, memory)


def advance_ms_mission(state):
    """Return a fully validated new boundary; no external mutation on any failure."""
    from .experiment_codec import canonical_copy
    _exact(state, MSMissionState, "mission state")
    state.__post_init__()
    if len(state.memory.outcomes) == len(state.program.actions):
        raise ValueError("mission fixed script is complete")
    program, memory = canonical_copy((state.program, state.memory))
    context = checked_checkpoint(state.context).restore(canonical_copy(state.context.inputs))
    memory = _execute_next(context, program, memory)
    return MSMissionState(context, program, memory)
