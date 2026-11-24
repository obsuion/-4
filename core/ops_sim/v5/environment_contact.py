"""B61 narrow nonservice contact composition; accepted custody algorithm/APIs.

Same finite TX/idle selection; every proposal owns its history privately.
No copied thermal engine or mutable config.
"""
from dataclasses import dataclass, replace
from fractions import Fraction
from math import ceil
from .contact_execution import (validate_contact_plan, ContactTrace, ContactAttempt,
    ContactSegment, RecordService, ContactOutcome, ContactExecutionResult,
    ConsumedContacts, _availability, _apply_services, _sum_segment_accounting, _integer_quantity)
from .continuation import checked_checkpoint
from .eps_system import EPSIntervalInputs
from .degradation import SolarDegradationForcingInput
from .integration_time import RationalSeconds
from .substepped_execution import _sample, _aggregate, _commit_action, _validate_physical_samples
from .state import OperationalMode, FDIRState
from .environment_thermal import construction_environment_substep as construction_physical_substep, effective_network
from .environment_ageing import guard,propose,retention
from .environment_lifecycle import complete_cut
from .construction_contact import ConstructionContactRefusal,ConstructionContactEvaluation,ConstructionContactResult
from .design_trade_physics import ElectricalLimitError


def _segment_proposal(context, plan, policy, integration, rate, start_bits, duration_bits, *, standby, compilation, evaluations, work, limits,environment_policy,environment_state,environment_work):
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
    parts = [];history=environment_state
    evaluated = 0
    unmet = 0.0
    for i in range(n):
        left=Fraction(plan.contact.start_time_seconds)+Fraction(start_bits,rate)+i*duration.fraction
        right=left+duration.fraction
        network=candidate.inputs.spacecraft_configuration.thermal.network
        guard(environment_policy,history,network,left)
        if solar is not None:raise ValueError('B61 duplicate legacy loss')
        nxt=propose(environment_policy,history,network,left,right,forcing.sunlit,forcing.incidence_angle_deg,environment_work)
        binding=(effective_network(environment_policy,history,network),environment_policy,history)
        environment_work.effective_networks+=1
        try:
            part, eps = construction_physical_substep(candidate, duration, forcing, eps_inputs, policy, solar, standby=standby, compilation=compilation, work=work, limits=limits,environment_binding=binding)
        except ElectricalLimitError as error:
            # Only complete returned substeps are counted. The failed line
            # owns its known refusal in ConstructionWork, not a served EPS step.
            trace=None
            if evaluated:
                trace=ContactTrace(RationalSeconds.from_fraction(Fraction(start_bits,rate)),
                    RationalSeconds.from_fraction(Fraction(start_bits*n+evaluated*duration_bits,rate*n)),rate*n,tuple(samples))
                _validate_physical_samples(tuple(parts),trace.samples,duration)
            evaluations.append(ConstructionContactEvaluation(start_bits,duration_bits,rate,standby,False,tuple(parts),trace,unmet,evaluated))
            raise ConstructionContactRefusal(str(error),evaluations,offset_bits=Fraction(start_bits*n+evaluated*duration_bits,n),standby=standby) from error
        evaluated += 1
        if part is None:
            unmet = eps.battery.unmet_load_w
            break
        part=complete_cut(candidate,environment_policy,history,nxt,part);history=nxt
        parts.append(part)
        samples.append(_sample(candidate, start_bits*n+(i+1)*duration_bits, required, eps.battery.unmet_load_w))
    trace = ContactTrace(RationalSeconds.from_fraction(Fraction(start_bits, rate)),
        RationalSeconds.from_fraction(Fraction(start_bits+duration_bits, rate)), rate*n, tuple(samples))
    _validate_physical_samples(tuple(parts), trace.samples, duration)
    evaluations.append(ConstructionContactEvaluation(start_bits,duration_bits,rate,standby,False,tuple(parts),trace,unmet,evaluated))
    return candidate, tuple(parts), trace, unmet, evaluated,history

def execute_environment_contact_plan(context, plan, *, consumed_contacts, policy, integration, compilation, work, limits,environment_policy,environment_state,environment_work):
    """One outer commit; returned consumed memory must accompany future calls."""
    from .experiment_codec import canonical_copy
    plan, consumed, policy, integration, rate = validate_contact_plan(context, plan, consumed_contacts, policy, integration)
    candidate = checked_checkpoint(context).restore(context.inputs)
    records = {r.record_id:r for r in candidate.spacecraft_state.data_storage.stored_records}
    progress = {p.record_id:_integer_quantity(p.transmitted_equivalent_bits, "selected partial bits")
        for p in candidate.ground_data_delivery_state.partial_transfers if p.record_id in plan.record_ids}
    capacity = rate*plan.duration_seconds
    cursor = 0;selected_environment=environment_state
    services, segments, attempts = [], [], []
    evaluations=[]
    denied = None
    for record_id in plan.record_ids:
        if cursor == capacity:
            break
        record = records[record_id]
        before = progress.get(record_id, 0)
        total = int(record.stored_equivalent_bits)
        bits = min(total-before, capacity-cursor)
        wait = _segment_proposal(candidate, plan, policy, integration, rate, cursor, bits, standby=True, compilation=compilation, evaluations=evaluations, work=work, limits=limits,environment_policy=environment_policy,environment_state=selected_environment,environment_work=environment_work)
        mission = _segment_proposal(candidate, plan, policy, integration, rate, cursor, bits, standby=False, compilation=compilation, evaluations=evaluations, work=work, limits=limits,environment_policy=environment_policy,environment_state=selected_environment,environment_work=environment_work)
        availability = _availability(candidate, policy, wait, mission)
        attempts.append(ContactAttempt(record_id, availability, mission[2], wait[4]+mission[4], len(wait[1])+len(mission[1])))
        if not availability.available:
            denied = record_id
            break
        evaluations[-1]=replace(evaluations[-1],selected=True)
        candidate, parts, trace = mission[:3];selected_environment=mission[5]
        segments.append(ContactSegment(record_id, trace, _aggregate(parts)))
        complete = before+bits == total
        services.append(RecordService(record, before, bits, before+bits, trace.start_offset, trace.end_offset,
            complete, plan.contact.start_time_seconds+ceil(trace.end_offset.fraction) if complete else None))
        cursor += bits
    if cursor < capacity:
        idle = _segment_proposal(candidate, plan, policy, integration, rate, cursor, capacity-cursor, standby=True, compilation=compilation, evaluations=evaluations, work=work, limits=limits,environment_policy=environment_policy,environment_state=selected_environment,environment_work=environment_work)
        evaluations[-1]=replace(evaluations[-1],selected=True)
        candidate, parts, trace = idle[:3];selected_environment=idle[5]
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
    return ConstructionContactResult(result,tuple(evaluations)),selected_environment
