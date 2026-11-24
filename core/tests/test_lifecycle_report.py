"""Strict compact-report accounting; shortened calendars are SYNTHETIC_UNIT.

These tests do not claim month physics. One 72-second HOLD uses the genuine
accepted EPS/thermal/construction leaves to exercise a real returned boundary;
all other fault/pressure checks are nonnumerical report fixtures.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
from types import SimpleNamespace
import json
import pytest

from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot, LifecyclePolicy, LifecycleScenario, MONTH
from ops_sim.v5.lifecycle_physics import (LifecycleActionOutcome, execute_lifecycle_action,
    LifecyclePhysicalModel, start_lifecycle_physical)
from ops_sim.v5.long_mission import LongMissionAction
from ops_sim.v5 import long_mission as leaf
from ops_sim.v5.assembly_attitude_3d import BodyAttitude3D
from ops_sim.v5.rolling_cache import PublicCacheBank, CumulativeWork
from ops_sim.v5.lifecycle_report import LifecycleReport, pack, unpack, _part


@pytest.fixture(scope='module')
def base(): return make_inputs()


def _root(base, *, duration=72, period=72):
    scenario = LifecycleScenario(cadence_seconds=120, acquisition_window_seconds=60,
        contact_offset_seconds=20, contact_duration_seconds=40, deadline_offset_seconds=72)
    return LifecycleRoot(base, duration, replace(LifecyclePolicy(), month_period_seconds=period),
                         scenario, 'BOUND_SHORT_TABLE_V1')


def _context(base): return base.initial_checkpoint.restore(base.model.simulation_inputs)


class _ShortSource:
    """Portable TEST ONLY adapter; no dependency on pytest's import mode."""
    def __init__(self, model, provider, source, work):
        self.source = source
        self.stub = SimpleNamespace(inputs=model, nominal_provider=provider, runtime_work=work)
    def guard(self): return self.source.guard()
    def schedule(self, a, b): return self.source.schedule(a, b)
    def observations(self, entry, a, b, sampling): return leaf._observations(self.stub, entry, a, b)
    def orientation_inputs(self, hardware, time, quaternion):
        return leaf._orientation_inputs(self.stub, hardware, time, quaternion)


def _physical_start(base):
    model = base.model; work = leaf.RuntimeWork()
    bank = PublicCacheBank(model, CumulativeWork(), base.quotas, 'ACTUAL_PUBLIC_MODEL')
    provider, source = bank.bind(work)
    pose = BodyAttitude3D(model.assembly.body_frame_id,
        model.environment.trajectory.initial_state.position.frame, Q(128), base.initial_quaternion, Q(128))
    return start_lifecycle_physical(LifecyclePhysicalModel(model, model.environment),
        _context(base), pose, tuple(r.product for r in base.requests), provider,
        _ShortSource(model, provider, source, work), runtime_work=work)


def _refusal(time=128):
    return LifecycleActionOutcome('SYNTHETIC_UNIT-refusal', 'CAPTURE', 'refused',
        'SYNTHETIC_UNIT-no-physical-call', time, time, (), (), (), None, None, None, None)


def test_rational_saved_values_and_initial_soc_are_exact(base):
    report = LifecycleReport(_root(base), _context(base))
    q = sum((Q(x) for x in (.1, .2, .3)), Q())
    assert unpack(pack(q)) == q
    summary = report.summary()
    assert summary['calendar'] == 'SYNTHETIC_UNIT_BUCKET_NOT_MONTH_PHYSICS'
    assert summary['totals']['minimum_soc'] == summary['totals']['end_soc']
    assert summary['totals']['end_soc'] is not None
    assert summary['totals']['priority_score_status'] == 'UNAVAILABLE_NO_OFFERS'


@pytest.mark.parametrize('weight', [True, -1., 0., float('nan'), float('inf'), 999.])
def test_offer_failure_is_atomic_and_weight_is_source_bound(base, weight):
    report = LifecycleReport(_root(base), _context(base)); before = deepcopy(report.state)
    with pytest.raises(ValueError): report.offer(0, weight)
    assert report.state == before


@pytest.mark.parametrize('mutation', ['unknown', 'counter_bool', 'end_before_start', 'bucket',
    'negative_bits', 'negative_temperature', 'mixed_nodes', 'bad_priority', 'bad_useful_bits',
    'soc', 'wear', 'transition_frontier', 'offer_frontier', 'sealed_count'])
def test_compact_report_state_semantics_reject_after_reencoding(base, mutation):
    root = _root(base); context = _context(base); report = LifecycleReport(root, context)
    report.offer(0, base.requests[root.scenario.request_index].product.request.priority_weight)
    state = json.loads(json.dumps(report.state)); row = state['current']
    if mutation == 'unknown': state['unreviewed'] = 1
    elif mutation == 'counter_bool': row['credits'] = True
    elif mutation == 'end_before_start': state['end_seconds'] = 1
    elif mutation == 'bucket': row['bucket'] += 1
    elif mutation == 'negative_bits': row['useful_bits'] = -1
    elif mutation == 'negative_temperature': row['maximum_temperature_k']['battery'] = -100.
    elif mutation == 'mixed_nodes': row['maximum_temperature_k']['other'] = 300.
    elif mutation == 'bad_priority': row['priority_denominator'] = pack(999)
    elif mutation == 'bad_useful_bits': row['useful_bits'] = 1
    elif mutation == 'soc': row['minimum_soc'] = 2.
    elif mutation == 'wear': row['wear_end']['solar_retention'] = 2.
    elif mutation == 'transition_frontier': state['next_transition'] = 9
    elif mutation == 'offer_frontier': state['offered_frontier'] = 0
    elif mutation == 'sealed_count': state['sealed_count'] = 1
    with pytest.raises(ValueError): LifecycleReport(root, context, state=state)
    assert report.state != state


def test_repeated_frontier_and_failed_consume_are_atomic(base):
    context = _context(base); report = LifecycleReport(_root(base), context)
    report.consume(_refusal(), context, 0)
    before = deepcopy(report.state)
    with pytest.raises(ValueError, match='frontier'): report.consume(_refusal(), context, 0)
    assert report.state == before
    with pytest.raises(ValueError): report.consume(_refusal(), context, 1, expired=1)
    assert report.state == before


def test_pressure_refusals_keep_bounded_state_without_history(base):
    context = _context(base); report = LifecycleReport(_root(base), context)
    first = len(json.dumps(report.state))
    for ordinal in range(256): report.consume(_refusal(), context, ordinal)
    last = len(json.dumps(report.state))
    assert report.state['next_transition'] == 256
    assert report.summary()['totals']['refused_actions'] == 256
    assert last-first < 100
    assert not {'seen_actions', 'seen_receipts', 'sealed_rows', 'decisions', 'forecasts'} & set(report.state)


def test_real_hold_boundary_expiry_then_zero_duration_terminal_event_tail(base):
    root = _root(base); physical = _physical_start(base); report = LifecycleReport(root, physical.context)
    weight = base.requests[root.scenario.request_index].product.request.priority_weight
    report.offer(0, weight)
    physical, outcome = execute_lifecycle_action(physical,
        LongMissionAction('report-boundary-hold', 'HOLD_UNTIL', until_seconds=200))
    assert outcome.status == 'completed'
    carry = report.consume(outcome, physical.context, 0, expired=1)
    assert not carry and report.state['pending_boundary_expired'] == 1
    assert report.summary()['totals']['expired'] == 0
    first = report.seal(physical.context, terminal=True, carry=carry)
    assert first['start_seconds'] == 128 and first['end_seconds'] == 200
    assert first['seal'] == 'MONTH_BOUNDARY' and first['expired'] == 0
    assert report.state['status'] == 'ACTIVE'
    last = report.seal(physical.context, terminal=True)
    assert last['start_seconds'] == last['end_seconds'] == 200
    assert last['seal'] == 'ENDPOINT_EVENT_TAIL' and last['expired'] == 1
    summary = report.summary()
    assert summary['status'] == 'COMPLETE' and summary['end_seconds'] == 200
    assert summary['totals']['expired'] == 1
    assert summary['totals']['physical_substeps'] == len(outcome.cuts)
    assert unpack(summary['totals']['sums']['throughput_wh']) == sum((Q(c.part.battery_degradation_result.throughput_increment_wh) for c in outcome.cuts), Q())


def test_window_global_frontiers_and_no_fabricated_elapsed_interval(base):
    root = _root(base, duration=360, period=72)
    context = _context(base); context.simulation_time_seconds = 248  # SYNTHETIC_UNIT data boundary only.
    report = LifecycleReport(root, context, window=True, offered_frontier=1, transition_frontier=87)
    assert report.state['next_transition'] == 87 and report.state['offer_base_frontier'] == 1
    assert report.summary()['start_seconds'] == report.summary()['end_seconds'] == 248
    assert report.summary()['totals']['offered'] == 0
    report.consume(_refusal(248), context, 87)
    report.offer(1, base.requests[root.scenario.request_index].product.request.priority_weight)
    assert report.summary()['totals']['offered'] == 1
    before = deepcopy(report.state)
    invalid = replace(_refusal(248), kind='HOLD_UNTIL', status='completed', reason=None, end_seconds=250)
    context.simulation_time_seconds = 250
    with pytest.raises(ValueError, match='lacks returned actual substeps'): report.consume(invalid, context, 88)
    assert report.state == before


def test_same_bucket_window_carry_in_union_and_unavailable_priority(base):
    root = _root(base, duration=360, period=MONTH)
    context = _context(base); context.simulation_time_seconds = 160
    report = LifecycleReport(root, context, window=True, offered_frontier=1)
    credit = dict(request_id=root.scenario.occurrence_id(0), record_ids=['SYNTHETIC_UNIT-record'],
        priority=float(report._expected_weight), useful_bits=report._expected_bits,
        completion_time=pack(160), released_at_seconds=128)
    # SYNTHETIC_UNIT bookkeeping only: direct fold tests the set-union rule,
    # not receipt provenance. Public consume additionally requires actual
    # returned completing service and actual completed custody.
    report._assign_credit(report.state['current'], credit, report.state)
    summary = report.summary()
    assert summary['totals']['offered'] == 0 and summary['totals']['credits'] == 1
    assert summary['totals']['carry_in_credits'] == 1
    assert summary['totals']['prior_bucket_credits'] == 0
    assert summary['totals']['nonlocal_offer_credits'] == 1
    assert summary['totals']['priority_score'] is None
    assert summary['totals']['priority_score_status'] == 'UNAVAILABLE_CARRY_IN_SCOPE'


def test_capacity_clip_uses_returned_authoritative_energy_and_loss(base):
    report = LifecycleReport(_root(base), _context(base)); row = deepcopy(report.state['current'])
    nodes = list(row['maximum_temperature_k'])
    # SYNTHETIC_UNIT returned-value fixture, not a physical calculation.
    battery = dict(dt_seconds=2., start_energy_wh=10., end_energy_wh=12., generation_w=4.,
        load_w=3., unmet_load_w=0., charge_input_w=1., discharge_output_w=0.,
        curtailed_generation_w=0., conversion_loss_wh=.25)
    physical = dict(eps_result=dict(battery=battery),
        battery_capacity_reconciliation_result=dict(authoritative_end_energy_wh=11.,
            unavailable_energy_wh=1., end_usable_capacity_wh=11.),
        eps_capability_result=dict(battery_usable_capacity_wh=20.),
        battery_degradation_result=dict(throughput_increment_wh=.5, calendar_damage=.001, cycling_damage=.002),
        solar_degradation_result=dict(retention_loss=.0001),
        thermal_coupling_result=dict(thermal_result=dict(node_transitions=[dict(node_id=dict(value=k),
            start_temperature_k=300., end_temperature_k=301.) for k in nodes]),
            node_heat_ledgers=[dict(internal_dissipation_w=1., absorbed_solar_w=2.,
                absorbed_albedo_w=0., absorbed_earth_ir_w=1.) for _ in nodes]))
    part = dict(physical=physical, electrical=dict(pv_wire_loss_w=.1, receiving_wire_loss_w=.2))
    _part(row, part)
    assert row['end_energy_wh'] == 11. and row['minimum_energy_wh'] == 10.
    assert unpack(row['sums']['capacity_clip_wh']) == 1
    assert unpack(row['sums']['generation_wh']) == Q(4.)*Q(2.)/3600
    assert unpack(row['sums']['wire_loss_wh']) == (Q(.1)+Q(.2))*Q(2.)/3600
    assert row['end_soc'] == 1. and row['physical_substeps'] == 1


def test_quiet_hold_observations_follow_declared_cadence_without_ack_burst(base):
    from ops_sim.v5.lifecycle_execution import start_lifecycle, step_lifecycle
    # This 240-second real quiet fixture intentionally has no complete offered
    # request window. It is a cadence regression, not a long mission result.
    root = LifecycleRoot(base, 240, sun_mode='BOUND_SHORT_TABLE_V1')
    assert root.offered_population == 0
    state = start_lifecycle(root); clocks = []; samples = set()
    for _ in range(8):
        if state.status != 'ACTIVE': break
        state, event, row = step_lifecycle(state)
        assert event['kind'] == 'HOLD_UNTIL'
        clocks.append(state.clock)
        samples.update(packet.observed_at_seconds for packet in state.queued)
    assert state.status == 'COMPLETE' and clocks == [188, 248, 288, 308, 368]
    assert samples == {248, 368}
    assert len(state.queued) == 1
    assert state.knowledge.observed_at_seconds == 248
    assert state.report.summary()['totals']['physical_substeps'] > 0
