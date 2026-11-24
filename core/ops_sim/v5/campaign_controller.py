"""One deterministic rolling policy over received knowledge and declared forecasts.

The public planner takes no SimulationContext, checkpoint, scoring ledger or
future outcomes. All physical trials below own newly reconstructed/isolated state.
"""

from dataclasses import dataclass, replace
from fractions import Fraction
from math import ceil

from .campaign_contract import (BoundaryFeedback, ResourceObservation, PlannedAction,
    RollingPlan, RollingPolicy, BoundaryKnowledgeMode, ReleasedMSRequest,
    MSOpportunity, CampaignForcing, typed, sequence)
from .communications import ServiceableGroundContact
from .checkpoint import ThermalNodeStateSnapshot
from .contact_execution import (ContactPlan, ConsumedContacts, ContactOutcome,
                                execute_contact_plan, _integer_quantity)
from .context import SimulationContext
from .continuation import ImagingAction, checked_checkpoint
from .controller_state import ControllerState
from .coupled_downlink import CoupledDownlinkInputs
from .data_delivery import GroundDataDeliveryState, CompletedAcquisitionDelivery
from .degradation import SolarDegradationForcingInput
from .diagnostics import Diagnostics
from .ids import AcquisitionDataRecordId
from .imaging_execution import ScheduledObservationAcquisitionExecution
from .imaging_resources import AcquisitionEPSIntervalEnvironment
from .knowledge import GroundKnowledgeState
from .mission import MissionState
from .ms_acquisition import execute_ms_request
from .ms_acquisition import InitialAttitudeEvidence
from .adcs import compute_boresight_transition
from .ms_product import MSAcquisitionEvidence
from .operational_protection import ProtectedRequest, StandbyAction
from .state import (SpacecraftState, BatteryState, PropulsionState, ThermalState,
    DegradationState, BatteryDegradationState, SolarDegradationState, OnboardOperationsState,
    DataStorageState)
from .substepped_execution import TimedRequest


@dataclass(frozen=True, slots=True)
class PlanningView:
    inputs: object
    requests: tuple
    opportunities: tuple
    contacts: tuple
    forcing: tuple
    protection: object
    integration: object
    policy: object
    knowledge_mode: object
    until_seconds: int


@dataclass(frozen=True, slots=True)
class PlanningKnowledge:
    feedback: BoundaryFeedback
    acknowledgements: tuple[BoundaryFeedback, ...]
    previous_execution: object
    consumed_contacts: ConsumedContacts
    acquired_request_ids: tuple
    failed_opportunity_ids: tuple[str, ...]


class CampaignBudgetExceeded(ValueError):
    """Incomplete/unsupported work budget, never a completed campaign."""


def request_rank(request):
    p = request.product
    return (-p.request.priority_weight, p.delivery_deadline_seconds, p.request.request_id.value)


def observe_boundary(context, mode, *, outcome=None, acquisition=None):
    """Explicit trusted telemetry/ack adapter. Never called by a policy on truth."""
    s = context.spacecraft_state
    resource = ResourceObservation(s.battery.energy_wh, s.degradation.battery.usable_capacity_retention,
        s.degradation.solar.generation_retention, s.degradation.battery.cumulative_energy_throughput_wh,
        tuple(ThermalNodeStateSnapshot.from_state(n) for n in s.thermal.node_states
              if n.node_id in mode.observed_temperature_node_ids),
        s.onboard.operational_mode, s.onboard.fdir_state, s.onboard.critical_energy_since_seconds)
    contact = outcome.contact if type(outcome) is ContactOutcome else None
    reasons = (() if outcome is None else
        tuple(dict.fromkeys(r.value for a in outcome.attempts for r in a.availability.reasons))
        if contact is not None else tuple(r.value for r in outcome.availability.reasons))
    return BoundaryFeedback(context.simulation_time_seconds, context.simulation_time_seconds, resource,
        s.data_storage.stored_records, context.ground_data_delivery_state.partial_transfers,
        "initial" if outcome is None else "contact" if contact is not None else outcome.actual_kind.value,
        reasons, acquisition, contact, outcome.services if contact is not None else ())


def planning_context(view, knowledge):
    """Reconstruct needed state only from observed fields/acknowledgements/estimates.

    Unused delta-v is declared zero; legacy knowledge, mission, authority and
    diagnostics are empty local placeholders, never copied from real state.
    """
    from .experiment_codec import canonical_copy
    f = knowledge.feedback
    typed(f, BoundaryFeedback)
    inputs, f, estimates = canonical_copy((view.inputs, f, view.knowledge_mode.estimated_temperatures))
    r = f.resources
    observed = tuple(n.node_id for n in r.observed_temperatures)
    if (len(observed) != len(set(observed))
            or set(observed) != set(view.knowledge_mode.observed_temperature_node_ids)):
        raise ValueError("received temperature fields disagree with declared knowledge mode")
    temperatures = {n.node_id: n for n in (*r.observed_temperatures, *estimates)}
    network = inputs.spacecraft_configuration.thermal.network
    if set(temperatures) != {n.node_id for n in network.nodes}:
        raise ValueError("every planning temperature needs observation or explicit estimate")
    deliveries = tuple(CompletedAcquisitionDelivery(s.record, ack.contact)
        for ack in knowledge.acknowledgements for s in ack.services if s.completed)
    context = SimulationContext(f.received_at_seconds, inputs,
        SpacecraftState(BatteryState(r.battery_energy_wh), PropulsionState(0.),
            ThermalState(tuple(temperatures[n.node_id].restore() for n in network.nodes)),
            DegradationState(BatteryDegradationState(r.battery_retention, r.throughput_wh),
                             SolarDegradationState(r.solar_retention)),
            OnboardOperationsState(r.operational_mode, r.fdir_state, None, None, None,
                                   r.critical_energy_since_seconds), DataStorageState(f.onboard_records)),
        GroundKnowledgeState(None, ()), GroundDataDeliveryState(f.partial_transfers, deliveries),
        MissionState((), (), (), None, (), ()),
        ControllerState(inputs.model_manifest.controller_id, None, 0), Diagnostics(0))
    checked_checkpoint(context)
    return context


def forcing_for(view, start, end):
    segment = next((s for s in view.forcing if s.start_seconds <= start < end <= s.end_seconds), None)
    if segment is None:
        raise ValueError("atomic action crosses an unsupported forcing boundary")
    wait = segment.standby
    if wait.solar_degradation_forcing is not None:
        total = wait.solar_degradation_forcing.retention_loss
        loss = float(Fraction(total) * Fraction(end-start, segment.end_seconds-segment.start_seconds))
        if total > 0 and loss == 0:
            raise ValueError("positive solar forcing allocation underflows")
        wait = replace(wait, solar_degradation_forcing=SolarDegradationForcingInput(loss))
    return segment, wait


def image_action(view, selected):
    from .experiment_codec import content_digest
    item = next(o for o in view.opportunities if o.opportunity.opportunity_id.value == selected.identity)
    _, wait = forcing_for(view, selected.start_seconds, selected.end_seconds)
    rid = AcquisitionDataRecordId("ms7-" + content_digest("ms7-record-v1",
        (item.acquisition.request.request_id, item.opportunity.opportunity_id, selected.start_seconds)))
    execution = ScheduledObservationAcquisitionExecution(item.candidate, selected.start_seconds)
    action = ImagingAction("ms7-image-" + rid.value, execution, rid,
        AcquisitionEPSIntervalEnvironment(wait.sunlit, wait.incidence_angle_deg, wait.loads),
        wait.routing_config, wait.thermal_inputs, wait.external_heat_sources, wait.solar_degradation_forcing)
    return TimedRequest(selected.start_seconds, selected.end_seconds, ProtectedRequest(action, wait)), item.acquisition


def execute_selected(context, view, selected, previous, consumed):
    """Materialize one selected full action into accepted executors, no new physics."""
    segment, wait = forcing_for(view, selected.start_seconds, selected.end_seconds)
    if selected.kind == "contact":
        contact = next(c for c in view.contacts if c.contact_id.value == selected.identity)
        if (selected.start_seconds, selected.end_seconds) != (contact.start_time_seconds, contact.end_time_seconds):
            raise ValueError("contact identity must retain original interval")
        tx = CoupledDownlinkInputs(segment.transmitter, wait.loads, wait.sunlit, wait.incidence_angle_deg,
            wait.routing_config, wait.thermal_inputs, wait.external_heat_sources, wait.solar_degradation_forcing)
        result = execute_contact_plan(context, ContactPlan(contact, selected.record_ids, tx, wait),
            consumed_contacts=consumed, policy=view.protection, integration=view.integration)
        return result.outcome, None, previous, result.consumed_contacts
    if selected.kind == "imaging":
        timed, acquisition = image_action(view, selected)
    else:
        timed = TimedRequest(selected.start_seconds, selected.end_seconds,
            ProtectedRequest(StandbyAction(selected.identity), wait))
        acquisition = None
    result = execute_ms_request(context, previous, timed, acquisition=acquisition,
        policy=view.protection, integration=view.integration)
    evidence = MSAcquisitionEvidence(result.created_record, acquisition) if result.created_record is not None else None
    return result.outcome, evidence, result.previous_execution, consumed


def capacity_screen(view, context, product, bits, acquisition_end):
    """Optimistic contact capacity minus ALL queued remaining bits; no RF guarantee.

    Beyond-lookahead insufficiency is unknown. Full known horizon insufficiency
    screens a candidate only for this bounded policy, not mathematical infeasibility.
    """
    deadline = product.delivery_deadline_seconds
    rate = _integer_quantity(view.inputs.spacecraft_configuration.communications.nominal_downlink_data_rate_bps.value,
                             "declared bitrate", positive=True)
    capacity = sum(rate * max(0, min(c.end_time_seconds, deadline, view.until_seconds)-c.start_time_seconds)
        for c in view.contacts if c.start_time_seconds >= acquisition_end)
    progress = {p.record_id: int(p.transmitted_equivalent_bits) for p in context.ground_data_delivery_state.partial_transfers}
    queued = sum(int(r.stored_equivalent_bits)-progress.get(r.record_id, 0)
                 for r in context.spacecraft_state.data_storage.stored_records)
    if capacity >= queued + bits:
        return "declared-capacity-sufficient"
    return "capacity-unknown-beyond-lookahead" if deadline > view.until_seconds else "queued-capacity-screen"


def build_rolling_plan(view, knowledge):
    """Build several forecast actions; caller executes ONLY the first and refreshes.

    Request releases remain filtered at this real boundary, even for later plan
    actions. No future request contents or hidden release clocks enter this API.
    """
    from .experiment_codec import canonical_copy
    if type(view) is not PlanningView or type(knowledge) is not PlanningKnowledge:
        raise TypeError("planner requires isolated view and received knowledge")
    typed(view.policy, RollingPolicy)
    typed(view.knowledge_mode, BoundaryKnowledgeMode)
    sequence(view.requests, ReleasedMSRequest, 16)
    sequence(view.opportunities, MSOpportunity, 64)
    sequence(view.contacts, ServiceableGroundContact, 64)
    sequence(view.forcing, CampaignForcing, 64)
    sequence(knowledge.acknowledgements, BoundaryFeedback, 128)
    now = knowledge.feedback.received_at_seconds
    if (type(view.until_seconds) is not int or not now < view.until_seconds
            <= min(view.inputs.common_world.horizon_seconds, now+view.policy.lookahead_seconds)):
        raise ValueError("forecast horizon outside bounded current visibility")
    if any(r.release_seconds > now for r in view.requests):
        raise ValueError("planner cannot receive unreleased requests")
    known = {r.product.request.request_id for r in view.requests}
    if any(o.acquisition.request.request_id not in known for o in view.opportunities):
        raise ValueError("planner opportunity refers to unavailable request")
    if any(a.received_at_seconds > now for a in knowledge.acknowledgements):
        raise ValueError("planner cannot receive future acknowledgements")
    c = planning_context(view, knowledge)
    previous = canonical_copy(knowledge.previous_execution)
    consumed = canonical_copy(knowledge.consumed_contacts)
    acquired = set(knowledge.acquired_request_ids)
    failed = set(knowledge.failed_opportunity_ids)
    ranked = sorted(view.requests, key=request_rank)
    ranks = {r.product.request.request_id: request_rank(r) for r in ranked}
    products = {r.product.request.request_id: r.product for r in ranked}
    plans, rejected = [], []
    evaluations = work = 0

    def reject(identity, reason):
        # Evidence concerns this actual selection boundary; forecast suffix
        # choices carry their own selection reasons, not ambiguous rejections.
        if not plans:
            rejected.append((identity, reason))

    def trial(action):
        nonlocal evaluations, work
        cost = ((2*len(action.record_ids)+1) if action.kind == "contact" else 2)*view.integration.substeps
        if evaluations + 1 > view.policy.max_candidate_evaluations or work + cost > view.policy.max_forecast_eps:
            raise CampaignBudgetExceeded("forecast evaluation/work budget exhausted; campaign incomplete")
        evaluations += 1
        work += cost
        clone = checked_checkpoint(c).restore(c.inputs)
        result = execute_selected(clone, view, action, previous, consumed)
        return clone, result

    while len(plans) < view.policy.plan_actions and c.simulation_time_seconds < view.until_seconds:
        now = c.simulation_time_seconds
        chosen = evaluated = None
        # Contacts are nonoverlapping, admitted full intervals, and start exactly now.
        for contact in view.contacts:
            if (contact.start_time_seconds != now or contact in consumed.contacts
                    or contact.end_time_seconds > view.until_seconds):
                continue
            order = tuple(r.record_id for r in sorted(c.spacecraft_state.data_storage.stored_records,
                key=lambda r: (*ranks[r.imaging_request_id], r.record_id.value))
                if products[r.imaging_request_id].delivery_deadline_seconds >= now)
            if not order:
                reject(contact.contact_id.value, "no-useful-acknowledged-backlog")
                continue
            action = PlannedAction("contact", contact.contact_id.value, now, contact.end_time_seconds, order,
                                   "contact-start-ranked-backlog")
            candidate, result = trial(action)
            if result[0].transmitted_bits:
                chosen, evaluated = action, (candidate, result)
                break
            reject(contact.contact_id.value, "forecast-contact-denied")

        if chosen is None:
            for request in ranked:
                p = request.product
                if p.request.request_id in acquired or now >= p.delivery_deadline_seconds:
                    reject(p.request.request_id.value, "already-acquired" if p.request.request_id in acquired else "request-expired")
                    continue
                options = sorted((o for o in view.opportunities if o.acquisition.request.request_id == p.request.request_id),
                    key=lambda o: (o.opportunity.window_start_seconds, o.opportunity.opportunity_id.value))
                for item in options:
                    o = item.opportunity
                    identity = o.opportunity_id.value
                    end = now + o.imaging_duration_seconds
                    if identity in failed:
                        reject(identity, "previous-actual-denial")
                        continue
                    if not (max(o.window_start_seconds, p.acquisition_start_seconds) <= now
                            and end <= min(o.window_end_seconds, p.acquisition_end_seconds, view.until_seconds)):
                        reject(identity, "outside-current-full-exposure-window")
                        continue
                    if not any(s.start_seconds <= now < end <= s.end_seconds for s in view.forcing):
                        reject(identity, "atomic-imaging-crosses-forcing-boundary")
                        continue
                    screen = capacity_screen(view, c, p, item.acquisition.sizing.stored_bits, end)
                    if screen == "queued-capacity-screen":
                        reject(identity, screen)
                        continue
                    action = PlannedAction("imaging", identity, now, end, (), "highest-ranked-feasible;"+screen)
                    candidate, result = trial(action)
                    if result[1] is not None:
                        chosen, evaluated = action, (candidate, result)
                        break
                    reasons = ",".join(r.value for r in result[0].availability.reasons)
                    reject(identity, "forecast-acquisition-denied:"+reasons)
                if chosen is not None:
                    break

        if chosen is None:
            events = [view.until_seconds, now+view.policy.standby_poll_seconds]
            events += [s.end_seconds for s in view.forcing if s.start_seconds <= now < s.end_seconds]
            events += [c.start_time_seconds for c in view.contacts if c.start_time_seconds > now]
            for item in view.opportunities:
                p = products[item.acquisition.request.request_id]
                if p.request.request_id not in acquired:
                    events.extend(t for t in (item.opportunity.window_start_seconds, p.acquisition_start_seconds,
                                              item.opportunity.window_end_seconds, p.delivery_deadline_seconds) if t > now)
                    if type(previous) is InitialAttitudeEvidence:
                        origin, direction = previous.at_seconds, previous.common_frame_boresight
                    else:
                        origin = previous.scheduled_start_seconds + previous.candidate.opportunity.imaging_duration_seconds
                        direction = previous.candidate.common_frame_boresight
                    transition = compute_boresight_transition(view.inputs.spacecraft_configuration.adcs.agile_pointing,
                        direction, item.candidate.maneuver_candidate.common_frame_boresight)
                    ready = ceil(Fraction(origin) + Fraction(transition.total_transition_time_seconds))
                    if ready > now:
                        events.append(ready)
            end = min(t for t in events if t > now)
            chosen = PlannedAction("standby", f"ms7-standby-{now}-{end}", now, end, (), "physical-wait-next-known-event-or-poll")
            evaluated = trial(chosen)
        c, (outcome, evidence, previous, consumed) = evaluated
        if evidence is not None:
            acquired.add(evidence.plan.request.request_id)
        plans.append(chosen)
    f = knowledge.feedback
    return RollingPlan(f.sampled_at_seconds, f.received_at_seconds, view.until_seconds,
        tuple(plans), tuple(rejected), evaluations, work)
