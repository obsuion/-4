"""B55 explicit service-aware contact adapter over immutable custody owners.

The lifecycle caller offers at most one-second service chunks. Each chunk has
the named L2 partition. A private TX prediction grants bits only when EVERY
cut has complete receiving TX power and NORMAL boot-complete service. Failed
predictions retain paid allocation work; selected idle advances real passive
physics and preserves preceding partial custody. No monkeypatch is used.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from fractions import Fraction as Q
from math import ceil
from .contact_execution import (validate_contact_plan, ContactTrace, ContactAttempt,
    ContactSegment, RecordService, ContactOutcome, ContactExecutionResult,
    ConsumedContacts, _availability, _apply_services, _sum_segment_accounting,
    _integer_quantity)
from .construction_contact import (ConstructionContactEvaluation,
    ConstructionContactResult)
from .construction_service import ConstructionServicePolicy, service_physical_substep
from .continuation import checked_checkpoint
from .eps_capability import compute_eps_capability
from .eps_system import EPSIntervalInputs
from .degradation import SolarDegradationForcingInput
from .integration_time import RationalSeconds
from .lifecycle_service import select_service_mode, commit_service_step
from .substepped_execution import _sample, _aggregate, _commit_action, _validate_physical_samples, _violations
from .state import OperationalMode, FDIRState
from .data_delivery import CompletedAcquisitionDelivery


class ServiceContactDomainRefusal(ValueError):
    def __init__(self, reason, diagnostic):
        super().__init__(reason); self.diagnostic = diagnostic


@dataclass(frozen=True, slots=True)
class ServiceContactOutcome:
    """B55 actual functional service, distinct from legacy EPS unmet scope."""
    contact: object
    requested_order: tuple
    bitrate_bps: int
    subdivision_level: int
    services: tuple
    attempts: tuple
    segments: tuple
    accounting: object
    denied_record_id: object
    operational_mode: OperationalMode
    fdir_state: FDIRState
    critical_energy_since_seconds: int | None
    recovered: bool
    service_diagnostics: tuple
    method: str = 'B55_SELECTED_CONTACT_SERVICE_OUTCOME_V1'

    def legacy_physical_projection(self):
        """Validation-only legacy scopes; never a state/receipt authority."""
        idle = tuple(segment for segment in self.segments if not segment.transmitter_on)
        eps_unmet = any(segment.accounting.unmet_load_wh for segment in idle)
        unsafe = eps_unmet or any(sample.operating_node_ids for segment in idle for sample in segment.trace.samples)
        mode = OperationalMode.SAFE if unsafe else (OperationalMode.DOWNLINK
            if self.segments[-1].transmitter_on else OperationalMode.STANDBY)
        fdir = FDIRState.BACKUP if self.denied_record_id is not None or unsafe else FDIRState.NORMAL
        return ContactOutcome(self.contact, self.requested_order, self.bitrate_bps,
            self.subdivision_level, self.services, self.attempts, self.segments,
            self.accounting, self.denied_record_id, mode, fdir,
            self.critical_energy_since_seconds if eps_unmet else None,
            self.recovered and fdir is FDIRState.NORMAL)

    def __post_init__(self):
        from .construction_service import ConstructionServiceDiagnostic
        from .battery_port_construction import PortServiceDiagnostic
        if type(self.method) is not str or self.method != 'B55_SELECTED_CONTACT_SERVICE_OUTCOME_V1':
            raise ValueError('explicit selected contact service version required')
        # All pre-existing record order, exact bit/rate, segment continuity,
        # samples, physical accounting and authorization rules are retained.
        self.legacy_physical_projection().__post_init__()
        if (type(self.service_diagnostics) is not tuple or
                len(self.service_diagnostics) != self.accounting.numerical_substeps or
                not 1 <= len(self.service_diagnostics) <= 256 or
                any(type(item) not in (ConstructionServiceDiagnostic,PortServiceDiagnostic) for item in self.service_diagnostics)):
            raise ValueError('complete selected per-cut contact service diagnostics required')
        clock = Q(self.contact.start_time_seconds)
        for diagnostic in self.service_diagnostics:
            if diagnostic.start_seconds != clock or diagnostic.end_seconds <= clock:
                raise ValueError('selected contact service support gap/overlap')
            clock = diagnostic.end_seconds
        if clock != self.contact.end_time_seconds:
            raise ValueError('selected contact service support differs from contact')
        essential = any(item.essential_unserved_w > 0 for item in self.service_diagnostics)
        idle = tuple(segment for segment in self.segments if not segment.transmitter_on)
        thermal_unsafe = any(sample.operating_node_ids for segment in idle for sample in segment.trace.samples)
        degraded = self.service_diagnostics[-1].service_mode != 'NORMAL'
        unsafe = essential or degraded or thermal_unsafe
        expected_mode = OperationalMode.SAFE if unsafe else (OperationalMode.DOWNLINK
            if self.segments[-1].transmitter_on else OperationalMode.STANDBY)
        expected_fdir = FDIRState.BACKUP if self.denied_record_id is not None or unsafe else FDIRState.NORMAL
        if self.operational_mode is not expected_mode or self.fdir_state is not expected_fdir:
            raise ValueError('selected functional service disagrees with actual onboard regime')
        if (self.critical_energy_since_seconds is not None) != essential:
            raise ValueError('actual essential-service marker disagrees with selected cuts')
        if self.critical_energy_since_seconds is not None and (
                type(self.critical_energy_since_seconds) is not int or
                not 0 <= self.critical_energy_since_seconds <= self.contact.start_time_seconds):
            raise ValueError('sampled essential marker requires a valid prior boundary')
        if type(self.recovered) is not bool or self.recovered and expected_fdir is not FDIRState.NORMAL:
            raise ValueError('functional contact recovery requires NORMAL actual service')

    @property
    def transmitted_bits(self): return sum(service.transmitted_bits for service in self.services)
    @property
    def tx_on_seconds(self):
        return RationalSeconds.from_fraction(sum((segment.trace.end_offset.fraction-segment.trace.start_offset.fraction
            for segment in self.segments if segment.transmitter_on), Q()))
    @property
    def idle_seconds(self):
        return RationalSeconds.from_fraction(sum((segment.trace.end_offset.fraction-segment.trace.start_offset.fraction
            for segment in self.segments if not segment.transmitter_on), Q()))
    @property
    def evaluated_eps_substeps(self):
        return sum(attempt.evaluated_eps_substeps for attempt in self.attempts)+sum(
            segment.accounting.numerical_substeps for segment in self.segments if not segment.transmitter_on)


@dataclass(frozen=True, slots=True)
class ServiceContactExecutionResult:
    outcome: ServiceContactOutcome
    consumed_contacts: ConsumedContacts
    final_checkpoint: object

    def __post_init__(self):
        from .checkpoint import CheckpointState
        if (type(self.outcome) is not ServiceContactOutcome or
                type(self.consumed_contacts) is not ConsumedContacts or
                type(self.final_checkpoint) is not CheckpointState):
            raise TypeError('exact B55 selected contact result families required')
        self.outcome.__post_init__(); self.consumed_contacts.__post_init__()
        if (not self.consumed_contacts.contacts or self.consumed_contacts.contacts[-1] != self.outcome.contact or
                self.final_checkpoint.simulation_time_seconds != self.outcome.contact.end_time_seconds):
            raise ValueError('selected contact result identity/clock mismatch')
        final = self.final_checkpoint.spacecraft; last = self.outcome.segments[-1].trace.samples[-1]
        if (final.battery_energy_wh != last.battery_energy_wh or
                final.degradation.battery.usable_capacity_retention != last.battery_retention or
                final.degradation.battery.cumulative_energy_throughput_wh != last.cumulative_throughput_wh or
                final.degradation.solar.generation_retention != last.solar_retention or
                tuple((node.node_id, node.temperature_k) for node in final.thermal.node_states) != last.temperatures_k or
                final.operational_mode is not self.outcome.operational_mode or
                final.fdir_state is not self.outcome.fdir_state or
                final.critical_energy_since_seconds != self.outcome.critical_energy_since_seconds):
            raise ValueError('selected physical/service checkpoint disagrees with actual trace')
        completed = {item.record.record_id: item for item in self.final_checkpoint.ground_data_delivery.completed_deliveries}
        partial = {item.record_id: item for item in self.final_checkpoint.ground_data_delivery.partial_transfers}
        for service in self.outcome.services:
            key = service.record.record_id
            if service.completed:
                if completed.get(key) != CompletedAcquisitionDelivery(service.record, self.outcome.contact):
                    raise ValueError('selected completed service differs from schema-5 custody')
            elif key not in partial or partial[key].transmitted_equivalent_bits != service.progress_after_bits:
                raise ValueError('selected partial service differs from schema-5 custody')


@dataclass(frozen=True, slots=True)
class ServiceContactResult:
    contact_result: ConstructionContactResult
    service_state: object
    service_work: object
    last_service_diagnostic: object
    battery_port_state: object | None = None
    environment_ageing_state: object | None = None
    @property
    def outcome(self): return self.contact_result.outcome
    @property
    def consumed_contacts(self): return self.contact_result.consumed_contacts
    @property
    def evaluations(self): return self.contact_result.evaluations


def execute_service_contact_plan(context, plan, *, consumed_contacts, policy,
        integration, compilation, work, limits, service_policy, service_state,
        service_work, allocation_work,battery_port_policy=None,battery_port_state=None,battery_port_work=None,
        environment_ageing_policy=None,environment_ageing_state=None,environment_ageing_work=None,
        backend_service=None,_contact_preparation=None):
    if backend_service is not None:
        from .lifecycle_native_state import BackendServiceBinding
        from .lifecycle_typed_context import TypedContactBinding
        if type(backend_service) not in (BackendServiceBinding,TypedContactBinding):
            raise TypeError('B63 exact private contact backend binding')
        backend_service.check_context(context)
    if _contact_preparation is None:
        plan, consumed, policy, integration, rate = validate_contact_plan(
            context, plan, consumed_contacts, policy, integration)
    else:
        from .contact_execution import _ContactPreparation,_validate_contact_plan
        if type(_contact_preparation)is not _ContactPreparation or _contact_preparation.binding is not backend_service:
            raise ValueError('YEAR-V3 exact owned CONTACT preparation required')
        plan,consumed,policy,integration,rate=_validate_contact_plan(
            context,plan,consumed_contacts,policy,integration,_contact_preparation)
    if plan.duration_seconds > 1:
        raise ValueError('B55 contact service chunk must not exceed one second')
    candidate = deepcopy(context, {id(context.inputs): context.inputs})
    records = {r.record_id: r for r in candidate.spacecraft_state.data_storage.stored_records}
    progress = {p.record_id: _integer_quantity(p.transmitted_equivalent_bits, 'selected partial bits')
        for p in candidate.ground_data_delivery_state.partial_transfers if p.record_id in plan.record_ids}
    capacity = rate*plan.duration_seconds; cursor = 0
    services = []; segments = []; attempts = []; evaluations = []; denied = None
    selected_port=battery_port_state;selected_environment=environment_ageing_state
    selected_state = service_state; selected_work = service_work; last_diagnostic = None

    def proposal(origin, initial_state, initial_work, start_bits, duration_bits, standby):
        local_port=selected_port;local_environment=selected_environment
        private = deepcopy(origin, {id(origin.inputs): origin.inputs})
        local_state, local_work = initial_state, initial_work
        forcing = plan.idle_inputs if standby else plan.tx_inputs
        eps = (EPSIntervalInputs(forcing.sunlit, forcing.incidence_angle_deg, forcing.loads)
               if standby else forcing.eps_inputs)
        if not standby and eps.load_breakdown.communications_w <= 0:
            raise ValueError('B55_POSITIVE_AUTHORED_HIGH_RATE_TX_DEMAND_REQUIRED')
        required = policy.standby_node_ids if standby else policy.downlink_node_ids
        n = integration.substeps
        duration = RationalSeconds.from_fraction(Q(duration_bits, rate*n))
        solar = forcing.solar_degradation_forcing
        if solar is not None:
            loss = float(Q(solar.retention_loss)*Q(duration_bits, rate*plan.duration_seconds*n))
            if solar.retention_loss > 0 and loss == 0:
                raise ValueError('positive contact solar loss underflows')
            solar = SolarDegradationForcingInput(loss)
        samples = [_sample(private, start_bits*n, required)]; parts = []; deficit = 0.; diagnostic = None
        for i in range(n):
            left = Q(plan.contact.start_time_seconds)+Q(start_bits, rate)+i*duration.fraction
            right = left+duration.fraction
            capability = compute_eps_capability(private.inputs.spacecraft_configuration.eps,
                                                private.spacecraft_state.degradation)
            decision = select_service_mode(service_policy, local_state, clock_seconds=left,
                energy_wh=private.spacecraft_state.battery.energy_wh,
                usable_capacity_wh=capability.battery_usable_capacity_wh, stationary=True)
            if not decision.supported:
                raise ValueError('stationary contact left admitted recovery domain')
            environment_binding=None;next_environment=None
            if environment_ageing_policy is not None:
                from .environment_ageing import guard,propose,retention
                from .environment_thermal import effective_network
                network=private.inputs.spacecraft_configuration.thermal.network
                guard(environment_ageing_policy,local_environment,network,left)
                if private.spacecraft_state.degradation.solar.generation_retention!=retention(environment_ageing_policy,local_environment):raise ValueError('B61 contact PV provenance')
                if solar is not None:raise ValueError('B61 contact cannot double legacy loss')
                next_environment=propose(environment_ageing_policy,local_environment,network,left,right,forcing.sunlit,forcing.incidence_angle_deg,environment_ageing_work)
                effective = (effective_network(environment_ageing_policy,local_environment,network)
                    if backend_service is None else
                    backend_service.effective_environment(environment_ageing_policy,local_environment,network))
                environment_binding=(effective,environment_ageing_policy,local_environment)
                environment_ageing_work.effective_networks+=1
            service = service_physical_substep if backend_service is None else backend_service.call
            part, carrier = service(private, duration, forcing, eps, policy, solar,
                compilation=compilation, service_policy=ConstructionServicePolicy(),
                service_mode=decision.state.mode, service_work=allocation_work,
                work=work, limits=limits, start_seconds=left, end_seconds=right,
                battery_port_policy=battery_port_policy,battery_port_state=local_port,battery_port_work=battery_port_work,environment_binding=environment_binding)
            if environment_ageing_policy is not None:
                from .environment_lifecycle import complete_cut
                part=complete_cut(private,environment_ageing_policy,local_environment,next_environment,part)
                local_environment=next_environment
            if battery_port_policy is not None:local_port=part.port_state_after
            diagnostic = part.service
            tx = (not standby and decision.state.mode == 'NORMAL' and
                  diagnostic.essential_fully_served and diagnostic.full_commanded_service and
                  diagnostic.commanded_loads.communications_w > 0 and
                  diagnostic.served_loads.communications_w == diagnostic.commanded_loads.communications_w)
            if not standby and not tx:
                # A positive flag rejects the entire private TX proposal. It
                # does not fabricate EPS unmet energy or actual partial bits.
                missing_tx = (diagnostic.desired_loads.communications_w-
                              diagnostic.served_loads.communications_w)
                missing_commanded = diagnostic.commanded_load_w-diagnostic.served_load_w
                observed_deficit = max(missing_tx, missing_commanded)
                if observed_deficit <= 0:
                    raise ValueError('B55_UNSUPPORTED_TX_FUNCTION_WITHOUT_OBSERVED_POWER_DEFICIT')
                deficit = max(deficit, observed_deficit)
            names = tuple(diagnostic.desired_loads.__dataclass_fields__)
            desired_q = sum((Q(getattr(diagnostic.desired_loads, name)) for name in names), Q())
            commanded_q = sum((Q(getattr(diagnostic.commanded_loads, name)) for name in names), Q())
            served_q = sum((Q(getattr(diagnostic.served_loads, name)) for name in names), Q())
            unmet_q = sum((Q(getattr(diagnostic.commanded_loads, name))-Q(getattr(diagnostic.served_loads, name))
                for name in ('base_bus_w', 'obc_w')), Q())
            local_state, local_work = commit_service_step(service_policy, decision, local_work,
                duration_seconds=duration.fraction, desired_normal_load_w=desired_q,
                commanded_load_w=commanded_q, served_receiving_load_w=served_q,
                essential_unserved_w=unmet_q,
                essential_fully_served=diagnostic.essential_fully_served, tx_fully_served=tx)
            nodes = tuple(node.node_id for node in private.spacecraft_state.thermal.node_states)
            if _violations(private, nodes, survival=True):
                raise ServiceContactDomainRefusal('B55_SURVIVAL_TEMPERATURE_AT_CONTACT_ENDPOINT',
                    ('PAID_PRIVATE_CONTACT_ENDPOINT_NOT_PUBLISHED', left, right,
                     tuple(evaluations), tuple(parts), part))
            parts.append(part)
            samples.append(_sample(private, start_bits*n+(i+1)*duration_bits, required,
                                   carrier.battery.unmet_load_w))
        trace = ContactTrace(RationalSeconds.from_fraction(Q(start_bits, rate)),
            RationalSeconds.from_fraction(Q(start_bits+duration_bits, rate)), rate*n, tuple(samples))
        _validate_physical_samples(tuple(parts), trace.samples, duration)
        evaluations.append(ConstructionContactEvaluation(start_bits, duration_bits, rate,
            standby, False, tuple(parts), trace, deficit, n))
        return private, tuple(parts), trace, deficit, n, local_state, local_work, diagnostic, local_port,local_environment

    for record_id in plan.record_ids:
        if cursor == capacity: break
        record = records[record_id]; before = progress.get(record_id, 0)
        total = int(record.stored_equivalent_bits); bits = min(total-before, capacity-cursor)
        wait = proposal(candidate, selected_state, selected_work, cursor, bits, True)
        mission = proposal(candidate, selected_state, selected_work, cursor, bits, False)
        availability = _availability(candidate, policy, wait, mission)
        attempts.append(ContactAttempt(record_id, availability, mission[2], wait[4]+mission[4],
                                       len(wait[1])+len(mission[1])))
        if not availability.available:
            denied = record_id; break
        evaluations[-1] = replace(evaluations[-1], selected=True)
        candidate, parts, trace = mission[:3]
        selected_state, selected_work, last_diagnostic, selected_port,selected_environment = mission[5:]
        segments.append(ContactSegment(record_id, trace, _aggregate(parts)))
        complete = before+bits == total
        services.append(RecordService(record, before, bits, before+bits, trace.start_offset,
            trace.end_offset, complete,
            plan.contact.start_time_seconds+ceil(trace.end_offset.fraction) if complete else None))
        cursor += bits
    if cursor < capacity:
        idle = proposal(candidate, selected_state, selected_work, cursor, capacity-cursor, True)
        evaluations[-1] = replace(evaluations[-1], selected=True)
        candidate, parts, trace = idle[:3]
        selected_state, selected_work, last_diagnostic, selected_port,selected_environment = idle[5:]
        segments.append(ContactSegment(None, trace, _aggregate(parts)))
    idle_segments = [s for s in segments if not s.transmitter_on]
    selected_diagnostics = tuple(part.service for evaluation in evaluations if evaluation.selected for part in evaluation.parts)
    essential = any(item.essential_unserved_w > 0 for item in selected_diagnostics)
    unsafe = essential or selected_state.mode != 'NORMAL' or any(p.operating_node_ids for s in idle_segments for p in s.trace.samples)
    old = context.spacecraft_state.onboard; onboard = candidate.spacecraft_state.onboard
    onboard.critical_energy_since_seconds = ((old.critical_energy_since_seconds
        if old.critical_energy_since_seconds is not None else plan.contact.start_time_seconds) if essential else None)
    onboard.operational_mode = OperationalMode.SAFE if unsafe else (OperationalMode.DOWNLINK
        if segments[-1].transmitter_on else OperationalMode.STANDBY)
    onboard.fdir_state = FDIRState.BACKUP if denied is not None or unsafe else FDIRState.NORMAL
    _apply_services(candidate, plan.contact, services)
    candidate.simulation_time_seconds = plan.contact.end_time_seconds
    candidate.diagnostics.completed_steps = context.diagnostics.completed_steps+1
    outcome = ServiceContactOutcome(plan.contact, plan.record_ids, rate, integration.subdivision_level,
        tuple(services), tuple(attempts), tuple(segments), _sum_segment_accounting(segments), denied,
        onboard.operational_mode, onboard.fdir_state, onboard.critical_energy_since_seconds,
        old.fdir_state is FDIRState.BACKUP and onboard.fdir_state is FDIRState.NORMAL,
        selected_diagnostics)
    result = ServiceContactExecutionResult(outcome, ConsumedContacts((*consumed.contacts, plan.contact)),
                                   checked_checkpoint(candidate))
    _commit_action(context, candidate)
    return ServiceContactResult(ConstructionContactResult(result, tuple(evaluations)),
                                selected_state, selected_work, last_diagnostic, selected_port,selected_environment)
