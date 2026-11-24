"""Separate coupled-design controller and replay-bound completed continuation.

The common policy orders received requests by closing acquisition window, then
the accepted priority/deadline/identity rank. Forecast and actual execution share
the same paid motion/settle/hold/acquisition macro. No version-7 meaning changes.
"""

from dataclasses import asdict, dataclass, replace
from fractions import Fraction
import json
from math import atan2, ceil, fsum, radians

from .campaign_contract import CampaignForcing, PlannedAction
from .campaign_controller import (PlanningKnowledge, PlanningView, image_action,
    observe_boundary, planning_context, request_rank)
from .contact_execution import ContactOutcome, ContactPlan, ConsumedContacts, execute_contact_plan
from .continuation import checked_checkpoint
from .coupled_downlink import CoupledDownlinkInputs
from .design_trade_execution import ProfileOutcome, execute_profile
from .design_trade_physics import SlewProfile
from .experiment_codec import canonical_content, content_digest
from .ms_acquisition import InitialAttitudeEvidence, execute_ms_request
from .ms_product import MSAcquisitionEvidence, assess_ms_product


@dataclass(frozen=True, slots=True)
class TradeEvent:
    phase: str
    start_seconds: int
    end_seconds: int
    start_angle_rad: float
    end_angle_rad: float
    request_id: str | None
    outcome: object
    acquisition: object
    feedback: object
    diagnostics: tuple


@dataclass(frozen=True, slots=True)
class TradeState:
    spec: object
    context: object
    program: object
    design: object
    angle_rad: float
    events: tuple[TradeEvent, ...]
    attempted_request_ids: tuple[str, ...]
    rejections: tuple[tuple[str, str], ...]
    advances: int


def _owners():
    from .design_trade_campaign import TradeSpec, build_program, forcing_at
    return TradeSpec, build_program, forcing_at


def _input_digest(state):
    from .design_trade_campaign import input_digest
    return input_digest(state.spec)


def start_trade(spec):
    owner, builder, _ = _owners()
    if type(spec) is not owner:
        raise TypeError("new coupled study requires its explicit TradeSpec")
    spec.__post_init__()
    inputs, program, design = builder(spec)
    if not design.accepted:
        raise ValueError("operational campaign requires a feasible full design")
    if any(r.release_seconds != 0 for r in program.requests):
        raise ValueError("this bounded controller requires all requests received at origin")
    c = program.initial_checkpoint.restore(inputs)
    direction = program.initial_attitude.common_frame_boresight
    angle = atan2(direction.x, direction.z)
    return TradeState(spec, c, program, design, angle, (), (), (), 0)


def _consumed(events):
    return ConsumedContacts(tuple(e.outcome.contact for e in events if type(e.outcome) is ContactOutcome))


def _view(state, *, forcing=None):
    p = state.program
    return PlanningView(state.context.inputs, p.requests, p.opportunities, p.contacts,
        p.forcing if forcing is None else forcing, p.protection, p.integration, p.policy,
        p.knowledge, state.context.inputs.common_world.horizon_seconds)


def _predicted_context(state):
    feedback = observe_boundary(state.context, state.program.knowledge)
    acknowledgements = tuple(e.feedback for e in state.events)
    knowledge = PlanningKnowledge(feedback, acknowledgements, state.program.initial_attitude,
        _consumed(state.events), tuple(e.acquisition.plan.request.request_id for e in state.events
        if e.acquisition is not None), ())
    return planning_context(_view(state), knowledge)


def _event(state, c, phase, before, after, outcome, *, request=None, acquisition=None, diagnostics=()):
    feedback = observe_boundary(c, state.program.knowledge,
        outcome=None if type(outcome) is ProfileOutcome else outcome, acquisition=acquisition)
    start = outcome.start_seconds if type(outcome) is ProfileOutcome else (
        outcome.contact.start_time_seconds if type(outcome) is ContactOutcome else outcome.actual_trace.start_time_seconds)
    return TradeEvent(phase, start, c.simulation_time_seconds, before, after, request,
        outcome, acquisition, feedback, diagnostics)


def _force(state, time, angle, phase, load_kind="standby"):
    return _owners()[2](state.spec, state.program, state.design, time, angle, phase, load_kind)


def _profile(state, c, angle, duration, phase, trajectory):
    def projected(time, theta, omega, torque, moving):
        # Electrical draw is declared separately from reversible kinetic storage;
        # the profile owner removes/restores body+rotor kinetic energy from heat.
        return _force(state, time, theta, phase if moving else "hold")
    outcome = execute_profile(c, duration_seconds=duration, integration_level=state.spec.level,
        start_angle_rad=angle, trajectory_at=trajectory, forcing_at=projected,
        policy=state.program.protection, max_interval_seconds=state.spec.max_interval_seconds)
    return outcome, _event(state, c, phase, angle, outcome.final_angle_rad, outcome)


def _hold(state, c, angle, until):
    events = []
    # Preserve declared eclipse boundary rather than sampling across its jump.
    boundaries = [t for t in (state.spec.eclipse_end_seconds, until) if c.simulation_time_seconds < t <= until]
    for end in sorted(set(boundaries)):
        outcome, event = _profile(state, c, angle, end-c.simulation_time_seconds, "hold",
            lambda t: (angle, 0., 0.))
        events.append(event)
    return events


def _turn_duration(state, angle, target):
    if angle == target:
        return None, 0
    profile = SlewProfile(abs(target-angle), state.spec.inertia(state.design), state.spec.torque_nm,
        radians(state.spec.rate_deg_s), state.spec.momentum_nms)
    return profile, ceil(profile.duration_s) + state.spec.settle_seconds


def _turn(state, c, angle, target):
    profile, _ = _turn_duration(state, angle, target)
    if profile is None:
        return angle, [], True
    sign = 1. if target > angle else -1.
    def trajectory(t):
        elapsed = float(t)
        if elapsed >= profile.duration_s:
            return target, 0., 0.
        return (angle + sign*profile.angle_at(elapsed), sign*profile.omega_at(elapsed),
            sign*profile.acceleration_at(elapsed)*profile.inertia_kg_m2)
    outcome, event = _profile(state, c, angle, ceil(profile.duration_s), "motion", trajectory)
    events = [event]
    angle = outcome.final_angle_rad
    if not outcome.approved:
        return angle, events, False
    if state.spec.settle_seconds:
        settled, event = _profile(state, c, angle, state.spec.settle_seconds, "settle", lambda t: (angle, 0., 0.))
        events.append(event)
        if not settled.approved:
            return angle, events, False
    return angle, events, True


def _macro(state, c, angle, item):
    o = item.opportunity
    target_direction = item.candidate.maneuver_candidate.common_frame_boresight
    target = atan2(target_direction.x, target_direction.z)
    _, turn_time = _turn_duration(state, angle, target)
    earliest = max(o.window_start_seconds, c.simulation_time_seconds + turn_time)
    if earliest + o.imaging_duration_seconds > o.window_end_seconds:
        return angle, (), False, "motion-and-exposure-do-not-fit-window"
    angle, events, ready = _turn(state, c, angle, target)
    if not ready:
        return angle, tuple(events), False, "forecast-or-actual-motion-protection-denied"
    events.extend(_hold(state, c, angle, max(o.window_start_seconds, c.simulation_time_seconds)))
    now = c.simulation_time_seconds
    end = now + o.imaging_duration_seconds
    if end > o.window_end_seconds:
        return angle, tuple(events), False, "actual-readiness-missed-window"
    wait, diag = _force(state, Fraction(now), angle, "hold", "imaging")
    fallback, fallback_diag = _force(state, Fraction(now), angle, "hold", "standby")
    transmitter = state.program.forcing[0].transmitter
    view = _view(state, forcing=(CampaignForcing(now, end, wait, transmitter),))
    selected = PlannedAction("imaging", o.opportunity_id.value, now, end, (), "coupled-paid-motion-ready")
    timed, acquisition = image_action(view, selected)
    timed = replace(timed, request=replace(timed.request, standby=fallback))
    previous = InitialAttitudeEvidence(now, target_direction, "Observed completed paid motion and settling")
    result = execute_ms_request(c, previous, timed, acquisition=acquisition,
        policy=state.program.protection, integration=state.program.integration)
    evidence = MSAcquisitionEvidence(result.created_record, acquisition) if result.created_record is not None else None
    actual_diag = diag if evidence is not None else fallback_diag
    events.append(_event(state, c, "imaging", angle, angle, result.outcome,
        request=acquisition.request.request_id.value, acquisition=evidence,
        diagnostics=((Fraction(now), Fraction(end), tuple(sorted(actual_diag.items()))),)))
    return angle, tuple(events), evidence is not None, "acquired" if evidence is not None else "forecast-or-actual-acquisition-denied"


def _finish_contact(state, c, angle):
    contact = state.program.contacts[0]
    events = []
    _, turn_time = _turn_duration(state, angle, 0.)
    if c.simulation_time_seconds + turn_time > contact.start_time_seconds:
        events.extend(_hold(state, c, angle, state.spec.horizon))
        return angle, tuple(events), "contact-pointing-ready-too-late"
    angle, turned, ready = _turn(state, c, angle, 0.)
    events.extend(turned)
    if not ready:
        events.extend(_hold(state, c, angle, state.spec.horizon))
        return angle, tuple(events), "contact-pointing-denied"
    events.extend(_hold(state, c, angle, contact.start_time_seconds))
    tx_wait, tx_diag = _force(state, Fraction(contact.start_time_seconds), angle, "hold", "contact")
    idle_wait, idle_diag = _force(state, Fraction(contact.start_time_seconds), angle, "hold", "standby")
    # The accepted contact owner requires identical ON/OFF baseline loads.
    # Attribute the incremental main-wire loss caused by transmitter current to
    # the ON-state demand; both communications and baseline heat use the bus node.
    # This changes neither terminal transmitter power nor received-bit arithmetic.
    transmitter = state.program.forcing[0].transmitter
    terminal_power = transmitter.electrical_power_w
    extra_wire = tx_diag["load_wire_loss_w"] - idle_diag["load_wire_loss_w"]
    if extra_wire < 0:
        raise ValueError("transmitter activation cannot reduce main-wire dissipation")
    transmitter = replace(transmitter, electrical_power_w=replace(terminal_power,
        value=terminal_power.value+extra_wire, provenance=replace(terminal_power.provenance,
            rationale="Declared transmitter terminal demand plus derived incremental main-wire ON-state loss")))
    tx = CoupledDownlinkInputs(transmitter, idle_wait.loads,
        tx_wait.sunlit, tx_wait.incidence_angle_deg, tx_wait.routing_config, tx_wait.thermal_inputs,
        tx_wait.external_heat_sources, tx_wait.solar_degradation_forcing)
    ranks = {r.product.request.request_id: request_rank(r) for r in state.program.requests}
    order = tuple(r.record_id for r in sorted(c.spacecraft_state.data_storage.stored_records,
        key=lambda r: (*ranks[r.imaging_request_id], r.record_id.value)))
    result = execute_contact_plan(c, ContactPlan(contact, order, tx, idle_wait),
        consumed_contacts=_consumed(state.events), policy=state.program.protection,
        integration=state.program.integration)
    diagnostics = tuple((Fraction(contact.start_time_seconds)+s.trace.start_offset.fraction,
        Fraction(contact.start_time_seconds)+s.trace.end_offset.fraction,
        tuple(sorted((tx_diag if s.transmitter_on else idle_diag).items()))) for s in result.outcome.segments)
    events.append(_event(state, c, "contact", angle, angle, result.outcome, diagnostics=diagnostics))
    events.extend(_hold(state, c, angle, state.spec.horizon))
    return angle, tuple(events), "contact-completed"


def _validate_boundary(state):
    if type(state) is not TradeState:
        raise TypeError("coupled trade state required")
    owner, builder, _ = _owners()
    if type(state.spec) is not owner:
        raise TypeError("coupled boundary requires its exact immutable TradeSpec")
    expected_inputs, expected_program, expected_design = builder(state.spec)
    from .design_trade_design import design_record
    if (canonical_content((state.context.inputs, state.program)) != canonical_content((expected_inputs, expected_program))
            or canonical_content(design_record(state.design)) != canonical_content(design_record(expected_design))):
        raise ValueError("coupled immutable spec/design/input/program binding mismatch")
    checked_checkpoint(state.context)
    if type(state.advances) is not int or not 0 <= state.advances <= min(7, state.spec.max_advances):
        raise ValueError("bounded continuation advance count invalid")
    if state.events:
        last = state.events[-1]
        if (state.angle_rad != last.end_angle_rad or state.context.simulation_time_seconds != last.end_seconds
                or canonical_content(observe_boundary(state.context, state.program.knowledge).resources)
                != canonical_content(last.feedback.resources)):
            raise ValueError("physical boundary disagrees with received feedback/attitude")
        previous_time, previous_angle = 0, atan2(state.program.initial_attitude.common_frame_boresight.x,
            state.program.initial_attitude.common_frame_boresight.z)
        for event in state.events:
            if (event.start_seconds != previous_time or event.start_angle_rad != previous_angle
                    or event.end_seconds <= event.start_seconds):
                raise ValueError("physical event history has a time or attitude gap")
            previous_time, previous_angle = event.end_seconds, event.end_angle_rad
    elif (state.context.simulation_time_seconds != 0 or state.advances != 0
            or state.angle_rad != atan2(state.program.initial_attitude.common_frame_boresight.x,
                state.program.initial_attitude.common_frame_boresight.z)
            or canonical_content(checked_checkpoint(state.context)) != canonical_content(state.program.initial_checkpoint)):
        raise ValueError("history-free state must equal the declared physical origin")
    if len(state.attempted_request_ids) != len(set(state.attempted_request_ids)):
        raise ValueError("request attempt identity repeated")


def advance_trade(state):
    _validate_boundary(state)
    if state.context.simulation_time_seconds >= state.spec.horizon:
        raise ValueError("coupled campaign already complete")
    if state.advances >= state.spec.max_advances:
        raise ValueError("declared advance budget exhausted; campaign incomplete")
    c = checked_checkpoint(state.context).restore(state.context.inputs)
    attempted, rejected = list(state.attempted_request_ids), list(state.rejections)
    requests = {r.product.request.request_id: r for r in state.program.requests}
    candidates = sorted(state.program.opportunities,
        key=lambda o: (o.opportunity.window_end_seconds, *request_rank(requests[o.acquisition.request.request_id]),
            o.opportunity.opportunity_id.value))
    for item in candidates:
        identity = item.acquisition.request.request_id.value
        if identity in attempted:
            continue
        attempted.append(identity)
        forecast = _predicted_context(state)
        _, _, approved, reason = _macro(state, forecast, state.angle_rad, item)
        if not approved:
            rejected.append((identity, reason))
            continue
        angle, events, actual, reason = _macro(state, c, state.angle_rad, item)
        if not actual:
            rejected.append((identity, "actual:"+reason))
        return TradeState(state.spec, c, state.program, state.design, angle,
            state.events+events, tuple(attempted), tuple(rejected), state.advances+1)
    angle, events, reason = _finish_contact(state, c, state.angle_rad)
    if reason != "contact-completed":
        rejected.append((state.program.contacts[0].contact_id.value, reason))
    return TradeState(state.spec, c, state.program, state.design, angle,
        state.events+events, tuple(attempted), tuple(rejected), state.advances+1)


def run_trade(spec):
    state = start_trade(spec)
    while state.context.simulation_time_seconds < spec.horizon:
        state = advance_trade(state)
    return state


def _event_wire(event):
    outcome = (canonical_content(asdict(event.outcome)) if type(event.outcome) is ProfileOutcome
        else canonical_content(event.outcome))
    return {"phase": event.phase, "start_seconds": event.start_seconds, "end_seconds": event.end_seconds,
        "start_angle_hex": event.start_angle_rad.hex(), "end_angle_hex": event.end_angle_rad.hex(),
        "request_id": event.request_id, "outcome": outcome, "acquisition": canonical_content(event.acquisition),
        "feedback": canonical_content(event.feedback), "diagnostics": canonical_content(event.diagnostics)}


def _state_wire(state):
    _validate_boundary(state)
    return {"advances": state.advances, "angle_hex": state.angle_rad.hex(),
        "attempted_request_ids": list(state.attempted_request_ids), "rejections": [list(x) for x in state.rejections],
        "events": [_event_wire(e) for e in state.events], "checkpoint": checked_checkpoint(state.context).to_dict()}


def save_trade(state):
    # JSON list normalization is part of this envelope; canonical tuple/list
    # distinctions inside the rebuilt typed immutable input graph remain intact.
    spec_wire = json.loads(json.dumps(state.spec.to_dict(), allow_nan=False))
    payload = {"version": 1, "spec": spec_wire, "input_digest": _input_digest(state),
        "inputs": canonical_content(state.context.inputs), "base_program": canonical_content(state.program),
        "state": _state_wire(state)}
    payload["digest"] = content_digest("task05e-completed-bundle-v1", payload)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def restore_trade(text):
    if type(text) is not str:
        raise TypeError("continuation requires JSON text")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj
    payload = json.loads(text, object_pairs_hook=unique, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    fields = {"version", "spec", "input_digest", "inputs", "base_program", "state", "digest"}
    if type(payload) is not dict or set(payload) != fields or type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("unsupported coupled continuation envelope")
    digest = payload.pop("digest")
    if digest != content_digest("task05e-completed-bundle-v1", payload):
        raise ValueError("coupled continuation digest mismatch")
    spec = _owners()[0].from_dict(payload["spec"])
    state = start_trade(spec)
    if (payload["input_digest"] != _input_digest(state) or payload["inputs"] != canonical_content(state.context.inputs)
            or payload["base_program"] != canonical_content(state.program)):
        raise ValueError("coupled immutable input binding mismatch")
    wire = payload["state"]
    if type(wire) is not dict or set(wire) != {"advances", "angle_hex", "attempted_request_ids", "rejections", "events", "checkpoint"}:
        raise ValueError("invalid coupled runtime envelope")
    if type(wire["advances"]) is not int or not 0 <= wire["advances"] <= min(7, spec.max_advances):
        raise ValueError("invalid bounded replay count")
    for _ in range(wire["advances"]):
        state = advance_trade(state)
    if canonical_content(wire) != canonical_content(_state_wire(state)):
        raise ValueError("coupled history/checkpoint/attitude disagrees with causal replay")
    return state


def summarize_trade(state):
    _validate_boundary(state)
    acquisitions = tuple(e.acquisition for e in state.events if e.acquisition is not None)
    contacts = tuple(e.outcome for e in state.events if type(e.outcome) is ContactOutcome)
    rows = []
    for request in state.program.requests:
        product = request.product
        selected = tuple(a for a in acquisitions if a.plan.request.request_id == product.request.request_id)
        result = assess_ms_product(product, selected, state.context.ground_data_delivery_state,
            contacts, state.context.simulation_time_seconds)
        records = {a.record.record_id for a in selected}
        received = sum(s.transmitted_bits for contact in contacts for s in contact.services if s.record.record_id in records)
        rows.append({"request_id": product.request.request_id.value, "priority": product.request.priority_weight,
            "acquired": bool(selected), "credited_products": result.credited_products, "status": result.status,
            "acquired_bits": sum(a.plan.sizing.stored_bits for a in selected), "received_bits": received,
            "deadline_seconds": product.delivery_deadline_seconds,
            "acquisition_start_seconds": None if not selected else selected[0].record.scheduled_start_seconds,
            "exact_completion_seconds": None if result.completion_time_seconds is None else
                [result.completion_time_seconds.numerator, result.completion_time_seconds.denominator],
            "reasons": result.reasons})
    denominator = sum(Fraction(r["priority"]) for r in rows)
    score = sum(Fraction(r["priority"])*r["credited_products"] for r in rows)/denominator
    samples, diagnostic_energy, phase_seconds = {}, {}, {}
    totals = {key: fsum(getattr(e.outcome.accounting, key) for e in state.events)
        for key in asdict(state.events[0].outcome.accounting)} if state.events else {}
    if totals:
        totals["numerical_substeps"] = sum(e.outcome.accounting.numerical_substeps for e in state.events)
    for event in state.events:
        phase_seconds[event.phase] = phase_seconds.get(event.phase, 0) + event.end_seconds-event.start_seconds
        if type(event.outcome) is ProfileOutcome:
            physical = [(s.time_seconds, s.physical) for s in event.outcome.samples]
            diagnostics = [(i.start_seconds, i.end_seconds, i.diagnostics) for i in event.outcome.intervals]
        elif type(event.outcome) is ContactOutcome:
            physical = [(Fraction(event.start_seconds)+Fraction(s.offset_numerator_seconds, segment.trace.denominator), s)
                for segment in event.outcome.segments for s in segment.trace.samples]
            diagnostics = event.diagnostics
        else:
            trace = event.outcome.actual_trace
            physical = [(Fraction(event.start_seconds)+Fraction(s.offset_numerator_seconds, 2**trace.subdivision_level), s)
                for s in trace.samples]
            diagnostics = event.diagnostics
        for time, sample in physical:
            samples[time] = {"time": [time.numerator, time.denominator], "energy_wh": sample.battery_energy_wh,
                "temperatures_k": {node.value: temperature for node, temperature in sample.temperatures_k},
                "unmet_w": sample.unmet_load_w}
        for start, end, diagnostics_row in diagnostics:
            for key, value in diagnostics_row:
                if key.endswith("_w"):
                    diagnostic_energy.setdefault(key.removesuffix("_w")+"_wh", []).append(value*float(end-start)/3600)
    sample_rows = [samples[t] for t in sorted(samples)]
    return {"status": "completed-horizon" if state.context.simulation_time_seconds == state.spec.horizon else "incomplete",
        "input_digest": _input_digest(state), "spec": state.spec.to_dict(), "requests": rows,
        "weighted_credit": [score.numerator, score.denominator], "phase_seconds": phase_seconds,
        "accounting": totals, "diagnostic_energy_wh": {k: fsum(v) for k,v in diagnostic_energy.items()},
        "final_energy_wh": state.context.spacecraft_state.battery.energy_wh,
        "minimum_energy_wh": min((s["energy_wh"] for s in sample_rows), default=state.context.spacecraft_state.battery.energy_wh),
        "final_angle_rad": state.angle_rad, "physical_samples": sample_rows,
        "rejections": state.rejections, "events": [_event_wire(e) for e in state.events],
        "checkpoint": checked_checkpoint(state.context).to_dict()}


__all__ = ["TradeState", "TradeEvent", "start_trade", "advance_trade", "run_trade",
    "save_trade", "restore_trade", "summarize_trade"]
