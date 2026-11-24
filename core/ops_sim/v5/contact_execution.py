"""Task 04B: explicit ordered service, exact time, one atomic physical contact.

Schema-5 custody keeps the ORIGINAL completing contact. Version-5 outcomes
own exact completion offsets and conservative integer completion timestamps.
No controller selection, retry, mid-contact checkpoint or continuous safety.
"""

from dataclasses import dataclass, fields
from fractions import Fraction
from math import ceil, isfinite, fsum

from .communications import ServiceableGroundContact, compute_downlink_capacity
from .continuation import _exact, checked_checkpoint
from .coupled_downlink import CoupledDownlinkInputs, validate_coupled_downlink_inputs
from .data_delivery import DownlinkTransferProgress, CompletedAcquisitionDelivery, _validate_acquisition_completed_by
from .degradation import SolarDegradationForcingInput
from .eps_system import EPSIntervalInputs
from .ids import AcquisitionDataRecordId
from .integration_time import IntegrationPolicy, RationalSeconds, MAX_ACTION_SECONDS
from .onboard_data import OnboardAcquisitionDataRecord
from .operational_protection import (StandbyInputs, ProtectionPolicy, ActionKind, validate_policy,
                                    _validate_forcing, _violations)
from .state import OperationalMode, FDIRState
from .substepped_execution import (PhysicalSample, ActionAccounting, SubstepAvailability, SampledReason,
                                  _physical_substep, _sample, _aggregate, _commit_action,
                                  _validate_physical_samples)


MAX_CONTACT_RECORDS = 32
MAX_CONSUMED_CONTACTS = 128
MAX_CONTACT_BITS = 2**40  # common sample numerator stays <= 2**52 at level 12
TIME_CONTRACT = "integer-bits-rate-rational-segments-v1"


def _integer_quantity(value, name, *, positive=False):
    if type(value) not in (int, float) or not isfinite(value) or int(value) != value:
        raise ValueError(f"{name} must be an exactly represented integer")
    value = int(value)
    if not (1 if positive else 0) <= value <= MAX_CONTACT_BITS:
        raise ValueError(f"{name} exceeds the bounded integer-bit/rate domain")
    return value


def _natural(value, name):
    _exact(value, int, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


@dataclass(frozen=True, slots=True)
class ContactPlan:
    contact: ServiceableGroundContact
    record_ids: tuple[AcquisitionDataRecordId, ...]
    tx_inputs: CoupledDownlinkInputs
    idle_inputs: StandbyInputs
    time_contract: str = TIME_CONTRACT

    def __post_init__(self):
        for value, owner in ((self.contact, ServiceableGroundContact),
                             (self.tx_inputs, CoupledDownlinkInputs), (self.idle_inputs, StandbyInputs)):
            _exact(value, owner, owner.__name__)
            value.__post_init__()
        _exact(self.record_ids, tuple, "record sequence")
        if len(self.record_ids) > MAX_CONTACT_RECORDS:
            raise ValueError("contact record sequence exceeds bounded work")
        for record in self.record_ids:
            _exact(record, AcquisitionDataRecordId, "record ID")
            record.__post_init__()
        if len(set(self.record_ids)) != len(self.record_ids):
            raise ValueError("duplicate selected record IDs")
        if type(self.time_contract) is not str or self.time_contract != TIME_CONTRACT:
            raise ValueError("unsupported exact service-time contract")
        if self.duration_seconds > MAX_ACTION_SECONDS:
            raise ValueError("contact duration exceeds time representation")

    @property
    def duration_seconds(self):
        return self.contact.end_time_seconds - self.contact.start_time_seconds


@dataclass(frozen=True, slots=True)
class ConsumedContacts:
    """Immutable causal memory, never diagnostics or inferred from deliveries."""
    contacts: tuple[ServiceableGroundContact, ...]

    def __post_init__(self):
        _exact(self.contacts, tuple, "consumed contacts")
        if len(self.contacts) > MAX_CONSUMED_CONTACTS:
            raise ValueError("consumed history exceeds bounded continuation")
        for contact in self.contacts:
            _exact(contact, ServiceableGroundContact, "consumed contact")
            contact.__post_init__()
        if len({c.contact_id for c in self.contacts}) != len(self.contacts):
            raise ValueError("contact identity already consumed")
        if any(a.end_time_seconds > b.start_time_seconds for a, b in zip(self.contacts, self.contacts[1:])):
            raise ValueError("consumed physical contact intervals overlap or are unordered")


@dataclass(frozen=True, slots=True)
class ContactTrace:
    """Sample offset = numerator / denominator seconds from contact origin."""
    start_offset: RationalSeconds
    end_offset: RationalSeconds
    denominator: int
    samples: tuple[PhysicalSample, ...]

    def __post_init__(self):
        for value in (self.start_offset, self.end_offset):
            _exact(value, RationalSeconds, "offset")
            value.__post_init__()
        if self.start_offset.fraction >= self.end_offset.fraction:
            raise ValueError("trace requires a positive segment")
        _exact(self.denominator, int, "sample denominator")
        if not 1 <= self.denominator <= 2**52:
            raise ValueError("sample denominator outside bound")
        _exact(self.samples, tuple, "samples")
        if not 1 <= len(self.samples) <= 4097:
            raise ValueError("trace must be a bounded computed prefix")
        for sample in self.samples:
            _exact(sample, PhysicalSample, "sample")
            sample.__post_init__()
        offsets = [Fraction(s.offset_numerator_seconds, self.denominator) for s in self.samples]
        if offsets[0] != self.start_offset.fraction or offsets[-1] > self.end_offset.fraction:
            raise ValueError("sample times outside exact segment")
        if any(a >= b for a, b in zip(offsets, offsets[1:])):
            raise ValueError("sample offsets must increase")
        if self.samples[0].unmet_load_w != 0:
            raise ValueError("segment origin has no preceding EPS interval")

    @property
    def complete(self):
        return Fraction(self.samples[-1].offset_numerator_seconds, self.denominator) == self.end_offset.fraction


@dataclass(frozen=True, slots=True)
class ContactSegment:
    record_id: AcquisitionDataRecordId | None
    trace: ContactTrace
    accounting: ActionAccounting

    def __post_init__(self):
        if self.record_id is not None:
            _exact(self.record_id, AcquisitionDataRecordId, "segment record")
        _exact(self.trace, ContactTrace, "segment trace")
        _exact(self.accounting, ActionAccounting, "segment accounting")
        self.trace.__post_init__()
        self.accounting.__post_init__()
        if not self.trace.complete or len(self.trace.samples) != self.accounting.numerical_substeps + 1:
            raise ValueError("actual segment must contain all physical endpoints")

    @property
    def transmitter_on(self):
        return self.record_id is not None


@dataclass(frozen=True, slots=True)
class RecordService:
    record: OnboardAcquisitionDataRecord
    progress_before_bits: int
    transmitted_bits: int
    progress_after_bits: int
    start_offset: RationalSeconds
    end_offset: RationalSeconds
    completed: bool
    completion_time_seconds: int | None

    def __post_init__(self):
        _exact(self.record, OnboardAcquisitionDataRecord, "record")
        self.record.__post_init__()
        total = _integer_quantity(self.record.stored_equivalent_bits, "record bits", positive=True)
        for name in ("progress_before_bits", "transmitted_bits", "progress_after_bits"):
            _exact(getattr(self, name), int, name)
            _integer_quantity(getattr(self, name), name)
        if not (self.transmitted_bits > 0 and self.progress_before_bits < self.progress_after_bits <= total):
            raise ValueError("service exceeds remaining record bits")
        if self.progress_after_bits != self.progress_before_bits + self.transmitted_bits:
            raise ValueError("per-record bit conservation failed")
        for t in (self.start_offset, self.end_offset):
            _exact(t, RationalSeconds, "service offset")
            t.__post_init__()
        if self.start_offset.fraction >= self.end_offset.fraction:
            raise ValueError("service duration must be positive")
        _exact(self.completed, bool, "completed")
        if self.completed != (self.progress_after_bits == total):
            raise ValueError("completion disagrees with record progress")
        if self.completed:
            _natural(self.completion_time_seconds, "conservative completion time")
        elif self.completion_time_seconds is not None:
            raise ValueError("partial record has no completion timestamp")


@dataclass(frozen=True, slots=True)
class ContactAttempt:
    record_id: AcquisitionDataRecordId
    availability: SubstepAvailability
    predicted_trace: ContactTrace
    evaluated_eps_substeps: int
    evaluated_thermal_substeps: int

    def __post_init__(self):
        for value, owner in ((self.record_id, AcquisitionDataRecordId),
                             (self.availability, SubstepAvailability), (self.predicted_trace, ContactTrace)):
            _exact(value, owner, owner.__name__)
            value.__post_init__()
        if self.availability.requested_kind is not ActionKind.DOWNLINK:
            raise ValueError("contact attempt must request downlink")
        for name in ("evaluated_eps_substeps", "evaluated_thermal_substeps"):
            _natural(getattr(self, name), name)
        if not 1 <= self.evaluated_thermal_substeps <= self.evaluated_eps_substeps <= 8192:
            raise ValueError("invalid numerical work")


def _sum_segment_accounting(segments):
    """One declared contact aggregate: fsum of authoritative segment ledgers."""
    return ActionAccounting(**{field.name:
        (sum(getattr(s.accounting, field.name) for s in segments) if field.name == "numerical_substeps"
         else fsum(getattr(s.accounting, field.name) for s in segments)) for field in fields(ActionAccounting)})


@dataclass(frozen=True, slots=True)
class ContactOutcome:
    contact: ServiceableGroundContact
    requested_order: tuple[AcquisitionDataRecordId, ...]
    bitrate_bps: int
    subdivision_level: int
    services: tuple[RecordService, ...]
    attempts: tuple[ContactAttempt, ...]
    segments: tuple[ContactSegment, ...]
    accounting: ActionAccounting
    denied_record_id: AcquisitionDataRecordId | None
    operational_mode: OperationalMode
    fdir_state: FDIRState
    critical_energy_since_seconds: int | None
    recovered: bool

    def __post_init__(self):
        _exact(self.contact, ServiceableGroundContact, "contact")
        self.contact.__post_init__()
        _exact(self.bitrate_bps, int, "bitrate")
        _integer_quantity(self.bitrate_bps, "bitrate", positive=True)
        policy = IntegrationPolicy(self.subdivision_level)
        _exact(self.requested_order, tuple, "requested order")
        if len(self.requested_order) > MAX_CONTACT_RECORDS or len(set(self.requested_order)) != len(self.requested_order):
            raise ValueError("invalid requested order")
        for record_id in self.requested_order:
            _exact(record_id, AcquisitionDataRecordId, "requested record")
        for name, owner in (("services", RecordService), ("attempts", ContactAttempt), ("segments", ContactSegment)):
            values = getattr(self, name)
            _exact(values, tuple, name)
            if len(values) > MAX_CONTACT_RECORDS + 1:
                raise ValueError("contact evidence exceeds bounded work")
            for value in values:
                _exact(value, owner, name)
                value.__post_init__()
        _exact(self.accounting, ActionAccounting, "contact accounting")
        self.accounting.__post_init__()
        if not self.segments:
            raise ValueError("contact must integrate its entire physical duration")
        if self.accounting != _sum_segment_accounting(self.segments):
            raise ValueError("contact accounting differs from selected segment ledgers")
        boundary = Fraction(0)
        tx_ids = []
        for i, segment in enumerate(self.segments):
            trace = segment.trace
            if trace.start_offset.fraction != boundary:
                raise ValueError("physical segments have a gap or overlap")
            boundary = trace.end_offset.fraction
            if trace.denominator != self.bitrate_bps * policy.substeps:
                raise ValueError("sample time denominator differs from policy")
            if segment.accounting.numerical_substeps != policy.substeps:
                raise ValueError("segment partition differs from policy")
            start = trace.start_offset.fraction * trace.denominator
            increment = (trace.end_offset.fraction - trace.start_offset.fraction) * self.bitrate_bps
            for j, sample in enumerate(trace.samples):
                if sample.offset_numerator_seconds != start + j * increment:
                    raise ValueError("physical sample partition is not exact")
            if segment.record_id is None:
                if i != len(self.segments) - 1:
                    raise ValueError("idle must consume the entire remaining contact")
            else:
                tx_ids.append(segment.record_id)
            if i:
                previous = self.segments[i-1].trace.samples[-1]
                current = trace.samples[0]
                for name in ("battery_energy_wh", "battery_retention", "solar_retention",
                             "cumulative_throughput_wh", "temperatures_k"):
                    if getattr(previous, name) != getattr(current, name):
                        raise ValueError("physical state is discontinuous between segments")
        if boundary != self.contact.end_time_seconds - self.contact.start_time_seconds:
            raise ValueError("physical coverage must equal the contact duration")
        if tuple(tx_ids) != tuple(s.record.record_id for s in self.services) or tuple(tx_ids) != self.requested_order[:len(tx_ids)]:
            raise ValueError("service changed explicit record order")
        if tuple(a.record_id for a in self.attempts) != self.requested_order[:len(self.attempts)]:
            raise ValueError("attempts changed explicit order")
        denied = tuple(a.record_id for a in self.attempts if not a.availability.available)
        if self.denied_record_id is not None:
            _exact(self.denied_record_id, AcquisitionDataRecordId, "denied record")
        if denied != (() if self.denied_record_id is None else (self.denied_record_id,)):
            raise ValueError("denial evidence disagrees")
        if len(self.attempts) != len(self.services) + len(denied):
            raise ValueError("only accepted attempts may service records")
        if denied and (self.attempts[-1].record_id != self.denied_record_id or self.segments[-1].transmitter_on):
            raise ValueError("denial must terminate transmission")
        for service, segment, attempt in zip(self.services, self.segments, self.attempts):
            if not attempt.availability.available or not attempt.predicted_trace.complete:
                raise ValueError("service requires complete authorized prediction")
            if attempt.predicted_trace != segment.trace:
                raise ValueError("authorized and executed refined trajectories differ")
            if (service.start_offset, service.end_offset) != (segment.trace.start_offset, segment.trace.end_offset):
                raise ValueError("data and physical time differ")
            if service.transmitted_bits != (service.end_offset.fraction-service.start_offset.fraction)*self.bitrate_bps:
                raise ValueError("bits/rate must own exact service duration")
            if service.completed and service.completion_time_seconds != self.contact.start_time_seconds + ceil(service.end_offset.fraction):
                raise ValueError("completion timestamp must conservatively ceil exact offset")
            if not service.completed and service.end_offset.fraction != boundary:
                raise ValueError("partial service must exhaust the contact")
        if self.tx_on_seconds.fraction != Fraction(self.transmitted_bits, self.bitrate_bps):
            raise ValueError("contact time/bit conservation failed")
        for value, owner in ((self.operational_mode, OperationalMode), (self.fdir_state, FDIRState), (self.recovered, bool)):
            _exact(value, owner, owner.__name__)
        idle = tuple(s for s in self.segments if not s.transmitter_on)
        essential = any(s.accounting.unmet_load_wh for s in idle)
        unsafe = essential or any(p.operating_node_ids for s in idle for p in s.trace.samples)
        expected_mode = OperationalMode.SAFE if unsafe else (OperationalMode.DOWNLINK if self.segments[-1].transmitter_on else OperationalMode.STANDBY)
        expected_fdir = FDIRState.BACKUP if denied or unsafe else FDIRState.NORMAL
        if self.operational_mode is not expected_mode or self.fdir_state is not expected_fdir:
            raise ValueError("protection regime disagrees with selected contact evidence")
        if (self.critical_energy_since_seconds is not None) != bool(essential):
            raise ValueError("critical boundary disagrees with actual essential deficit")
        if self.recovered and self.fdir_state is not FDIRState.NORMAL:
            raise ValueError("recovery requires a normal outer decision")
        if self.critical_energy_since_seconds is not None:
            _natural(self.critical_energy_since_seconds, "critical boundary")
            if self.critical_energy_since_seconds > self.contact.start_time_seconds:
                raise ValueError("critical boundary is not a fractional crossing")

    @property
    def transmitted_bits(self):
        return sum(s.transmitted_bits for s in self.services)

    @property
    def tx_on_seconds(self):
        return RationalSeconds.from_fraction(sum((s.trace.end_offset.fraction-s.trace.start_offset.fraction
            for s in self.segments if s.transmitter_on), Fraction(0)))

    @property
    def idle_seconds(self):
        return RationalSeconds.from_fraction(Fraction(self.contact.end_time_seconds-self.contact.start_time_seconds)-self.tx_on_seconds.fraction)

    @property
    def evaluated_eps_substeps(self):
        return sum(a.evaluated_eps_substeps for a in self.attempts) + sum(s.accounting.numerical_substeps for s in self.segments if not s.transmitter_on)

    @property
    def evaluated_thermal_substeps(self):
        return sum(a.evaluated_thermal_substeps for a in self.attempts) + sum(s.accounting.numerical_substeps for s in self.segments if not s.transmitter_on)


def validate_contact_plan(context, plan, consumed, policy, integration):
    # Public untrusted input always performs complete historical admission.
    return _validate_contact_plan(context,plan,consumed,policy,integration,None)


def _validate_contact_plan(context, plan, consumed, policy, integration, preparation):
    """Eagerly validate ALL selected records, even those beyond capacity."""
    from .experiment_codec import canonical_copy, canonical_content
    if preparation is None:
        checked_checkpoint(context)
        canonical_copy(context.inputs)
    else:
        preparation.check(context,policy,integration)
        preparation.checkpoint(context)
    for value, owner in ((plan, ContactPlan), (consumed, ConsumedContacts), (integration, IntegrationPolicy)):
        _exact(value, owner, owner.__name__)
    plan, consumed = canonical_copy(plan), canonical_copy(consumed)
    if preparation is None:
        integration=canonical_copy(integration)
        policy=validate_policy(policy,context)
    else:
        policy=preparation.policy
    contact = plan.contact
    if any(c.contact_id == contact.contact_id for c in consumed.contacts):
        raise ValueError("contact identity already consumed")
    if len(consumed.contacts) == MAX_CONSUMED_CONTACTS:
        raise ValueError("consumed contact memory is full")
    if any(c.end_time_seconds > context.simulation_time_seconds for c in consumed.contacts):
        raise ValueError("consumed contact ends after current completed clock")
    if contact.start_time_seconds != context.simulation_time_seconds or contact.end_time_seconds > context.inputs.common_world.horizon_seconds:
        raise ValueError("contact must start now and end within horizon")
    if context.inputs.common_world.event_ids:
        raise ValueError("within-contact world events unsupported")
    if (len(plan.record_ids)+1)*integration.substeps > 4096:
        raise ValueError("contact exceeds bounded physical substeps; no convergence claim")
    if context.spacecraft_state.onboard.fdir_state not in (FDIRState.NORMAL, FDIRState.BACKUP):
        raise ValueError("FDIR regime outside sampled policy")
    if context.spacecraft_state.onboard.operational_mode not in (OperationalMode.SAFE, OperationalMode.STANDBY, OperationalMode.IMAGING, OperationalMode.DOWNLINK):
        raise ValueError("activity regime outside sampled policy")
    network = context.inputs.spacecraft_configuration.thermal.network
    validate_coupled_downlink_inputs(plan.tx_inputs, network)
    _validate_forcing(plan.idle_inputs, network)
    if canonical_content(plan.tx_inputs.baseline_loads) != canonical_content(plan.idle_inputs.loads):
        raise ValueError("TX-off loads must equal the explicit baseline")
    for name in ("sunlit", "incidence_angle_deg", "routing_config", "thermal_inputs", "external_heat_sources", "solar_degradation_forcing"):
        if canonical_content(getattr(plan.tx_inputs, name)) != canonical_content(getattr(plan.idle_inputs, name)):
            raise ValueError("ON/OFF forcing must share the declared constant contact environment")
    communications = context.inputs.spacecraft_configuration.communications
    # Enforce the raw type/integer domain before the legacy owner's float conversion.
    rate = _integer_quantity(communications.nominal_downlink_data_rate_bps.value, "bitrate", positive=True)
    capacity = compute_downlink_capacity(communications, contact)
    bits = _integer_quantity(rate*plan.duration_seconds, "contact capacity", positive=True)
    if capacity.nominal_downlink_data_rate_bps != rate or capacity.nominal_contact_capacity_bits != bits:
        raise ValueError("nominal rate/capacity disagrees with exact raw integer rate")
    records = {r.record_id:r for r in context.spacecraft_state.data_storage.stored_records}
    completed = {d.record.record_id for d in context.ground_data_delivery_state.completed_deliveries}
    if any(d.completing_contact.contact_id == contact.contact_id for d in context.ground_data_delivery_state.completed_deliveries):
        raise ValueError("contact identity already recorded as a completing contact")
    progress = {p.record_id:p.transmitted_equivalent_bits for p in context.ground_data_delivery_state.partial_transfers}
    for record_id in plan.record_ids:
        if record_id in completed:
            raise ValueError("selected record already completed/delivered")
        if record_id not in records:
            raise ValueError("selected record is missing/not onboard")
        record = records[record_id]
        _validate_acquisition_completed_by(record, contact.start_time_seconds, boundary="contact start")
        total = _integer_quantity(record.stored_equivalent_bits, "stored bits", positive=True)
        before = _integer_quantity(progress.get(record_id, 0), "existing partial bits")
        if before >= total:
            raise ValueError("selected progress is not partial")
    return plan, consumed, policy, integration, rate


def _segment_proposal(context, plan, policy, integration, rate, start_bits, duration_bits, *, standby):
    """No clocks/data commits: reuse the exact same Task 04A physical substep."""
    candidate = checked_checkpoint(context).restore(context.inputs)
    forcing = plan.idle_inputs if standby else plan.tx_inputs
    eps_inputs = EPSIntervalInputs(forcing.sunlit, forcing.incidence_angle_deg, forcing.loads) if standby else forcing.eps_inputs
    required = policy.standby_node_ids if standby else policy.downlink_node_ids
    n = integration.substeps
    duration = RationalSeconds.from_fraction(Fraction(duration_bits, rate*n))
    solar = forcing.solar_degradation_forcing
    if solar is not None:
        loss = float(Fraction(solar.retention_loss)*Fraction(duration_bits, rate*plan.duration_seconds*n))
        if solar.retention_loss > 0 and loss == 0:
            raise ValueError("positive contact solar loss underflows on partition")
        solar = SolarDegradationForcingInput(loss)
    samples = [_sample(candidate, start_bits*n, required)]
    parts = []
    evaluated = 0
    unmet = 0.0
    for i in range(n):
        part, eps = _physical_substep(candidate, duration, forcing, eps_inputs, policy, solar, standby=standby)
        evaluated += 1
        if part is None:
            unmet = eps.battery.unmet_load_w
            break
        parts.append(part)
        samples.append(_sample(candidate, start_bits*n+(i+1)*duration_bits, required, eps.battery.unmet_load_w))
    trace = ContactTrace(RationalSeconds.from_fraction(Fraction(start_bits, rate)),
        RationalSeconds.from_fraction(Fraction(start_bits+duration_bits, rate)), rate*n, tuple(samples))
    _validate_physical_samples(tuple(parts), trace.samples, duration)
    return candidate, tuple(parts), trace, unmet, evaluated


def _availability(context, policy, wait, mission):
    start = _violations(context, policy.downlink_node_ids)
    predicted = tuple(dict.fromkeys(n for s in mission[2].samples[1:] for n in s.operating_node_ids))
    standby = tuple(dict.fromkeys(n for s in wait[2].samples for n in s.operating_node_ids))
    essential = _aggregate(wait[1]).unmet_load_wh
    reasons = tuple(reason for evidence, reason in ((start, SampledReason.OPERATING_START),
        (predicted, SampledReason.OPERATING_TRAJECTORY), (standby, SampledReason.STANDBY_THERMAL),
        (mission[3], SampledReason.ACTION_POWER), (essential, SampledReason.ESSENTIAL_POWER)) if evidence)
    return SubstepAvailability(ActionKind.DOWNLINK, reasons, start, predicted, standby, mission[3], essential)


def _apply_services(candidate, contact, services):
    """Write schema-5 custody once, after all private physical segments succeed."""
    storage = candidate.spacecraft_state.data_storage
    delivery = candidate.ground_data_delivery_state
    for service in services:
        record_id = service.record.record_id
        positions = [i for i,p in enumerate(delivery.partial_transfers) if p.record_id == record_id]
        position = positions[0] if positions else None
        if service.completed:
            storage.stored_records = tuple(r for r in storage.stored_records if r.record_id != record_id)
            delivery.partial_transfers = tuple(p for p in delivery.partial_transfers if p.record_id != record_id)
            delivery.completed_deliveries += (CompletedAcquisitionDelivery(service.record, contact),)
        else:
            progress = DownlinkTransferProgress(record_id, float(service.progress_after_bits))
            if position is None:
                delivery.partial_transfers += (progress,)
            else:
                delivery.partial_transfers = delivery.partial_transfers[:position]+(progress,)+delivery.partial_transfers[position+1:]


@dataclass(frozen=True, slots=True)
class ContactExecutionResult:
    outcome: ContactOutcome
    consumed_contacts: ConsumedContacts
    final_checkpoint: object

    def __post_init__(self):
        from .checkpoint import CheckpointState
        for value, owner in ((self.outcome, ContactOutcome), (self.consumed_contacts, ConsumedContacts),
                             (self.final_checkpoint, CheckpointState)):
            _exact(value, owner, owner.__name__)
        self.outcome.__post_init__()
        self.consumed_contacts.__post_init__()
        if not self.consumed_contacts.contacts or self.consumed_contacts.contacts[-1] != self.outcome.contact:
            raise ValueError("result must consume its original contact")
        if self.final_checkpoint.simulation_time_seconds != self.outcome.contact.end_time_seconds:
            raise ValueError("final clock must equal the physical contact end")
        final = self.final_checkpoint.spacecraft
        last = self.outcome.segments[-1].trace.samples[-1]
        if (final.battery_energy_wh != last.battery_energy_wh
                or final.degradation.battery.usable_capacity_retention != last.battery_retention
                or final.degradation.battery.cumulative_energy_throughput_wh != last.cumulative_throughput_wh
                or final.degradation.solar.generation_retention != last.solar_retention
                or tuple((n.node_id,n.temperature_k) for n in final.thermal.node_states) != last.temperatures_k
                or final.operational_mode is not self.outcome.operational_mode
                or final.fdir_state is not self.outcome.fdir_state
                or final.critical_energy_since_seconds != self.outcome.critical_energy_since_seconds):
            raise ValueError("final checkpoint disagrees with actual physical/protection evidence")
        delivery = self.final_checkpoint.ground_data_delivery
        completed = {d.record.record_id:d for d in delivery.completed_deliveries}
        partial = {p.record_id:p for p in delivery.partial_transfers}
        for service in self.outcome.services:
            record_id = service.record.record_id
            if service.completed:
                if record_id not in completed or completed[record_id] != CompletedAcquisitionDelivery(service.record, self.outcome.contact):
                    raise ValueError("completed service disagrees with schema-5 delivery")
            elif record_id not in partial or partial[record_id].transmitted_equivalent_bits != service.progress_after_bits:
                raise ValueError("partial service disagrees with schema-5 progress")


def execute_contact_plan(context, plan, *, consumed_contacts, policy, integration):
    """One outer commit; returned consumed memory must accompany future calls."""
    from .experiment_codec import canonical_copy
    plan, consumed, policy, integration, rate = validate_contact_plan(context, plan, consumed_contacts, policy, integration)
    candidate = checked_checkpoint(context).restore(canonical_copy(context.inputs))
    records = {r.record_id:r for r in candidate.spacecraft_state.data_storage.stored_records}
    progress = {p.record_id:_integer_quantity(p.transmitted_equivalent_bits, "selected partial bits")
        for p in candidate.ground_data_delivery_state.partial_transfers if p.record_id in plan.record_ids}
    capacity = rate*plan.duration_seconds
    cursor = 0
    services, segments, attempts = [], [], []
    denied = None
    for record_id in plan.record_ids:
        if cursor == capacity:
            break
        record = records[record_id]
        before = progress.get(record_id, 0)
        total = int(record.stored_equivalent_bits)
        bits = min(total-before, capacity-cursor)
        wait = _segment_proposal(candidate, plan, policy, integration, rate, cursor, bits, standby=True)
        mission = _segment_proposal(candidate, plan, policy, integration, rate, cursor, bits, standby=False)
        availability = _availability(candidate, policy, wait, mission)
        attempts.append(ContactAttempt(record_id, availability, mission[2], wait[4]+mission[4], len(wait[1])+len(mission[1])))
        if not availability.available:
            denied = record_id
            break
        candidate, parts, trace = mission[:3]
        segments.append(ContactSegment(record_id, trace, _aggregate(parts)))
        complete = before+bits == total
        services.append(RecordService(record, before, bits, before+bits, trace.start_offset, trace.end_offset,
            complete, plan.contact.start_time_seconds+ceil(trace.end_offset.fraction) if complete else None))
        cursor += bits
    if cursor < capacity:
        idle = _segment_proposal(candidate, plan, policy, integration, rate, cursor, capacity-cursor, standby=True)
        candidate, parts, trace = idle[:3]
        segments.append(ContactSegment(None, trace, _aggregate(parts)))
    # Decisions are derived from actual selected samples; rejected predictions
    # never become observed survival failures or ground knowledge.
    idle_segments = [s for s in segments if not s.transmitter_on]
    essential = any(s.accounting.unmet_load_wh for s in idle_segments)
    unsafe = essential or any(p.operating_node_ids for s in idle_segments for p in s.trace.samples)
    old = context.spacecraft_state.onboard
    onboard = candidate.spacecraft_state.onboard
    onboard.critical_energy_since_seconds = ((old.critical_energy_since_seconds if old.critical_energy_since_seconds is not None
        else plan.contact.start_time_seconds) if essential else None)
    onboard.operational_mode = OperationalMode.SAFE if unsafe else (OperationalMode.DOWNLINK if segments[-1].transmitter_on else OperationalMode.STANDBY)
    onboard.fdir_state = FDIRState.BACKUP if denied is not None or unsafe else FDIRState.NORMAL
    _apply_services(candidate, plan.contact, services)
    candidate.simulation_time_seconds = plan.contact.end_time_seconds
    candidate.diagnostics.completed_steps = context.diagnostics.completed_steps+1
    outcome = ContactOutcome(plan.contact, plan.record_ids, rate, integration.subdivision_level,
        tuple(services), tuple(attempts), tuple(segments), _sum_segment_accounting(segments), denied,
        onboard.operational_mode, onboard.fdir_state, onboard.critical_energy_since_seconds,
        old.fdir_state is FDIRState.BACKUP and onboard.fdir_state is FDIRState.NORMAL)
    result = ContactExecutionResult(outcome, ConsumedContacts((*consumed.contacts, plan.contact)), checked_checkpoint(candidate))
    _commit_action(context, candidate)
    return result


__all__ = ["ContactPlan", "ConsumedContacts", "ContactTrace", "ContactSegment", "RecordService",
           "ContactAttempt", "ContactOutcome", "ContactExecutionResult", "execute_contact_plan"]


_CONTACT_KEY=object()
_CONTACT_COUNTS=dict(preparations=0,cuts=0,immutable_admissions_avoided=0)


def contact_preparation_counts():
    return dict(method='YEAR_V3_OPERATION_LOCAL_CONTACT_PREPARATION_V1',**_CONTACT_COUNTS,
        scope='IMPLEMENTATION_CONTROL_ONLY_NOT_PHYSICAL_MODEL_WORK')


class _ContactPreparation:
    """Only immutable admission, owned by one closed synchronous generation.

    No state, plan, forcing, consumed IDs, chosen records, or partial bits are
    cached. An epoch change after a callback invalidates this object. Re-entry
    after exit/restart needs a new full admission. Public validation has no
    capability argument. The capability is neither checkpoint DATA nor global.
    """
    __slots__=('binding','inputs','policy','integration','original_policy','original_integration',
        'generation','epoch','pid','thread','active','pins','cut_context_id')
    def __init__(self,binding,context,policy,integration,key):
        import os,threading
        from .lifecycle_typed_context import TypedContactBinding
        from .lifecycle_typed_backend import NEW_DOMAIN
        from .experiment_codec import canonical_copy
        if key is not _CONTACT_KEY or type(binding)is not TypedContactBinding or binding.context.selection!=NEW_DOMAIN:
            raise ValueError('YEAR-V3 private typed CONTACT factory required')
        binding.check_context(context)
        if any(type(v)is not int or not 0<=v<2**40 for v in _CONTACT_COUNTS.values()):raise ValueError('YEAR-V3 CONTACT implementation control exhausted')
        generation=binding.context.job._validation
        if generation is None or not generation.closed():raise ValueError('YEAR-V3 closed CONTACT generation required')
        # The closed owner has full guards at entry/exit and suspends around
        # external callbacks. Inputs are that exact source-bound owned graph.
        checked_checkpoint(context);canonical_copy(context.inputs)
        self.policy=validate_policy(policy,context);self.integration=canonical_copy(integration)
        self.original_policy=policy;self.original_integration=integration
        self.binding=binding;self.inputs=context.inputs;self.generation=generation
        self.epoch=generation._epoch;self.pid=os.getpid();self.thread=threading.get_ident();self.active=True
        self.cut_context_id=id(context)
        self.pins=(binding,context.inputs,self.policy,self.integration,policy,integration,generation,self.epoch,self.pid,self.thread)
        _CONTACT_COUNTS['preparations']+=1
    def check(self,context,policy,integration):
        import os,threading
        if (type(self)is not _ContactPreparation or self.active is not True or
                any(a is not b for a,b in zip(self.pins[:7],(self.binding,self.inputs,self.policy,self.integration,self.original_policy,self.original_integration,self.generation))) or self.pins[7:]!=(self.epoch,self.pid,self.thread) or
                os.getpid()!=self.pid or threading.get_ident()!=self.thread or id(context)!=self.cut_context_id or context.inputs is not self.inputs or
                policy is not self.original_policy or integration is not self.original_integration or
                self.generation is not self.binding.context.job._validation or
                not self.generation.closed() or self.generation._epoch!=self.epoch):
            raise ValueError('YEAR-V3 stale/foreign CONTACT preparation')
        self.binding.check_context(context)
        if _CONTACT_COUNTS['cuts']>=2**40:raise ValueError('YEAR-V3 CONTACT implementation control exhausted')
        _CONTACT_COUNTS['cuts']+=1;_CONTACT_COUNTS['immutable_admissions_avoided']+=1
    def checkpoint(self,context):
        # Same dynamic schema-5 lossless roundtrip; only the already admitted
        # immutable input re-encoding is removed from the inner cut.
        from .checkpoint import CheckpointState
        from .experiment_codec import canonical_content
        snapshot=CheckpointState.from_context(context)
        reconstructed=CheckpointState.from_dict(snapshot.to_dict())
        if canonical_content(snapshot)!=canonical_content(reconstructed):
            raise ValueError('runtime state is not losslessly representable by schema 5')
        reconstructed.restore(context.inputs)
    def bind_cut(self,context,key):
        if key is not _CONTACT_KEY:raise ValueError('YEAR-V3 private CONTACT cut binder')
        self.binding.check_context(context)
        if not self.generation.closed()or self.generation._epoch!=self.epoch or self.active is not True:raise ValueError('YEAR-V3 stale CONTACT binder')
        self.cut_context_id=id(context) # provenance only; no physical state/result retained
    def close(self):self.active=False;self.pins=();self.cut_context_id=None
    def __copy__(self):raise TypeError('private CONTACT preparation cannot be copied')
    def __deepcopy__(self,memo):raise TypeError('private CONTACT preparation cannot be copied')
    def __reduce_ex__(self,p):raise TypeError('private CONTACT preparation cannot be persisted')


def _prepare_contact(binding,context,policy,integration):
    from .lifecycle_typed_context import TypedContactBinding
    from .lifecycle_typed_backend import NEW_DOMAIN
    if type(binding)is not TypedContactBinding or binding.context.selection!=NEW_DOMAIN:return None
    return _ContactPreparation(binding,context,policy,integration,_CONTACT_KEY)


def _bind_contact_cut(preparation,context):
    if preparation is not None:
        if type(preparation)is not _ContactPreparation:raise TypeError('YEAR-V3 exact CONTACT cut binder')
        preparation.bind_cut(context,_CONTACT_KEY)
