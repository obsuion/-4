"""Version 5: completed-contact restart with causal consumed-contact memory."""

from dataclasses import dataclass

from .checkpoint import CheckpointState
from .context import SimulationContext
from .continuation import _exact, _label, checked_checkpoint, MAX_SCRIPT_ACTIONS
from .contact_execution import ContactPlan, ConsumedContacts, ContactOutcome, execute_contact_plan
from .integration_time import IntegrationPolicy, MAX_PROGRAM_SUBSTEPS
from .observation_feasibility import ScheduledObservationExecution
from .operational_protection import ProtectionPolicy, validate_policy


@dataclass(frozen=True, slots=True)
class ContactProgram:
    version: int
    initial_checkpoint: CheckpointState
    initial_previous_execution: ScheduledObservationExecution
    initial_consumed_contacts: ConsumedContacts
    policy: ProtectionPolicy
    integration: IntegrationPolicy
    plans: tuple[ContactPlan, ...]
    assumptions: tuple[str, ...]

    def __post_init__(self):
        _exact(self.version, int, "contact program version")
        if self.version != 5:
            raise ValueError("unsupported contact program version")
        for value, owner in ((self.initial_checkpoint, CheckpointState),
                (self.initial_previous_execution, ScheduledObservationExecution),
                (self.initial_consumed_contacts, ConsumedContacts), (self.policy, ProtectionPolicy),
                (self.integration, IntegrationPolicy)):
            _exact(value, owner, owner.__name__)
            if owner is not CheckpointState:
                value.__post_init__()
        _exact(self.plans, tuple, "contact plans")
        if len(self.plans)+len(self.initial_consumed_contacts.contacts) > MAX_SCRIPT_ACTIONS:
            raise ValueError("contact program exceeds bounded history")
        for plan in self.plans:
            _exact(plan, ContactPlan, "plan")
            plan.__post_init__()
            if (len(plan.record_ids)+1)*self.integration.substeps > 4096:
                raise ValueError("contact program exceeds per-contact physical work")
        if sum((2*len(p.record_ids)+1)*self.integration.substeps for p in self.plans) > MAX_PROGRAM_SUBSTEPS:
            raise ValueError("contact program exceeds bounded numerical replay work")
        ConsumedContacts((*self.initial_consumed_contacts.contacts, *(p.contact for p in self.plans)))
        boundary = self.initial_checkpoint.simulation_time_seconds
        if any(c.end_time_seconds > boundary for c in self.initial_consumed_contacts.contacts):
            raise ValueError("origin consumed contacts exceed origin clock")
        for plan in self.plans:
            if plan.contact.start_time_seconds != boundary:
                raise ValueError("contact program requires consecutive declared physical contacts")
            boundary = plan.contact.end_time_seconds
        previous = self.initial_previous_execution
        if previous.scheduled_start_seconds+previous.candidate.opportunity.imaging_duration_seconds > self.initial_checkpoint.simulation_time_seconds:
            raise ValueError("prior acquisition ends after origin")
        _exact(self.assumptions, tuple, "assumptions")
        if not self.assumptions:
            raise ValueError("explicit contact-model assumptions required")
        for assumption in self.assumptions:
            _label(assumption, "assumption")


@dataclass(frozen=True, slots=True)
class ContactMemory:
    outcomes: tuple[ContactOutcome, ...]
    consumed_contacts: ConsumedContacts
    previous_execution: ScheduledObservationExecution

    def __post_init__(self):
        _exact(self.outcomes, tuple, "contact outcomes")
        if len(self.outcomes) > MAX_SCRIPT_ACTIONS:
            raise ValueError("outcomes exceed bounded history")
        for outcome in self.outcomes:
            _exact(outcome, ContactOutcome, "outcome")
            outcome.__post_init__()
        _exact(self.consumed_contacts, ConsumedContacts, "consumed contacts")
        self.consumed_contacts.__post_init__()
        _exact(self.previous_execution, ScheduledObservationExecution, "prior acquisition")
        self.previous_execution.__post_init__()

    @property
    def transmitted_bits(self):
        return sum(o.transmitted_bits for o in self.outcomes)

    @property
    def numerical_substeps(self):
        return sum(o.accounting.numerical_substeps for o in self.outcomes)

    @property
    def evaluated_eps_substeps(self):
        return sum(o.evaluated_eps_substeps for o in self.outcomes)


def validate_contact_continuation(context, program, memory):
    from .experiment_codec import canonical_copy, canonical_content
    _exact(program, ContactProgram, "program")
    _exact(memory, ContactMemory, "memory")
    program, memory = canonical_copy(program), canonical_copy(memory)
    actual = checked_checkpoint(context)
    replay = program.initial_checkpoint.restore(context.inputs)
    validate_policy(program.policy, replay)
    if context.inputs.common_world.event_ids:
        raise ValueError("world-event execution unsupported")
    if any(p.contact.end_time_seconds > context.inputs.common_world.horizon_seconds for p in program.plans):
        raise ValueError("program contact exceeds horizon")
    if len(memory.outcomes) > len(program.plans):
        raise ValueError("outcome cursor exceeds program")
    consumed = program.initial_consumed_contacts
    for plan, recorded in zip(program.plans[:len(memory.outcomes)], memory.outcomes):
        result = execute_contact_plan(replay, plan, consumed_contacts=consumed,
            policy=program.policy, integration=program.integration)
        if canonical_content(result.outcome) != canonical_content(recorded):
            raise ValueError("contact outcome disagrees with deterministic replay")
        consumed = result.consumed_contacts
    if canonical_content(consumed) != canonical_content(memory.consumed_contacts):
        raise ValueError("consumed-contact memory disagrees with replay")
    if canonical_content(memory.previous_execution) != canonical_content(program.initial_previous_execution):
        raise ValueError("contact execution must preserve prior acquisition")
    if canonical_content(actual) != canonical_content(checked_checkpoint(replay)):
        raise ValueError("checkpoint disagrees with contact replay")


@dataclass(frozen=True, slots=True)
class ContactState:
    context: SimulationContext
    program: ContactProgram
    memory: ContactMemory

    def __post_init__(self):
        validate_contact_continuation(self.context, self.program, self.memory)


def advance_contact_continuation(state):
    """Fresh completed-contact state; external context/memory untouched on failure."""
    from .experiment_codec import canonical_copy
    _exact(state, ContactState, "contact state")
    state.__post_init__()
    cursor = len(state.memory.outcomes)
    if cursor == len(state.program.plans):
        raise ValueError("contact program is complete")
    program, memory = canonical_copy(state.program), canonical_copy(state.memory)
    context = checked_checkpoint(state.context).restore(canonical_copy(state.context.inputs))
    result = execute_contact_plan(context, program.plans[cursor], consumed_contacts=memory.consumed_contacts,
                                  policy=program.policy, integration=program.integration)
    next_memory = ContactMemory((*memory.outcomes, result.outcome), result.consumed_contacts, memory.previous_execution)
    return ContactState(context, program, next_memory)


__all__ = ["ContactProgram", "ContactMemory", "ContactState", "advance_contact_continuation"]
