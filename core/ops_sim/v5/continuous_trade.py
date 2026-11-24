"""Opt-in periodic mission coordinator; physical evolution remains in V5 owners.

The fixed month horizon is independent of execution stop/checkpoint boundaries.
Only six requests of the current cycle are published. No previous decisions are
replayed during advance, and no delivered custody is discarded. Diagnostics are
returned for streaming, not appended to the live state.
"""

from dataclasses import asdict, dataclass, fields, replace
from fractions import Fraction
from math import atan2, ceil, isfinite, radians

from . import ids
from .campaign_contract import CampaignForcing, PlannedAction, ReleasedMSRequest
from .campaign_controller import PlanningView, image_action, request_rank
from .checkpoint import (SpacecraftStateSnapshot,
                         GroundDataDeliveryStateSnapshot)
from .communications import ServiceableGroundContact
from .contact_execution import ContactPlan, ConsumedContacts, execute_contact_plan
from .continuation import checked_checkpoint
from .coupled_downlink import CoupledDownlinkInputs
from .design_trade_campaign import TradeSpec, build_program, direction, forcing_at
from .design_trade_execution import execute_profile
from .design_trade_physics import SlewProfile
from .experiment_codec import canonical_content, content_digest
from .integration_time import IntegrationPolicy
from .ms_acquisition import InitialAttitudeEvidence, execute_ms_request
from .ms_product import MSAcquisitionEvidence, assess_ms_product


HORIZON = 2592000
PERIOD = 5400
LIGHT = 3600
CONTACT_START = 3420
CONTACT_END = 3500
ZERO_DIGEST = "0" * 64


@dataclass(frozen=True, slots=True)
class ContinuousSpec:
    design_id: str
    workload: str = "regular"
    numerical: str = "coarse"
    initial_fraction: float = .5
    contact_chunk_seconds: int = 20
    version: int = 1
    horizon: int = HORIZON
    variant: str = "FULL"

    def __post_init__(self):
        if type(self.design_id) is not str or self.design_id not in (
                "B2-A2", "B4-A2", "B6-A2", "B8-A2", "B2-A4", "B4-A4"):
            raise ValueError("continuous study requires a feasible accepted allocation")
        for name, values in (("workload", ("regular", "burst")),
                             ("numerical", ("coarse", "fine")),
                             ("variant", ("FULL", "RESOURCE_ONLY"))):
            if type(getattr(self, name)) is not str or getattr(self, name) not in values:
                raise ValueError("unsupported continuous " + name)
        if type(self.version) is not int or self.version != 1:
            raise ValueError("unsupported continuous contract version")
        if type(self.horizon) is not int or self.horizon != HORIZON:
            raise ValueError("pilot stops must not shorten the immutable month horizon")
        if (type(self.initial_fraction) is not float or not isfinite(self.initial_fraction)
                or not 0 < self.initial_fraction <= 1):
            raise ValueError("initial reserve must be a finite built-in fraction")
        if type(self.contact_chunk_seconds) is not int or not 1 <= self.contact_chunk_seconds <= 20:
            raise ValueError("contact chunks must be exact integers in [1,20] seconds")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
            raise ValueError("exact continuous input fields required")
        return cls(**value)

    @property
    def refinement(self):
        return int(self.numerical == "fine")


@dataclass(frozen=True, slots=True)
class ContinuousState:
    spec: ContinuousSpec
    context: object
    template_spec: TradeSpec
    program: object
    design: object
    angle_rad: float
    cycle_index: int
    next_request_index: int
    phase: str
    contact_blocked: bool
    advances: int
    events_emitted: int
    event_count: int
    event_digest: str
    accounting: dict
    last_events: tuple


def start_continuous(spec):
    if type(spec) is not ContinuousSpec:
        raise TypeError("exact continuous spec required")
    spec.__post_init__()
    # This bounded template is used only for accepted hardware/owner contracts.
    # Its six requests are prototypes, never a reinterpreted month-long V7 plan.
    template = TradeSpec(spec.design_id, "relaxed", spec.variant, 1 + spec.refinement,
        sun_angle_deg=70., horizon=PERIOD, initial_fraction=spec.initial_fraction,
        first_window_seconds=120, relaxed_cadence_seconds=600,
        contact_start_seconds=CONTACT_START, contact_end_seconds=CONTACT_END,
        delivery_deadline_seconds=CONTACT_END)
    inputs, program, design = build_program(template)
    context = program.initial_checkpoint.restore(inputs)
    identity = content_digest("task05fa-continuous-spec-v1", spec.to_dict())[:24]
    world = replace(inputs.common_world, world_id=ids.WorldId("task05fa-" + spec.workload),
        scenario_id=ids.ScenarioId("task05fa-" + spec.workload), horizon_seconds=HORIZON)
    environment = replace(inputs.environment_config,
        environment_id=ids.EnvironmentId("task05fa-periodic-sun70-v1"))
    model = replace(inputs.model_manifest, manifest_id=ids.ModelManifestId("task05fa-" + identity),
        world_id=world.world_id, scenario_id=world.scenario_id,
        environment_id=environment.environment_id,
        controller_id=ids.ControllerId("task05fa-received-paid-earliest-window-v1"))
    inputs = replace(inputs, common_world=world, model_manifest=model, environment_config=environment,
        scenario_config=replace(inputs.scenario_config, scenario_id=world.scenario_id))
    context = replace(context, inputs=inputs,
        controller_state=replace(context.controller_state, controller_id=model.controller_id))
    checked_checkpoint(context)
    temperatures = {n.node_id.value: n.temperature_k for n in context.spacecraft_state.thermal.node_states}
    accounting = {"energies": {}, "diagnostic_energy_wh": {}, "phase_seconds": {},
        "numerical_substeps": 0, "forecast_substeps": 0, "acquired": 0, "credited": 0,
        "completed": 0, "transmitted_bits": 0, "acquired_bits": 0,
        "weighted_credit": 0., "forecast_rejections": 0, "actual_denials": 0,
        "minimum_energy_wh": context.spacecraft_state.battery.energy_wh,
        "maximum_energy_wh": context.spacecraft_state.battery.energy_wh,
        "minimum_temperatures_k": dict(temperatures), "maximum_temperatures_k": dict(temperatures)}
    # Keep the V7 prototype internally valid against its original 5400s world;
    # long context inputs and explicit continuous spec are the new authorities.
    return ContinuousState(spec, context, template, program, design, 0., 0, 0,
        "requests", False, 0, 0, 0, ZERO_DIGEST, accounting, ())


def cycle_requests(state, cycle):
    """Deterministic physical occurrences; caller filters publication at origin."""
    if type(cycle) is not int or not 0 <= cycle < HORIZON // PERIOD:
        raise ValueError("cycle outside immutable month")
    start = cycle * PERIOD
    cadence = 600 if state.spec.workload == "regular" else 130
    result = []
    for i, (r, o) in enumerate(zip(state.program.requests, state.program.opportunities)):
        name = f"task05fa-{state.spec.workload}-c{cycle:04d}-r{i}"
        at = start + 120 + cadence * i
        request = replace(r.product.request, request_id=ids.ImagingRequestId(name),
            target_id=ids.GroundTargetId("task05fa-target-" + str(i)))
        footprint = replace(r.product.footprint, region_id=name + "-region")
        product = replace(r.product, request=request, capture_group=name + "-capture",
            footprint=footprint, acquisition_start_seconds=at, acquisition_end_seconds=at + 70,
            delivery_deadline_seconds=start + CONTACT_END)
        opportunity = replace(o.opportunity, opportunity_id=ids.ObservationOpportunityId(name + "-op"),
            request_id=request.request_id, window_start_seconds=at, window_end_seconds=at + 70)
        candidate = replace(o.candidate, maneuver_candidate=replace(o.candidate.maneuver_candidate,
            opportunity=opportunity))
        acquisition = replace(o.acquisition, request=request, capture_group=product.capture_group,
            sizing=replace(o.acquisition.sizing, footprint=footprint))
        result.append((ReleasedMSRequest(product, start), replace(o, candidate=candidate, acquisition=acquisition)))
    return tuple(sorted(result, key=lambda pair: (pair[1].opportunity.window_end_seconds,
        *request_rank(pair[0]), pair[1].opportunity.opportunity_id.value)))


def published_requests(state, now):
    if type(now) is not int or not 0 <= now < HORIZON:
        raise ValueError("publication requires a completed in-horizon clock")
    return cycle_requests(state, now // PERIOD)


def _request_for_record(state, record):
    prefix = "task05fa-" + state.spec.workload + "-c"
    value = record.imaging_request_id.value
    if not value.startswith(prefix):
        raise ValueError("record is not a continuous physical occurrence")
    cycle = int(value[len(prefix):].split("-r")[0])
    return next(pair for pair in cycle_requests(state, cycle)
                if pair[0].product.request.request_id == record.imaging_request_id)


def forcing_breakpoints(start, end):
    return tuple(t for cycle in range(start // PERIOD, end // PERIOD + 1)
        for t in (cycle * PERIOD, cycle * PERIOD + LIGHT) if start < t < end)


def _force(state, time, angle, phase="hold", load="standby"):
    # The accepted 05E physical mapping remains authoritative, including wires.
    sunlit = time % PERIOD < LIGHT
    marker = state.template_spec.eclipse_end_seconds if sunlit else 0
    return forcing_at(state.template_spec, state.program, state.design, marker, angle, phase, load)


@dataclass(frozen=True, slots=True)
class ReceivedPhysicalFeedback:
    sampled_seconds: int
    received_seconds: int
    spacecraft: SpacecraftStateSnapshot
    custody: GroundDataDeliveryStateSnapshot
    angle_rad: float


def observe_continuous(state):
    """Declared ideal zero-latency telemetry and receipt acknowledgements.

    All configured temperatures, physical resource fields and full custody are
    observed. Mission/scoring truth, unpublished requests and diagnostic history
    are not part of this adapter or the forecast API.
    """
    c = state.context
    return ReceivedPhysicalFeedback(c.simulation_time_seconds, c.simulation_time_seconds,
        SpacecraftStateSnapshot.from_state(c.spacecraft_state),
        GroundDataDeliveryStateSnapshot.from_state(c.ground_data_delivery_state), state.angle_rad)


def forecast_context(state, feedback):
    if type(feedback) is not ReceivedPhysicalFeedback:
        raise TypeError("forecast requires received physical feedback")
    if (type(feedback.sampled_seconds) is not int or type(feedback.received_seconds) is not int
            or feedback.sampled_seconds != feedback.received_seconds
            or feedback.received_seconds != state.context.simulation_time_seconds):
        raise ValueError("only explicit zero-latency telemetry is in this contract")
    if type(feedback.angle_rad) is not float or not isfinite(feedback.angle_rad):
        raise ValueError("received attitude must be a finite built-in angle")
    # Fresh mutable objects from observed snapshots, with empty private mission,
    # knowledge/controller histories. Immutable inputs can safely be shared.
    from .context import SimulationContext
    from .controller_state import ControllerState
    from .diagnostics import Diagnostics
    from .knowledge import GroundKnowledgeState
    from .mission import MissionState
    c = SimulationContext(feedback.received_seconds, state.context.inputs,
        feedback.spacecraft.restore(), GroundKnowledgeState(None, ()), feedback.custody.restore(),
        MissionState((), (), (), None, (), ()),
        ControllerState(state.context.inputs.model_manifest.controller_id, None, 0), Diagnostics(0))
    checked_checkpoint(c)
    return c


def _sample_wire(time, sample):
    return {"time": [time.numerator, time.denominator], "energy_wh": sample.battery_energy_wh,
        "temperatures_k": {node.value: temperature for node, temperature in sample.temperatures_k},
        "throughput_wh": sample.cumulative_throughput_wh, "unmet_w": sample.unmet_load_w}


def _profile_event(phase, outcome, start_angle):
    return {"kind": phase, "start": outcome.start_seconds, "end": outcome.end_seconds,
        "start_angle": start_angle, "end_angle": outcome.final_angle_rad,
        "approved": outcome.approved, "reasons": list(outcome.reasons),
        "accounting": asdict(outcome.accounting),
        "samples": [_sample_wire(s.time_seconds, s.physical) for s in outcome.samples],
        "diagnostics": [{"start": [i.start_seconds.numerator, i.start_seconds.denominator],
            "end": [i.end_seconds.numerator, i.end_seconds.denominator], "values": dict(i.diagnostics)}
            for i in outcome.intervals]}


def _profile(state, c, angle, duration, phase, trajectory):
    start = c.simulation_time_seconds
    result = execute_profile(c, duration_seconds=duration,
        integration_level=state.spec.refinement, start_angle_rad=angle,
        trajectory_at=trajectory,
        forcing_at=lambda t, theta, omega, torque, moving: _force(state, t, theta, phase if moving else "hold"),
        policy=state.program.protection,
        max_interval_seconds=60 if phase == "hold" else 5,
        forcing_breakpoints_seconds=forcing_breakpoints(start, start + duration))
    return result, _profile_event(phase, result, angle)


def _hold(state, c, angle, until):
    events = []
    while c.simulation_time_seconds < until:
        end = min(until, c.simulation_time_seconds + 600)
        result, event = _profile(state, c, angle, end - c.simulation_time_seconds, "hold",
            lambda t: (angle, 0., 0.))
        events.append(event)
    return events


def _turn_duration(state, angle, target):
    if angle == target:
        return None, 0
    s = state.template_spec
    profile = SlewProfile(abs(target - angle), s.inertia(state.design), s.torque_nm,
        radians(s.rate_deg_s), s.momentum_nms)
    return profile, ceil(profile.duration_s) + s.settle_seconds


def _turn(state, c, angle, target):
    profile, _ = _turn_duration(state, angle, target)
    if profile is None:
        return angle, [], True
    sign = 1. if target > angle else -1.
    initial_angle = angle
    def trajectory(t):
        elapsed = float(t)
        if elapsed >= profile.duration_s:
            return target, 0., 0.
        return (initial_angle + sign * profile.angle_at(elapsed), sign * profile.omega_at(elapsed),
            sign * profile.acceleration_at(elapsed) * profile.inertia_kg_m2)
    result, event = _profile(state, c, angle, ceil(profile.duration_s), "motion", trajectory)
    events = [event]
    angle = result.final_angle_rad
    if not result.approved:
        return angle, events, False
    result, event = _profile(state, c, angle, state.template_spec.settle_seconds, "settle",
        lambda t: (angle, 0., 0.))
    events.append(event)
    return angle, events, result.approved


def _macro(state, c, angle, pair):
    request, item = pair
    o = item.opportunity
    if request.release_seconds > c.simulation_time_seconds:
        raise ValueError("unpublished request cannot enter paid forecast or execution")
    target_direction = item.candidate.maneuver_candidate.common_frame_boresight
    target = atan2(target_direction.x, target_direction.z)
    _, turn_time = _turn_duration(state, angle, target)
    earliest = max(o.window_start_seconds, c.simulation_time_seconds + turn_time)
    if earliest + o.imaging_duration_seconds > o.window_end_seconds:
        return angle, [], False, "motion-and-exposure-do-not-fit-window"
    if earliest + o.imaging_duration_seconds > c.simulation_time_seconds + PERIOD:
        raise ValueError("forecast exceeds declared one-cycle lookahead")
    angle, events, ready = _turn(state, c, angle, target)
    if not ready:
        return angle, events, False, "motion-protection-denied"
    events.extend(_hold(state, c, angle, max(o.window_start_seconds, c.simulation_time_seconds)))
    now = c.simulation_time_seconds
    end = now + o.imaging_duration_seconds
    # Optical acquisitions are only admitted wholly within declared illumination.
    # A crossing proposal is never averaged over a discontinuous environment.
    if now % PERIOD >= LIGHT or end > now // PERIOD * PERIOD + LIGHT:
        return angle, events, False, "acquisition-crosses-illumination-boundary"
    wait, diag = _force(state, Fraction(now), angle, "hold", "imaging")
    fallback, fallback_diag = _force(state, Fraction(now), angle)
    view = PlanningView(c.inputs, (request,), (item,), (),
        (CampaignForcing(now, end, wait, state.program.forcing[0].transmitter),),
        state.program.protection, IntegrationPolicy(2 + state.spec.refinement),
        state.program.policy, state.program.knowledge, min(HORIZON, now + PERIOD))
    selected = PlannedAction("imaging", o.opportunity_id.value, now, end, (), "continuous-paid-motion-ready")
    timed, acquisition = image_action(view, selected)
    timed = replace(timed, request=replace(timed.request, standby=fallback))
    result = execute_ms_request(c, InitialAttitudeEvidence(now, target_direction,
        "Observed completed physically paid motion and settling"), timed,
        acquisition=acquisition, policy=view.protection, integration=view.integration)
    outcome = result.outcome
    record = result.created_record
    events.append({"kind": "imaging", "start": now, "end": end,
        "start_angle": angle, "end_angle": angle, "approved": record is not None,
        "request_id": request.product.request.request_id.value,
        "record": None if record is None else canonical_content(record),
        "acquisition": None if record is None else canonical_content(acquisition),
        "acquired_bits": 0 if record is None else int(record.stored_equivalent_bits),
        "reasons": [r.value for r in outcome.availability.reasons],
        "accounting": asdict(outcome.accounting),
        "samples": [_sample_wire(Fraction(now) + Fraction(s.offset_numerator_seconds, view.integration.substeps), s)
            for s in outcome.actual_trace.samples],
        "diagnostics": [{"start": [now, 1], "end": [end, 1], "values": diag if record is not None else fallback_diag}]})
    return angle, events, record is not None, "acquired" if record is not None else "acquisition-protection-denied"


def _contact(state, c, angle, end, blocked):
    start = c.simulation_time_seconds
    if forcing_breakpoints(start, end):
        raise ValueError("contact segment must split at every forcing discontinuity")
    tx_wait, tx_diag = _force(state, Fraction(start), angle, "hold", "contact")
    idle_wait, idle_diag = _force(state, Fraction(start), angle)
    transmitter = state.program.forcing[0].transmitter
    terminal = transmitter.electrical_power_w
    extra_wire = tx_diag["load_wire_loss_w"] - idle_diag["load_wire_loss_w"]
    transmitter = replace(transmitter, electrical_power_w=replace(terminal,
        value=terminal.value + extra_wire, provenance=replace(terminal.provenance,
            rationale="Declared transmitter terminal demand plus derived incremental main-wire ON-state loss")))
    tx = CoupledDownlinkInputs(transmitter, idle_wait.loads, tx_wait.sunlit, tx_wait.incidence_angle_deg,
        tx_wait.routing_config, tx_wait.thermal_inputs, tx_wait.external_heat_sources, tx_wait.solar_degradation_forcing)
    records = sorted(c.spacecraft_state.data_storage.stored_records,
        key=lambda r: (*request_rank(_request_for_record(state, r)[0]), r.record_id.value))
    # Existing bounded per-contact selection remains 32. Older retained records
    # are neither deleted nor forgotten; the next physical segment sees them.
    selected = () if blocked else tuple(r.record_id for r in records[:32])
    contact = ServiceableGroundContact(ids.GroundContactId(f"task05fa-contact-{start}-{end}"),
        ids.GroundStationId("task05fa-declared-synthetic-station"), start, end)
    result = execute_contact_plan(c, ContactPlan(contact, selected, tx, idle_wait),
        consumed_contacts=ConsumedContacts(()), policy=state.program.protection,
        integration=IntegrationPolicy(state.spec.refinement))
    # Monotone clock + phase/cycle cursor authorize each unique [start,end) once.
    # The old <=128 consumed-contact wrapper remains untouched; actual completed
    # custody still retains every completing contact and rejects duplicate use.
    outcome = result.outcome
    services = []
    for service in outcome.services:
        request, item = _request_for_record(state, service.record)
        assessment = assess_ms_product(request.product, (MSAcquisitionEvidence(service.record, item.acquisition),),
            c.ground_data_delivery_state, (outcome,), end) if service.completed else None
        services.append({"record_id": service.record.record_id.value,
            "request_id": request.product.request.request_id.value,
            "priority": request.product.request.priority_weight,
            "record": canonical_content(service.record), "product": canonical_content(request.product),
            "acquisition": canonical_content(item.acquisition),
            "before_bits": service.progress_before_bits, "transmitted_bits": service.transmitted_bits,
            "after_bits": service.progress_after_bits, "completed": service.completed,
            "start_offset": [service.start_offset.numerator, service.start_offset.denominator],
            "end_offset": [service.end_offset.numerator, service.end_offset.denominator],
            "credited": False if assessment is None else bool(assessment.credited_products),
            "credit_reasons": [] if assessment is None else list(assessment.reasons),
            "completion": None if not service.completed else [
                (Fraction(start) + service.end_offset.fraction).numerator,
                (Fraction(start) + service.end_offset.fraction).denominator]})
    event = {"kind": "contact", "start": start, "end": end, "start_angle": angle, "end_angle": angle,
        "parent_contact": [state.cycle_index * PERIOD + CONTACT_START, state.cycle_index * PERIOD + CONTACT_END],
        "approved": outcome.denied_record_id is None, "services": services, "bitrate_bps": outcome.bitrate_bps,
        "reasons": list(dict.fromkeys(r.value for a in outcome.attempts for r in a.availability.reasons)),
        "blocked_before": blocked, "accounting": asdict(outcome.accounting),
        "samples": [_sample_wire(Fraction(start) + Fraction(s.offset_numerator_seconds, segment.trace.denominator), s)
            for segment in outcome.segments for s in segment.trace.samples],
        "diagnostics": [{"start": [(Fraction(start) + segment.trace.start_offset.fraction).numerator,
                                    (Fraction(start) + segment.trace.start_offset.fraction).denominator],
            "end": [(Fraction(start) + segment.trace.end_offset.fraction).numerator,
                      (Fraction(start) + segment.trace.end_offset.fraction).denominator],
            "values": tx_diag if segment.transmitter_on else idle_diag} for segment in outcome.segments]}
    return event, blocked or outcome.denied_record_id is not None


def _account(previous, events):
    import copy
    total = copy.deepcopy(previous)
    for event in events:
        if "accounting" not in event:
            total["forecast_rejections"] += int(event["kind"] == "forecast-rejection")
            continue
        phase = event["kind"]
        total["phase_seconds"][phase] = total["phase_seconds"].get(phase, 0) + event["end"] - event["start"]
        for key, value in event["accounting"].items():
            if key == "numerical_substeps":
                total[key] += value
            else:
                total["energies"][key] = total["energies"].get(key, 0.) + value
        total["actual_denials"] += int(not event["approved"])
        total["acquired"] += int(phase == "imaging" and event["approved"])
        total["acquired_bits"] += event.get("acquired_bits", 0)
        for service in event.get("services", ()):
            total["transmitted_bits"] += service["transmitted_bits"]
            total["completed"] += int(service["completed"])
            total["credited"] += int(service["credited"])
            total["weighted_credit"] += service["priority"] * int(service["credited"])
        for sample in event["samples"]:
            total["minimum_energy_wh"] = min(total["minimum_energy_wh"], sample["energy_wh"])
            total["maximum_energy_wh"] = max(total["maximum_energy_wh"], sample["energy_wh"])
            for node, temp in sample["temperatures_k"].items():
                total["minimum_temperatures_k"][node] = min(total["minimum_temperatures_k"][node], temp)
                total["maximum_temperatures_k"][node] = max(total["maximum_temperatures_k"][node], temp)
        for interval in event["diagnostics"]:
            hours = float(Fraction(*interval["end"]) - Fraction(*interval["start"])) / 3600
            for key, value in interval["values"].items():
                if key.endswith("_w"):
                    name = key[:-2] + "_wh"
                    total["diagnostic_energy_wh"][name] = total["diagnostic_energy_wh"].get(name, 0.) + value * hours
    return total


def validate_state(state, *, full_binding=False):
    if type(state) is not ContinuousState or type(state.spec) is not ContinuousSpec:
        raise TypeError("exact continuous boundary required")
    state.spec.__post_init__()
    now = state.context.simulation_time_seconds
    if type(state.angle_rad) is not float or not isfinite(state.angle_rad):
        raise ValueError("completed attitude must be finite built-in float")
    for name in ("cycle_index", "next_request_index", "advances", "events_emitted", "event_count"):
        if type(getattr(state, name)) is not int or getattr(state, name) < 0:
            raise ValueError("invalid continuous cursor " + name)
    if (state.cycle_index > HORIZON // PERIOD or state.next_request_index > 6
            or type(state.contact_blocked) is not bool or type(state.phase) is not str
            or state.phase not in ("requests", "contact", "recovery")):
        raise ValueError("invalid continuous phase")
    if not state.cycle_index * PERIOD <= now <= min(HORIZON, (state.cycle_index + 1) * PERIOD):
        raise ValueError("cycle cursor disagrees with physical clock")
    if state.cycle_index != now // PERIOD:
        raise ValueError("cycle cursor must advance at the completed periodic boundary")
    offset = now - state.cycle_index * PERIOD
    if state.phase == "requests" and offset >= CONTACT_START:
        raise ValueError("request phase cannot resume after contact preparation")
    if state.phase == "contact" and not CONTACT_START <= offset < CONTACT_END:
        raise ValueError("contact cursor outside declared service")
    if state.phase == "recovery" and offset < CONTACT_END:
        raise ValueError("recovery starts after contact")
    if state.phase != "requests" and state.next_request_index != 6:
        raise ValueError("contact/recovery requires completed request decisions")
    if type(state.event_digest) is not str or len(state.event_digest) != 64 or any(c not in "0123456789abcdef" for c in state.event_digest):
        raise ValueError("invalid evidence chain head")
    if state.event_count > state.events_emitted or (state.event_count == 0) != (state.event_digest == ZERO_DIGEST):
        raise ValueError("written evidence cursor disagrees with emitted events")
    if type(state.accounting) is not dict or type(state.last_events) is not tuple:
        raise ValueError("invalid continuous accounting/evidence")
    if full_binding:
        from .continuous_trade_io import validate_accounting
        from .design_trade_design import design_record
        expected = start_continuous(state.spec)
        if canonical_content((state.context.inputs, state.program)) != canonical_content((expected.context.inputs, expected.program)):
            raise ValueError("immutable continuous input binding mismatch")
        if canonical_content(state.template_spec.to_dict()) != canonical_content(expected.template_spec.to_dict()):
            raise ValueError("continuous physical template mismatch")
        if canonical_content(design_record(state.design)) != canonical_content(design_record(expected.design)):
            raise ValueError("continuous derived design mismatch")
        if set(state.accounting) != set(expected.accounting):
            raise ValueError("continuous accounting fields mismatch")
        checked_checkpoint(state.context)
        # Persistent totals must reconcile with retained physical and custody truth.
        deliveries = state.context.ground_data_delivery_state.completed_deliveries
        onboard = state.context.spacecraft_state.data_storage.stored_records
        if state.accounting["completed"] != len(deliveries) or state.accounting["acquired"] != len(deliveries) + len(onboard):
            raise ValueError("continuous counters disagree with retained custody")
        validate_accounting(state)


def advance_continuous(state, *, stop_seconds=None):
    """One bounded decision/macro/contact/hold; no replay or input reconstruction.

    A stop inside an atomic acquisition/motion macro is unsupported and rejected
    without mutation. Pilot/day stops occur at cycle boundaries; contact chunks
    and stationary recovery are genuine restart boundaries with partial custody.
    """
    validate_state(state)
    now = state.context.simulation_time_seconds
    stop = HORIZON if stop_seconds is None else stop_seconds
    if type(stop) is not int or not now < stop <= HORIZON:
        raise ValueError("stop must be a later completed time within the actual month")
    c = checked_checkpoint(state.context).restore(state.context.inputs)
    events = []
    angle = state.angle_rad
    index, phase, blocked = state.next_request_index, state.phase, state.contact_blocked
    cycle = state.cycle_index
    forecast_work = 0
    if phase == "requests":
        published = published_requests(state, now)
        if index == 0 and now == cycle * PERIOD:
            events.append({"kind": "release", "at": now, "cycle": cycle,
                "requests": [canonical_content(pair[0]) for pair in published],
                "opportunities": [canonical_content(pair[1]) for pair in published]})
        for pair in published[index:]:
            index += 1
            o = pair[1].opportunity
            # An execution cutoff does not silently turn a request into a reject.
            if max(o.window_start_seconds, c.simulation_time_seconds) + o.imaging_duration_seconds > stop:
                raise ValueError("stop lies inside a pending paid macro; use a completed boundary")
            feedback = observe_continuous(state)
            predicted = forecast_context(state, feedback)
            _, trial, approved, reason = _macro(state, predicted, feedback.angle_rad, pair)
            forecast_work += sum(e["accounting"]["numerical_substeps"] for e in trial)
            if not approved:
                events.append({"kind": "forecast-rejection", "at": now,
                    "request_id": pair[0].product.request.request_id.value, "reason": reason,
                    "forecast_end": predicted.simulation_time_seconds})
                continue
            angle, actual, approved, reason = _macro(state, c, angle, pair)
            events.extend(actual)
            break
        else:
            contact_start = cycle * PERIOD + CONTACT_START
            if contact_start > stop:
                raise ValueError("stop precedes next completed contact preparation boundary")
            angle, turned, ready = _turn(state, c, angle, 0.)
            events.extend(turned)
            blocked = not ready
            if c.simulation_time_seconds > contact_start:
                raise ValueError("paid contact preparation exceeded declared service start")
            events.extend(_hold(state, c, angle, contact_start))
            phase = "contact"
    elif phase == "contact":
        end = min(cycle * PERIOD + CONTACT_END, now + state.spec.contact_chunk_seconds, stop)
        cuts = forcing_breakpoints(now, end)
        if cuts:
            end = cuts[0]
        event, blocked = _contact(state, c, angle, end, blocked)
        events.append(event)
        if end == cycle * PERIOD + CONTACT_END:
            phase = "recovery"
    else:
        end = min((cycle + 1) * PERIOD, now + 600, stop)
        events.extend(_hold(state, c, angle, end))
        if end == (cycle + 1) * PERIOD:
            cycle += 1
            index, phase, blocked = 0, "requests", False
    if c.simulation_time_seconds > stop:
        raise ValueError("requested stop would interrupt an atomic physical macro")
    totals = _account(state.accounting, events)
    totals["forecast_substeps"] += forecast_work
    c.controller_state = replace(c.controller_state, replan_count=c.controller_state.replan_count + 1)
    result = replace(state, context=c, angle_rad=angle, cycle_index=cycle,
        next_request_index=index, phase=phase, contact_blocked=blocked,
        advances=state.advances + 1, events_emitted=state.events_emitted + len(events),
        accounting=totals, last_events=tuple(events))
    validate_state(result)
    return result


def summary(state):
    validate_state(state, full_binding=True)
    now = state.context.simulation_time_seconds
    c = state.context
    # Pilot accounting covers [0, now); requests released exactly at the next
    # cycle boundary belong to the following interval, not the finished day.
    published_cycles = min(HORIZON // PERIOD, (now + PERIOD - 1) // PERIOD)
    capacity = state.design.capacity_wh
    return {"status": "completed-month" if now == HORIZON else "pilot-boundary",
        "seconds": now, "immutable_horizon_seconds": HORIZON, "spec": state.spec.to_dict(),
        "offered_products": published_cycles * 6,
        "accounting": state.accounting, "final_energy_wh": c.spacecraft_state.battery.energy_wh,
        "final_temperatures_k": {n.node_id.value: n.temperature_k for n in c.spacecraft_state.thermal.node_states},
        "initial_energy_wh": capacity * state.spec.initial_fraction,
        "sampled_maximum_depth_of_discharge_fraction": 1 - state.accounting["minimum_energy_wh"] / capacity,
        "onboard_records": len(c.spacecraft_state.data_storage.stored_records),
        "partial_records": len(c.ground_data_delivery_state.partial_transfers),
        "completed_records": len(c.ground_data_delivery_state.completed_deliveries),
        "battery_throughput_wh": c.spacecraft_state.degradation.battery.cumulative_energy_throughput_wh,
        "event_count": state.event_count, "event_digest": state.event_digest, "advances": state.advances,
        "checkpoint": checked_checkpoint(c).to_dict()}
