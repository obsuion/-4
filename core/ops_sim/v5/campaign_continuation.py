"""Version-7 causal campaign continuation and explicit knowledge adapter.

Schema 5 owns truth/custody; immutable decision+feedback events own controller
causality. Released sets, prior attitude, consumed contacts and product assessments
are projections, not second mutable owners. Restore replays decisions and physics.
"""

from dataclasses import dataclass
from fractions import Fraction

from .campaign_contract import MSCampaignProgram, MSCampaignMemory, CampaignDecision, typed
from .campaign_controller import (PlanningView, PlanningKnowledge, CampaignBudgetExceeded,
    build_rolling_plan, observe_boundary, execute_selected, image_action, forcing_for)
from .contact_execution import ConsumedContacts, ContactOutcome, _integer_quantity
from .context import SimulationContext
from .continuation import checked_checkpoint, _exact
from .ms_acquisition import validate_ms_acquisition
from .ms_product import assess_ms_product
from .observation_feasibility import ScheduledObservationExecution
from .operational_protection import validate_policy, _validate_forcing


def planning_boundary(inputs, program, memory):
    """Filter unreleased requests before any controller call, including forecasts."""
    now = memory.feedback.received_at_seconds
    until = min(inputs.common_world.horizon_seconds, now + program.policy.lookahead_seconds)
    requests = tuple(r for r in program.requests if r.release_seconds <= now)
    ids = {r.product.request.request_id for r in requests}
    opportunities = tuple(o for o in program.opportunities if o.acquisition.request.request_id in ids
                          and o.opportunity.window_end_seconds > now and o.opportunity.window_start_seconds < until)
    view = PlanningView(inputs, requests, opportunities,
        tuple(c for c in program.contacts if now <= c.start_time_seconds < until),
        tuple(s for s in program.forcing if s.end_seconds > now and s.start_seconds < until),
        program.protection, program.integration, program.policy, program.knowledge, until)
    previous = program.initial_attitude
    acquired, failed, contacts = [], [], []
    for d in memory.decisions:
        a, ack = d.plan.actions[0], d.feedback
        if ack.acquisition is not None:
            acquired.append(ack.acquisition.plan.request.request_id)
            item = next(o for o in program.opportunities if o.opportunity.opportunity_id.value == a.identity)
            previous = ScheduledObservationExecution(item.candidate.maneuver_candidate, a.start_seconds)
        elif a.kind == "imaging":
            failed.append(a.identity)
        if ack.contact is not None:
            contacts.append(ack.contact)
    knowledge = PlanningKnowledge(memory.feedback, tuple(d.feedback for d in memory.decisions),
        previous, ConsumedContacts(tuple(contacts)), tuple(acquired), tuple(failed))
    return view, knowledge


def _origin(inputs, program):
    from .experiment_codec import canonical_content
    c = program.initial_checkpoint.restore(inputs)
    checked_checkpoint(c)
    now, horizon = c.simulation_time_seconds, inputs.common_world.horizon_seconds
    if (c.spacecraft_state.data_storage.stored_records or c.ground_data_delivery_state.partial_transfers
            or c.ground_data_delivery_state.completed_deliveries):
        raise ValueError("campaign origin requires empty custody and no inherited products")
    if inputs.common_world.event_ids:
        raise ValueError("campaign world events unsupported; supply explicit forcing intervals")
    if not now < horizon or program.initial_attitude.at_seconds > now:
        raise ValueError("campaign requires future horizon and nonfuture initial attitude")
    if program.forcing[0].start_seconds != now or program.forcing[-1].end_seconds != horizon:
        raise ValueError("forcing must cover the entire common campaign horizon")
    nodes = {n.node_id for n in inputs.spacecraft_configuration.thermal.network.nodes}
    if nodes != set(program.knowledge.observed_temperature_node_ids) | {n.node_id for n in program.knowledge.estimated_temperatures}:
        raise ValueError("knowledge requires a declared observation or estimate for every thermal node")
    validate_policy(program.protection, c)
    for f in program.forcing:
        _validate_forcing(f.standby, inputs.spacecraft_configuration.thermal.network)
    rate = _integer_quantity(inputs.spacecraft_configuration.communications.nominal_downlink_data_rate_bps.value,
                             "campaign bitrate", positive=True)
    for contact in program.contacts:
        if contact.start_time_seconds < now or contact.end_time_seconds > horizon:
            raise ValueError("contact outside campaign horizon")
        duration = contact.end_time_seconds-contact.start_time_seconds
        if duration > program.policy.lookahead_seconds:
            raise ValueError("lookahead must admit every full contact duration")
        _integer_quantity(rate*duration, "contact capacity", positive=True)
        if not any(f.start_seconds <= contact.start_time_seconds < contact.end_time_seconds <= f.end_seconds for f in program.forcing):
            raise ValueError("atomic contact crosses forcing boundary")
    requests = {r.product.request.request_id: r for r in program.requests}
    for r in program.requests:
        if r.release_seconds >= horizon:
            raise ValueError("request release must occur within campaign horizon")
    # Validate every association/configuration before control; this never exposes
    # future request contents to the controller or evaluates future execution.
    from .campaign_contract import PlannedAction
    whole = PlanningView(inputs, program.requests, program.opportunities, program.contacts, program.forcing,
        program.protection, program.integration, program.policy, program.knowledge, horizon)
    for item in program.opportunities:
        o, plan = item.opportunity, item.acquisition
        if plan.request.request_id not in requests:
            raise ValueError("opportunity has unknown request")
        r = requests[plan.request.request_id]
        p = r.product
        if (canonical_content(plan.request) != canonical_content(p.request)
                or canonical_content(plan.sizing.footprint) != canonical_content(p.footprint)
                or plan.capture_group != p.capture_group
                or not set(p.required_channels) <= set(plan.sizing.captured_channels)
                or plan.sizing.spacing_x_m > p.maximum_spacing_x_m
                or plan.sizing.spacing_y_m > p.maximum_spacing_y_m):
            raise ValueError("campaign acquisition cannot satisfy its declared product")
        if o.imaging_duration_seconds > program.policy.lookahead_seconds:
            raise ValueError("lookahead must admit a full exposure")
        if o.window_start_seconds < now or o.window_end_seconds > horizon:
            raise ValueError("opportunity outside campaign horizon")
        start = max(o.window_start_seconds, p.acquisition_start_seconds, r.release_seconds)
        end = start + o.imaging_duration_seconds
        if end > min(o.window_end_seconds, p.acquisition_end_seconds):
            raise ValueError("opportunity and product/release windows do not intersect")
        if item.candidate.maneuver_candidate.common_frame_boresight.frame_id != program.initial_attitude.common_frame_boresight.frame_id:
            raise ValueError("campaign requires one declared common boresight frame")
        # Use any constant segment for configuration checking only. Opportunities
        # crossing forcing boundaries are screened at the selected physical time.
        f = program.forcing[0]
        proxy = PlanningView(inputs, whole.requests, whole.opportunities, whole.contacts,
            (type(f)(start, end, f.standby, f.transmitter),), whole.protection, whole.integration,
            whole.policy, whole.knowledge_mode, horizon)
        action, _ = image_action(proxy, PlannedAction("imaging", o.opportunity_id.value, start, end, (), "configuration-validation"))
        validate_ms_acquisition(action.request.action, inputs.spacecraft_configuration.payload.optical_acquisition, plan)
    memory = MSCampaignMemory(observe_boundary(c, program.knowledge), ())
    return c, memory


def _step(c, program, memory):
    if c.simulation_time_seconds == c.inputs.common_world.horizon_seconds:
        raise ValueError("campaign horizon already completed")
    if len(memory.decisions) >= program.policy.max_decisions:
        raise CampaignBudgetExceeded("decision budget exhausted; campaign incomplete")
    view, knowledge = planning_boundary(c.inputs, program, memory)
    plan = build_rolling_plan(view, knowledge)
    outcome, acquired, _, _ = execute_selected(c, view, plan.actions[0],
        knowledge.previous_execution, knowledge.consumed_contacts)
    ack = observe_boundary(c, program.knowledge, outcome=outcome, acquisition=acquired)
    return MSCampaignMemory(memory.initial_feedback, (*memory.decisions, CampaignDecision(plan, outcome, ack)))


def validate_campaign(context, program, memory):
    from .experiment_codec import canonical_copy, canonical_content
    _exact(context, SimulationContext, "context")
    typed(program, MSCampaignProgram)
    typed(memory, MSCampaignMemory)
    program, memory = canonical_copy((program, memory))
    if len(memory.decisions) > program.policy.max_decisions:
        raise ValueError("campaign history exceeds decision bound")
    actual = checked_checkpoint(context)
    replay, expected = _origin(context.inputs, program)
    for _ in memory.decisions:
        expected = _step(replay, program, expected)
    if canonical_content(memory) != canonical_content(expected):
        raise ValueError("campaign knowledge/decision history disagrees with causal replay")
    if canonical_content(actual) != canonical_content(checked_checkpoint(replay)):
        raise ValueError("campaign physical checkpoint disagrees with causal replay")


@dataclass(frozen=True, slots=True)
class MSCampaignState:
    context: SimulationContext
    program: MSCampaignProgram
    memory: MSCampaignMemory

    def __post_init__(self):
        validate_campaign(self.context, self.program, self.memory)


def start_campaign(inputs, program):
    from .experiment_codec import canonical_copy
    typed(program, MSCampaignProgram)
    inputs, program = canonical_copy((inputs, program))
    c, memory = _origin(inputs, program)
    return MSCampaignState(c, program, memory)


def advance_campaign(state):
    """Atomic completed action, including full standby after an actual denial."""
    from .experiment_codec import canonical_copy
    _exact(state, MSCampaignState, "campaign state")
    state.__post_init__()
    program, memory = canonical_copy((state.program, state.memory))
    c = checked_checkpoint(state.context).restore(canonical_copy(state.context.inputs))
    memory = _step(c, program, memory)
    return MSCampaignState(c, program, memory)


def campaign_summary(state):
    """Machine-readable projections; the scoring ledger never enters planning."""
    from .experiment_bundle import experiment_input_digest
    from .experiment_codec import canonical_content
    acquisitions = tuple(d.feedback.acquisition for d in state.memory.decisions if d.feedback.acquisition is not None)
    contacts = tuple(d.outcome for d in state.memory.decisions if type(d.outcome) is ContactOutcome)
    c, p = state.context, state.program
    now = c.simulation_time_seconds
    partial = {v.record_id: int(v.transmitted_equivalent_bits) for v in c.ground_data_delivery_state.partial_transfers}
    delivered = {v.record.record_id for v in c.ground_data_delivery_state.completed_deliveries}
    outcomes = []
    for request in sorted(p.requests, key=lambda r: r.product.request.request_id.value):
        product = request.product
        acq = tuple(a for a in acquisitions if a.plan.request.request_id == product.request.request_id)
        assessment = assess_ms_product(product, acq, c.ground_data_delivery_state, contacts, now)
        completion = next((Fraction(o.contact.start_time_seconds)+s.end_offset.fraction
            for o in contacts for s in o.services if s.completed and any(a.record.record_id == s.record.record_id for a in acq)), None)
        acquired = bool(acq)
        fully_delivered = acquired and all(a.record.record_id in delivered for a in acq)
        status = ("unreleased" if request.release_seconds > now else "delivered-on-time" if assessment.credited_products
            else "delivered-late" if fully_delivered else "partial-expired" if partial and any(a.record.record_id in partial for a in acq) and now >= product.delivery_deadline_seconds
            else "partial" if any(a.record.record_id in partial for a in acq)
            else "acquired-expired" if acquired and now >= product.delivery_deadline_seconds
            else "acquired" if acquired else "expired" if now >= product.delivery_deadline_seconds else "pending")
        outcomes.append({"request_id": product.request.request_id.value, "status": status,
            "release_seconds": request.release_seconds, "deadline_seconds": product.delivery_deadline_seconds,
            "acquired": acquired, "delivered": fully_delivered, "credited_products": assessment.credited_products,
            "exact_completion_seconds": None if completion is None else {"numerator": completion.numerator, "denominator": completion.denominator},
            "deadline_met": None if completion is None else completion <= product.delivery_deadline_seconds,
            "acquisitions": [{"record_id": a.record.record_id.value, "opportunity_id": a.record.observation_opportunity_id.value,
                "start_seconds": a.record.scheduled_start_seconds, "bits": a.plan.sizing.stored_bits,
                "partial_bits": partial.get(a.record.record_id, 0)} for a in acq], "assessment": canonical_content(assessment)})
    trace = [{"decision": i, "sampled_at_seconds": d.plan.sampled_at_seconds,
        "received_at_seconds": d.plan.received_at_seconds, "plan": canonical_content(d.plan),
        "selected_action": {"kind": d.plan.actions[0].kind, "identity": d.plan.actions[0].identity,
            "start_seconds": d.plan.actions[0].start_seconds, "end_seconds": d.plan.actions[0].end_seconds,
            "reason": d.plan.actions[0].reason},
        "rejections": d.plan.rejected, "actual_kind": d.feedback.actual_kind,
        "feedback_sampled_at_seconds": d.feedback.sampled_at_seconds,
        "feedback_received_at_seconds": d.feedback.received_at_seconds, "feedback_reasons": d.feedback.reasons}
        for i, d in enumerate(state.memory.decisions)]
    return {"input_digest": experiment_input_digest(c.inputs, p),
        "status": "completed-horizon" if now == c.inputs.common_world.horizon_seconds else "incomplete",
        "checkpoint": checked_checkpoint(c).to_dict(), "memory": canonical_content(state.memory),
        "metrics": {"clock_seconds": now, "decisions": len(trace), "acquired_products": sum(x['acquired'] for x in outcomes),
            "fully_delivered_products": sum(x['delivered'] for x in outcomes),
            "on_time_ms_products": sum(x['credited_products'] for x in outcomes)},
        "decisions": trace, "requests": outcomes}
