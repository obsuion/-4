"""Behavioral references for the common rolling controller and knowledge boundary."""

from dataclasses import replace, fields
from fractions import Fraction

import pytest

from examples.v5_ms_campaign_demo import build_demo_state, run
from ops_sim.v5.campaign_contract import RollingPolicy, BoundaryKnowledgeMode, CampaignForcing
from ops_sim.v5.campaign_continuation import (start_campaign, advance_campaign, planning_boundary,
                                             campaign_summary)
from ops_sim.v5.campaign_controller import build_rolling_plan, CampaignBudgetExceeded
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.ids import ObservationOpportunityId


def plan(state):
    return build_rolling_plan(*planning_boundary(state.context.inputs, state.program, state.memory))


def edit_request(state, index, **changes):
    p = state.program
    requests = list(p.requests)
    old = requests[index].product
    if 'priority_weight' in changes:
        request = replace(old.request, priority_weight=changes.pop('priority_weight'))
        changes['request'] = request
    product = replace(old, **changes)
    requests[index] = replace(requests[index], product=product)
    opportunities = tuple(replace(o, acquisition=replace(o.acquisition, request=product.request))
        if o.acquisition.request.request_id == old.request.request_id else o for o in p.opportunities)
    return start_campaign(state.context.inputs, replace(p, requests=tuple(requests), opportunities=opportunities))


def at_decision(state, n):
    for _ in range(n):
        state = advance_campaign(state)
    return state


def test_actual_rolling_priority_competition_and_no_truth_mutation():
    s = build_demo_state()
    before = canonical_content((CheckpointState.from_context(s.context), s.program, s.memory))
    a, b = plan(s), plan(s)
    assert a == b
    assert [(x.kind, x.identity) for x in a.actions[:2]] == [('imaging', 'op-a'), ('imaging', 'op-b')]
    assert len(a.actions) == 3
    assert before == canonical_content((CheckpointState.from_context(s.context), s.program, s.memory))
    assert advance_campaign(s).context.simulation_time_seconds == 110
    assert s.context.simulation_time_seconds == 100


@pytest.mark.parametrize('priority,deadline,expected', [(4., 320, 'op-b'), (3., 299, 'op-b'), (3., 300, 'op-a')])
def test_rank_priority_then_deadline_then_request_identity(priority, deadline, expected):
    s = edit_request(build_demo_state(), 1, priority_weight=priority, delivery_deadline_seconds=deadline)
    assert plan(s).actions[0].identity == expected


def test_opportunity_tie_is_stable_not_input_order():
    s = build_demo_state(); o = s.program.opportunities[0]
    renamed = replace(o, candidate=replace(o.candidate, maneuver_candidate=replace(o.candidate.maneuver_candidate,
        opportunity=replace(o.opportunity, opportunity_id=ObservationOpportunityId('aaa')))))
    s = start_campaign(s.context.inputs, replace(s.program, opportunities=(*s.program.opportunities, renamed)))
    assert plan(s).actions[0].identity == 'aaa'


def test_unreleased_request_contents_do_not_influence_earlier_plan():
    s = build_demo_state()
    changed = edit_request(s, 2, priority_weight=1000., delivery_deadline_seconds=350)
    assert plan(s) == plan(changed)
    view, knowledge = planning_boundary(s.context.inputs, s.program, s.memory)
    assert {r.product.request.request_id.value for r in view.requests} == {'ms7-a', 'ms7-b'}
    assert not any(o.opportunity.opportunity_id.value == 'op-c' for o in view.opportunities)
    assert not {'context', 'checkpoint', 'program', 'diagnostics', 'assessment'} & {f.name for f in fields(view)}
    assert not hasattr(knowledge, 'ground_data_delivery_state')


def test_unobserved_truth_is_not_a_hidden_planning_input():
    s = build_demo_state(denial=True)
    cp = s.program.initial_checkpoint
    nodes = tuple(replace(n, temperature_k=350.) if n.node_id.value == 'payload' else n for n in cp.spacecraft.thermal.node_states)
    changed = replace(cp, spacecraft=replace(cp.spacecraft, delta_v_remaining_m_per_s=1.,
        thermal=replace(cp.spacecraft.thermal, node_states=nodes)))
    other = start_campaign(s.context.inputs, replace(s.program, initial_checkpoint=changed))
    assert s.memory.initial_feedback == other.memory.initial_feedback
    assert plan(s) == plan(other)


def test_actual_denial_advances_full_duration_and_replans_from_ack():
    s = build_demo_state(denial=True)
    assert plan(s).actions[0].identity == 'op-a'
    denied = advance_campaign(s)
    assert denied.context.simulation_time_seconds == 110
    d = denied.memory.decisions[0]
    assert d.feedback.actual_kind == 'standby' and d.feedback.reasons
    assert d.feedback.acquisition is None and not d.feedback.onboard_records
    assert denied.context.spacecraft_state.battery.energy_wh < s.context.spacecraft_state.battery.energy_wh
    assert d.feedback.sampled_at_seconds == d.feedback.received_at_seconds == 110
    assert plan(denied).actions[0].identity == 'op-b'


def test_storage_forecast_selects_lower_ranked_feasible_product():
    s = build_demo_state(); inputs = s.context.inputs; cfg = inputs.spacecraft_configuration
    storage = replace(cfg.storage, usable_capacity_gb=replace(cfg.storage.usable_capacity_gb, value=0.01))
    s = start_campaign(replace(inputs, spacecraft_configuration=replace(cfg, storage=storage)), s.program)
    p = plan(s)
    assert p.actions[0].identity == 'op-b'  # 12 Mbit fits; 113689008 bits do not.
    assert any(identity == 'op-a' and 'denied' in reason for identity, reason in p.rejected)


@pytest.mark.parametrize('resource', ['battery', 'thermal'])
def test_observed_resource_forecasts_prevent_known_failure(resource):
    s = build_demo_state(denial=(resource == 'thermal'))
    p = s.program
    if resource == 'battery':
        p = replace(p, initial_checkpoint=replace(p.initial_checkpoint,
            spacecraft=replace(p.initial_checkpoint.spacecraft, battery_energy_wh=0.001)))
    else:
        p = replace(p, knowledge=BoundaryKnowledgeMode(p.knowledge.mode,
            tuple(n.node_id for n in s.context.spacecraft_state.thermal.node_states), (), 'All temperatures observed.'))
    s = start_campaign(s.context.inputs, p)
    result = plan(s)
    assert result.actions[0].kind == 'standby'
    assert any('mission-full-service' in reason if resource == 'battery' else 'outside-operating' in reason
               for _, reason in result.rejected)


def test_capacity_screen_and_unknown_horizon_are_distinct():
    s = build_demo_state()
    none = start_campaign(s.context.inputs, replace(s.program, contacts=()))
    assert plan(none).actions[0].kind == 'standby'
    assert any(reason == 'queued-capacity-screen' for _, reason in plan(none).rejected)
    unknown = start_campaign(s.context.inputs, replace(s.program, contacts=(),
        policy=replace(s.program.policy, lookahead_seconds=30)))
    assert plan(unknown).actions[0].identity == 'op-a'
    assert 'unknown' in plan(unknown).actions[0].reason


@pytest.fixture(scope='module')
def completed():
    s, reason = run(build_demo_state())
    assert reason is None
    return s


def test_multiple_products_partial_exact_completion_and_horizon(completed):
    report = campaign_summary(completed)
    assert report['status'] == 'completed-horizon'
    assert report['metrics'] == {'clock_seconds': 380, 'decisions': 8, 'acquired_products': 3,
                                  'fully_delivered_products': 3, 'on_time_ms_products': 3}
    first = next(d for d in completed.memory.decisions if d.feedback.contact is not None)
    assert sum(s.transmitted_bits for s in first.feedback.services) == 40000000
    assert first.feedback.partial_transfers[0].transmitted_equivalent_bits == 40000000.
    # Independent integer capacity reference: (113689008-40000000)/1e6 after t=200.
    a = report['requests'][0]
    assert a['exact_completion_seconds'] == {'numerator': 17105563, 'denominator': 62500}
    assert all(x['deadline_met'] for x in report['requests'])
    assert sum(d.feedback.acquisition is not None for d in completed.memory.decisions) == 3
    assert campaign_summary(completed) == report  # no double credit on assessment
    intervals = [(d.plan.actions[0].start_seconds, d.plan.actions[0].end_seconds) for d in completed.memory.decisions]
    assert intervals[0][0] == 100 and intervals[-1][1] == 380
    assert all(a[1] == b[0] for a, b in zip(intervals, intervals[1:]))


def test_request_released_during_physical_action_waits_for_boundary(completed):
    ds = completed.memory.decisions
    assert ds[2].plan.actions[0].start_seconds == 120 and ds[2].plan.actions[0].end_seconds == 140
    assert ds[3].plan.actions[0].kind == 'contact'  # released c waits behind useful backlog
    c = next(d for d in ds if d.feedback.acquisition is not None and d.feedback.acquisition.plan.request.request_id.value == 'ms7-c')
    assert c.plan.actions[0].start_seconds == 180


def test_consumed_contacts_never_reused_and_prior_pointing_derived(completed):
    _, k = planning_boundary(completed.context.inputs, completed.program, completed.memory)
    assert [c.contact_id.value for c in k.consumed_contacts.contacts] == ['ms7-partial', 'ms7-completing']
    assert k.previous_execution.scheduled_start_seconds == 180
    with pytest.raises(ValueError, match='horizon'):
        advance_campaign(completed)


def test_forcing_boundaries_split_standby_and_reject_crossing_contacts():
    s = build_demo_state(); p = s.program; f = p.forcing[0]
    with pytest.raises(ValueError, match='contact crosses forcing'):
        start_campaign(s.context.inputs, replace(p, forcing=(replace(f, end_seconds=150),
            replace(f, start_seconds=150, end_seconds=200), p.forcing[1])))
    # No opportunities: physical standby must end at explicitly declared t=115.
    p = replace(p, opportunities=(), contacts=(), forcing=(replace(f, end_seconds=115),
        replace(f, start_seconds=115, end_seconds=200), p.forcing[1]))
    state = start_campaign(s.context.inputs, p)
    assert plan(state).actions[0].end_seconds == 115
    assert advance_campaign(state).context.simulation_time_seconds == 115


def test_budget_exhaustion_is_incomplete_and_never_mutates_input():
    s = build_demo_state()
    limited = start_campaign(s.context.inputs, replace(s.program, policy=replace(s.program.policy, max_decisions=1)))
    stopped, reason = run(limited)
    assert reason and campaign_summary(stopped)['status'] == 'incomplete'
    assert stopped.context.simulation_time_seconds == 110
    work = start_campaign(s.context.inputs, replace(s.program, policy=replace(s.program.policy, max_candidate_evaluations=1)))
    before = canonical_content(CheckpointState.from_context(work.context))
    with pytest.raises(CampaignBudgetExceeded):
        advance_campaign(work)
    assert canonical_content(CheckpointState.from_context(work.context)) == before


@pytest.mark.parametrize('field,value', [('plan_actions', 1), ('max_decisions', 129), ('max_candidate_evaluations', 129), ('max_forecast_eps', 16385)])
def test_policy_bounds_fail_closed(field, value):
    with pytest.raises(ValueError):
        replace(RollingPolicy(), **{field: value})


def test_unserved_expired_record_is_not_deleted():
    s = build_demo_state()
    s = start_campaign(s.context.inputs, replace(s.program, contacts=(), policy=replace(s.program.policy, lookahead_seconds=30)))
    final, _ = run(s)
    report = campaign_summary(final)
    assert report['metrics']['acquired_products'] == 3
    assert report['metrics']['on_time_ms_products'] == 0
    assert len(final.context.spacecraft_state.data_storage.stored_records) == 3
    assert all(r['status'] == 'acquired-expired' for r in report['requests'])


def short_delivery_case(deadline):
    s = build_demo_state(); p = s.program
    r, o = p.requests[1], p.opportunities[1]  # exact 12000000 bit square
    r = replace(r, product=replace(r.product, acquisition_end_seconds=130, delivery_deadline_seconds=deadline))
    o = replace(o, candidate=replace(o.candidate, maneuver_candidate=replace(o.candidate.maneuver_candidate,
        opportunity=replace(o.opportunity, window_end_seconds=130))))
    contacts = (replace(p.contacts[0], end_time_seconds=150),
                replace(p.contacts[1], start_time_seconds=155, end_time_seconds=185))
    inputs = replace(s.context.inputs, common_world=replace(s.context.inputs.common_world, horizon_seconds=185))
    p = replace(p, requests=(r,), opportunities=(o,), contacts=contacts,
        forcing=(replace(p.forcing[0], end_seconds=185),),
        policy=replace(p.policy, lookahead_seconds=50))
    return start_campaign(inputs, p)


@pytest.mark.parametrize('deadline,status,credit', [(157, 'delivered-on-time', 1), (156, 'delivered-late', 0)])
def test_exact_inclusive_deadline_and_late_are_separate(deadline, status, credit):
    s, reason = run(short_delivery_case(deadline))
    assert reason is None
    result = campaign_summary(s)['requests'][0]
    # First contact transmits 10 Mbit, second completes remaining 2 Mbit at 155+2.
    assert result['exact_completion_seconds'] == {'numerator': 157, 'denominator': 1}
    assert result['status'] == status and result['credited_products'] == credit
    assert result['deadline_met'] == bool(credit)


def test_contact_start_is_wakeup_even_if_end_beyond_current_forecast():
    s = short_delivery_case(157)
    # At 110, second contact starts inside [110,160], but ends at 185.
    s = advance_campaign(s)
    view, _ = planning_boundary(s.context.inputs, s.program, s.memory)
    assert any(c.start_time_seconds == 155 and c.end_time_seconds > view.until_seconds for c in view.contacts)
    final, _ = run(s)
    assert [d.feedback.contact.start_time_seconds for d in final.memory.decisions if d.feedback.contact] == [140, 155]


def test_actual_initial_attitude_requires_positive_settling_wait():
    from ops_sim.v5.adcs import CommonFrameBoresightDirection
    s = build_demo_state(); p = s.program; old = p.initial_attitude.common_frame_boresight
    initial = replace(p.initial_attitude, common_frame_boresight=CommonFrameBoresightDirection(old.frame_id, 0.1, 0., 0.99498743710662))
    s = start_campaign(s.context.inputs, replace(p, initial_attitude=initial))
    first = plan(s).actions[0]
    assert first.kind == 'standby' and first.end_seconds > 100
    after = advance_campaign(s)
    assert plan(after).actions[0].kind == 'imaging'


def test_duplicate_requests_overlapping_contacts_and_incomplete_forcing_reject():
    s = build_demo_state(); p = s.program
    with pytest.raises(ValueError, match='duplicate'):
        replace(p, requests=(*p.requests, p.requests[0]))
    with pytest.raises(ValueError, match='overlap'):
        replace(p, contacts=(p.contacts[0], replace(p.contacts[1], start_time_seconds=170)))
    with pytest.raises(ValueError, match='consecutive'):
        replace(p, forcing=(replace(p.forcing[0], end_seconds=199), p.forcing[1]))


def test_partial_expired_retained_and_no_automatic_record_deletion():
    s = short_delivery_case(157)
    # Initially future capacity is unknown; product is acquired, first contact
    # serves ten of twelve Mbit. No contact exists to finish it.
    s = start_campaign(s.context.inputs, replace(s.program, contacts=s.program.contacts[:1]))
    final, reason = run(s)
    assert reason is None
    result = campaign_summary(final)['requests'][0]
    assert result['status'] == 'partial-expired' and result['credited_products'] == 0
    assert result['acquisitions'][0]['partial_bits'] == 10000000
    assert len(final.context.spacecraft_state.data_storage.stored_records) == 1


def test_public_planner_rejects_unreleased_inputs_and_excessive_visibility():
    s = build_demo_state()
    view, knowledge = planning_boundary(s.context.inputs, s.program, s.memory)
    with pytest.raises(ValueError, match='unreleased'):
        build_rolling_plan(replace(view, requests=s.program.requests), knowledge)
    with pytest.raises(ValueError, match='visibility'):
        build_rolling_plan(replace(view, until_seconds=1000), knowledge)


def test_declared_observation_fields_cannot_silently_expand():
    s = build_demo_state(denial=True)
    view, k = planning_boundary(s.context.inputs, s.program, s.memory)
    extra = view.knowledge_mode.estimated_temperatures
    f = replace(k.feedback, resources=replace(k.feedback.resources,
        observed_temperatures=(*k.feedback.resources.observed_temperatures, *extra)))
    with pytest.raises(ValueError, match='temperature fields'):
        build_rolling_plan(view, replace(k, feedback=f))


def test_changed_environment_is_applied_only_on_its_declared_interval():
    s = build_demo_state(); p = s.program; f = p.forcing[0]
    forcing = (replace(f, end_seconds=110, standby=replace(f.standby, sunlit=True)),
               replace(f, start_seconds=110, end_seconds=120))
    inputs = replace(s.context.inputs, common_world=replace(s.context.inputs.common_world, horizon_seconds=120))
    s = start_campaign(inputs, replace(p, requests=p.requests[:1], opportunities=(), contacts=(), forcing=forcing))
    lit = advance_campaign(s)
    dark = advance_campaign(lit)
    assert (lit.context.simulation_time_seconds, dark.context.simulation_time_seconds) == (110, 120)
    # Independent sign reference: retained generation 25*0.8 W > 12 W baseline,
    # while eclipse generation is zero. Battery starts below capacity.
    assert lit.context.spacecraft_state.battery.energy_wh > s.context.spacecraft_state.battery.energy_wh
    assert dark.context.spacecraft_state.battery.energy_wh < lit.context.spacecraft_state.battery.energy_wh


def test_imaging_is_never_shortened_to_a_forcing_edge():
    s = build_demo_state(); p = s.program; f = p.forcing[0]
    p = replace(p, forcing=(replace(f, end_seconds=105), replace(f, start_seconds=105), p.forcing[1]))
    s = start_campaign(s.context.inputs, p)
    first = plan(s)
    assert first.actions[0].kind == 'standby' and first.actions[0].end_seconds == 105
    assert ('op-a', 'atomic-imaging-crosses-forcing-boundary') in first.rejected
    next_plan = plan(advance_campaign(s))
    assert next_plan.actions[0].kind == 'imaging'
    assert next_plan.actions[0].end_seconds-next_plan.actions[0].start_seconds == 10
