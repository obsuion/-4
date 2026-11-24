"""Whole-arc references and independent bounded-search accounting checks.

Synthetic perturbations of the accepted B3 return value test orchestration
failure contracts; they are not evidence about the physical Sun or an event.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Inexact, localcontext
from fractions import Fraction as Q
import sys

import pytest

from examples.m2_interval_illumination_demo import example_request
from ops_sim.v5 import orbit_j2 as nominal
from ops_sim.v5 import orbit_j2_enclosure as enclosure
from ops_sim.v5 import orbit_j2_segments as segments
from ops_sim.v5 import orbit_sun_intervals as b3
from ops_sim.v5 import orbit_sun_windows as m
from ops_sim.v5.sun_table import SunPositionSample
from test_orbit_sun_intervals import independent_circle_ray_side, query, _iadd, _imul, _isquare
from test_j2_enclosure import trig_interval
from test_j2_segments import coast
from test_v56f1_j2_gravity_contracts import TextTrap, change_path, forge
from test_v56f2_j2_coast_contracts import trajectory


LIMITS = {
    'max_trials': 16,
    'max_integration_steps': 65536,
    'max_geometry_cells': 65536,
    'max_retained_evidence_units': 393216,
    'max_arithmetic_operations': 33562624,
}


def search_policy(**changes):
    values = dict(LIMITS, max_trials=8)
    values.update(changes)
    return m.IlluminationSearchPolicy(**values)


def request(kind='ambiguous', *, source=None, resolution=2**-20, **budgets):
    q = example_request(kind) if source is None else source
    return m.IlluminationWindowRequest(q.coast, q.table, q.start, q.end,
                                      resolution, search_policy(**budgets))


def evaluate(kind='ambiguous', **kwargs):
    return m.evaluate_illumination_windows(request(kind, **kwargs))


def max_connected_unresolved(cells):
    """Independent exact scan; different diagnostic reasons stay connected."""
    longest = Q(0)
    start = end = None
    for cell in cells:
        if cell.assessment == 'UNRESOLVED':
            if start is None or end != cell.start_seconds:
                start = cell.start_seconds
            end = cell.end_seconds
            longest = max(longest, end-start)
        else:
            start = end = None
    return longest


def assert_complete_supported_partition(result):
    assert result.coverage_complete and type(result.windows) is tuple
    windows = result.windows
    assert windows and windows[0].start_seconds == Q(result.request.start.elapsed_seconds)
    assert windows[-1].end_seconds == Q(result.request.end.elapsed_seconds)
    assert all(a.end_seconds == b.start_seconds for a, b in zip(windows, windows[1:]))
    assert all(type(w.start_seconds) is Q and type(w.end_seconds) is Q and
               w.start_seconds < w.end_seconds for w in windows)
    for window in windows:
        assert window.assessment in ('ILLUMINATED', 'OCCULTED', 'UNRESOLVED')
        assert type(window.reasons) is tuple and window.reasons
        assert type(window.supports) is tuple and window.supports
        coverage = []
        for support in window.supports:
            trial = result.trials[support.trial_index]
            cell = trial.evidence.cells[support.cell_index]
            assert support.trial_digest == trial.input_digest
            assert cell.start_seconds <= support.start_seconds < support.end_seconds <= cell.end_seconds
            assert window.start_seconds <= support.start_seconds < support.end_seconds <= window.end_seconds
            assert cell.assessment == window.assessment
            assert cell.reason in window.reasons
            coverage.append((support.start_seconds, support.end_seconds))
        # Supports may overlap when two trials certify the same atom. Their
        # union must still cover every point, without silently erasing a gap.
        covered = window.start_seconds
        for lo, hi in sorted(coverage):
            assert lo <= covered
            covered = max(covered, hi)
        assert covered == window.end_seconds
    assert result.max_unresolved_width_seconds == max_connected_unresolved(windows)
    assert result.all_spans_classified == all(w.assessment != 'UNRESOLVED' for w in windows)
    assert result.combined_qualification == 'UNRESOLVED'
    assert result.combined_reasons == b3.COMBINED_REASONS


def assert_accounting(result):
    trials = result.trials
    admitted = [t for t in trials if t.evidence is not None]
    for output, field in (
        ('reserved_integration_steps', 'reserved_integration_steps'),
        ('reserved_geometry_cells', 'reserved_geometry_cells'),
        ('reserved_arithmetic_operations', 'reserved_arithmetic_operations'),
        ('reserved_evidence_units', 'reserved_evidence_units'),
    ):
        assert getattr(result, output) == sum(getattr(t, field) for t in trials)
    assert result.planned_integration_steps_considered == sum(t.planned_integration_steps for t in trials)
    assert result.planned_geometry_cells_considered == sum(t.planned_geometry_cells or 0 for t in trials)
    assert result.completed_integration_steps == sum(
        t.evidence.j2_evidence.enclosure_steps for t in admitted if t.evidence.j2_evidence is not None)
    assert result.picard_attempts == sum(
        t.evidence.j2_evidence.picard_attempts for t in admitted if t.evidence.j2_evidence is not None)
    assert result.geometry_cells_evaluated == sum(t.evidence.geometry_cells_evaluated for t in admitted)
    assert result.arithmetic_operations == sum(t.evidence.arithmetic_operations for t in admitted)
    assert result.propagation_calls == sum(t.evidence.propagation_calls for t in admitted)
    assert result.completed_integration_steps <= result.reserved_integration_steps
    assert result.geometry_cells_evaluated <= result.reserved_geometry_cells
    assert result.arithmetic_operations <= result.reserved_arithmetic_operations
    for name in ('integration_steps', 'geometry_cells', 'arithmetic_operations', 'evidence_units'):
        policy_name = 'max_retained_evidence_units' if name == 'evidence_units' else 'max_'+name
        assert getattr(result, 'reserved_'+name) <= getattr(result.request.policy, policy_name)
    for t in trials:
        if t.reserved_evidence_units:
            geometry = t.planned_geometry_cells or 0
            assert t.reserved_evidence_units == t.planned_integration_steps+5*geometry
            assert t.reserved_arithmetic_operations == 512*(geometry+1)
    assert result.retained_evidence_units <= result.reserved_evidence_units


def retained_raw_cells(result):
    return sum(len(t.evidence.cells or ())+
               (len(t.evidence.j2_evidence.cells or ()) if t.evidence.j2_evidence is not None else 0)
               for t in result.trials if t.evidence is not None)


@pytest.mark.parametrize('kind,expected', [('illuminated', 'ILLUMINATED'), ('occulted', 'OCCULTED')])
def test_complete_analytic_j2_arc_has_one_supported_window(kind, expected):
    # Independent bounds for the exact R=2 equatorial circle, n=17/16,
    # on [0,1/32]. No point sampler or production quadratic is the oracle.
    angle = Q(17, 512)
    assert 1-angle**2/2 > Q(99, 100) and angle < Q(34, 1000)
    assert 198-Q(68, 1000)-4 > 0  # outward half ray, Sun x=+100
    assert (2+200*Q(34, 1000))**2 < (100+Q(198, 100))**2  # inward line distance <1
    result = evaluate(kind)
    assert result.status == 'classified' and len(result.trials) == 1
    assert len(result.windows) == 1 and result.windows[0].assessment == expected
    assert result.temporal_resolution_achieved and result.max_unresolved_width_seconds == 0
    assert_complete_supported_partition(result)
    assert_accounting(result)


def test_changing_sun_endpoints_do_not_hide_occulted_interior_or_prove_roots():
    assert independent_circle_ray_side(Q(0), Q(16)) == 'ILLUMINATED'
    assert independent_circle_ray_side(Q(1, 32), Q(-16)) == 'ILLUMINATED'
    assert independent_circle_ray_side(Q(1, 64), Q(0)) == 'OCCULTED'
    result = evaluate(resolution=1/256)
    assert result.status == 'resolution_reached', result.reason
    # The accepted width criterion can stop before the interior occultation
    # receives a certificate: this uncertainty span need not bracket one root.
    assert {w.assessment for w in result.windows} == {'ILLUMINATED', 'UNRESOLVED'}
    assert not result.all_spans_classified and result.temporal_resolution_achieved
    assert 0 < result.max_unresolved_width_seconds <= Q(1, 256)
    midpoint = Q(result.request.start.elapsed_seconds)+Q(1, 64)
    assert any(w.start_seconds <= midpoint <= w.end_seconds and w.assessment == 'UNRESOLVED'
               for w in result.windows)
    assert_complete_supported_partition(result)
    assert_accounting(result)
    # Uncertainty may conceal two transitions. Published data carry only
    # conditional classifications and supports, never inferred event roots.
    names = {f.name for f in fields(result)}
    assert not names.intersection({'events', 'roots', 'ingress_time', 'egress_time', 'event_accuracy'})


def test_tighter_genuine_refinement_certifies_entire_occulted_interior_arc():
    # Independent exact Taylor bounds for the WHOLE [15/1024,17/1024] arc.
    # cos decreases and sin increases; Sun sx=-1, sy=16-1024*t is affine.
    # A cross-product distance-to-line bound, with a forward closest point,
    # establishes occultation without production A,B,C,D or root samples.
    a, b = Q(15, 1024), Q(17, 1024)
    ca, cb = trig_interval(Q(17, 16)*a, False), trig_interval(Q(17, 16)*b, False)
    sa, sb = trig_interval(Q(17, 16)*a, True), trig_interval(Q(17, 16)*b, True)
    rx, ry = (2*cb[0], 2*ca[1]), (2*sa[0], 2*sb[1])
    sy = (16-1024*b, 16-1024*a)
    cross = _iadd(_imul(rx, sy), ry)
    dx, dy = (-1-rx[1], -1-rx[0]), (sy[0]-ry[1], sy[1]-ry[0])
    towards = _iadd(_imul(rx, (Q(-1), Q(-1))), _imul(ry, sy))
    assert towards[1]-4 < 0
    assert _isquare(cross)[1] < _iadd(_isquare(dx), _isquare(dy))[0]
    result = evaluate(resolution=1/512)
    assert result.status == 'resolution_reached', result.reason
    assert {w.assessment for w in result.windows} == {'ILLUMINATED', 'OCCULTED', 'UNRESOLVED'}
    occulted = [w for w in result.windows if w.assessment == 'OCCULTED']
    assert len(occulted) == 1
    anchor = Q(result.request.start.elapsed_seconds)
    assert occulted[0].start_seconds == anchor+a and occulted[0].end_seconds == anchor+b
    assert result.max_unresolved_width_seconds <= Q(1, 512)
    assert_complete_supported_partition(result)
    assert_accounting(result)


def test_real_step_refinement_improves_orbital_tube_and_uncertainty():
    q = request(resolution=1/256)
    before = deepcopy(q)
    result = m.evaluate_illumination_windows(q)
    assert len(result.trials) > 1 and q == before
    first, second = result.trials[:2]
    assert first.evidence.status == second.evidence.status == 'complete'
    assert Q(second.request.coast.enclosure_policy.step_seconds) == Q(first.request.coast.enclosure_policy.step_seconds)/2
    coarse = first.evidence.j2_evidence.cells[0]
    fine = second.evidence.j2_evidence.cells[0]
    assert coarse.start_seconds == fine.start_seconds
    assert fine.end_seconds < coarse.end_seconds
    assert sum(Q(hi)-Q(lo) for lo, hi in fine.position_bounds_m) < sum(
        Q(hi)-Q(lo) for lo, hi in coarse.position_bounds_m)
    assert result.max_unresolved_width_seconds < max_connected_unresolved(first.evidence.cells)
    assert_complete_supported_partition(result)


def test_original_physical_authority_and_anchor_survive_every_refinement(monkeypatch):
    original = b3.evaluate_interval_illumination
    calls = []
    def record(q):
        calls.append(q)
        return original(q)
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', record)
    q = request(resolution=1/512)
    result = m.evaluate_illumination_windows(q)
    assert len(calls) == len([t for t in result.trials if t.evidence is not None]) > 1
    initial = q.coast
    for index, call in enumerate(calls):
        assert call.coast.trajectory == initial.trajectory
        assert call.coast.solver_config == initial.solver_config
        assert call.table == q.table and call.start == q.start and call.end == q.end
        assert call.coast.enclosure_policy == replace(initial.enclosure_policy,
            step_seconds=float(Q(initial.enclosure_policy.step_seconds)/2**index))
        assert result.trials[index].request == call
    assert len({t.input_digest for t in result.trials}) == len(result.trials)
    assert_accounting(result)


@pytest.mark.parametrize('start,end', [(0, 1/8), (3/64, 9/64), (-9/64, -3/64), (-9/64, 7/64)])
@pytest.mark.parametrize('h', [1/32, .01])
def test_negative_cross_anchor_nonbinary_grid_and_unaligned_sun_knots(start, end, h):
    knots = sorted({start, end, start+(end-start)/4, (start+end)/2})
    base = query(start, end, h=h, knots=knots)
    result = evaluate(source=base)
    assert result.status == 'classified', result.reason
    assert_complete_supported_partition(result)
    assert_accounting(result)
    cells = result.trials[0].evidence.cells
    expected = {Q(base.start.elapsed_seconds), Q(base.end.elapsed_seconds)}
    expected.update(Q(s.elapsed_seconds) for s in base.table.samples)
    expected.update(t for c in result.trials[0].evidence.j2_evidence.cells for t in (c.start_seconds, c.end_seconds))
    assert [cells[0].start_seconds]+[c.end_seconds for c in cells] == sorted(expected)
    anchor = Q(base.coast.trajectory.initial_state.position.instant.elapsed_seconds)
    step = Q(base.coast.enclosure_policy.step_seconds)
    independent_steps = sum((abs(span)//step)+bool(abs(span)%step)
        for span in (min(Q(base.start.elapsed_seconds)-anchor, Q(0)),
                     max(Q(base.end.elapsed_seconds)-anchor, Q(0))) if span)
    assert result.completed_integration_steps == independent_steps
    if start > 0 or end < 0:
        assert result.completed_integration_steps > len(result.trials[0].evidence.j2_evidence.cells)


def test_affine_sun_domain_ambiguity_retains_reasons_not_event_classification():
    q = example_request('illuminated')
    table = replace(q.table, samples=(
        replace(q.table.samples[0], position_m=(0., 1., 0.)),
        replace(q.table.samples[-1], position_m=(0., -1., 0.))))
    result = evaluate(source=replace(q, table=table), resolution=1/512)
    assert_complete_supported_partition(result)
    assert any('SUN_VECTOR_NONZERO_NOT_ESTABLISHED' in w.reasons for w in result.windows)
    midpoint = Q(q.start.elapsed_seconds)+Q(q.end.elapsed_seconds-q.start.elapsed_seconds)/2
    assert any(w.start_seconds <= midpoint <= w.end_seconds and w.assessment == 'UNRESOLVED'
               for w in result.windows)
    assert not result.all_spans_classified and result.combined_qualification == 'UNRESOLVED'


def test_closed_earth_tangency_remains_uncertainty_at_shared_initial_endpoint():
    # Independent exact initial ray r=(2,1,0), s=(1,1,0): d=(-1,0,0),
    # closest forward point=(0,1,0), so contact with the unit sphere is
    # occulted under the declared closed-Earth rule. No root finder is used.
    r, d = (Q(2), Q(1), Q(0)), (Q(-1), Q(0), Q(0))
    lam = -sum(a*b for a, b in zip(r, d))/sum(x*x for x in d)
    assert lam == 2 and sum((a+lam*b)**2 for a, b in zip(r, d)) == 1
    q = query(0, 1/32)
    anchor = q.start.elapsed_seconds
    c = coast(trajectory(r=(2, 1, 0), v=(0, 0, 0), t0=anchor, j2=0))
    table = replace(q.table, samples=(SunPositionSample(anchor, (1., 1., 0.)),
                                      SunPositionSample(q.end.elapsed_seconds, (1., 1., 0.))))
    result = evaluate(source=replace(q, coast=c, table=table), resolution=1/1024)
    assert_complete_supported_partition(result)
    assert result.windows[0].assessment == 'UNRESOLVED'
    assert result.windows[0].start_seconds == Q(anchor)
    assert any('SHADOW_BOUNDARY_OR_DEPENDENCY_AMBIGUITY' in w.reasons for w in result.windows)
    assert not result.all_spans_classified and result.combined_qualification == 'UNRESOLVED'


def _cell_variants(evidence, assessments, reasons=None):
    reasons = reasons or tuple('controlled '+str(i) for i in range(len(evidence.cells)))
    cells = tuple(replace(cell, assessment=a, reason=r)
                  for cell, a, r in zip(evidence.cells, assessments, reasons))
    assert len(cells) == len(evidence.cells)
    return forge(evidence, cells=cells, all_cells_classified=all(a != 'UNRESOLVED' for a in assessments))


def test_resolution_uses_connected_unknown_span_even_across_reason_boundaries(monkeypatch):
    original = b3.evaluate_interval_illumination
    def unresolved(q):
        evidence = original(q)
        return _cell_variants(evidence, ['UNRESOLVED']*len(evidence.cells))
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', unresolved)
    result = evaluate(source=query(0, 3/32), resolution=1/32, max_trials=1)
    assert result.status == 'budget_exhausted'
    assert not result.temporal_resolution_achieved and result.max_unresolved_width_seconds == Q(3, 32)
    assert_complete_supported_partition(result)


def test_later_ambiguity_does_not_downgrade_prior_certified_coverage(monkeypatch):
    original = b3.evaluate_interval_illumination
    calls = []
    def controlled(q):
        evidence = original(q)
        calls.append(evidence)
        classes = ['UNRESOLVED']*len(evidence.cells)
        if len(calls) == 1:
            classes[0] = 'ILLUMINATED'
        return _cell_variants(evidence, classes)
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', controlled)
    result = evaluate(source=query(0, 1/16), max_trials=2)
    assert result.status == 'budget_exhausted' and len(calls) == 2
    assert_complete_supported_partition(result)
    first = result.windows[0]
    assert first.assessment == 'ILLUMINATED'
    assert first.end_seconds == Q(result.request.start.elapsed_seconds)+Q(1, 32)
    assert all(s.trial_index == 0 for s in first.supports)


@pytest.mark.parametrize('start,end,steps', [
    (3/64, 9/64, (5, 9)), (-3/64, 7/64, (6, 10)),
])
def test_cumulative_refinement_counts_both_signed_legs_and_all_prefixes(monkeypatch, start, end, steps):
    original = b3.evaluate_interval_illumination
    def uncertain(q):
        evidence = original(q)
        return _cell_variants(evidence, ['UNRESOLVED']*len(evidence.cells))
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', uncertain)
    result = evaluate(source=query(start, end), max_trials=2)
    assert result.status == 'budget_exhausted'
    assert tuple(t.planned_integration_steps for t in result.trials) == steps
    assert tuple(t.evidence.j2_evidence.enclosure_steps for t in result.trials) == steps
    assert result.completed_integration_steps == result.reserved_integration_steps == sum(steps)
    assert_complete_supported_partition(result)
    assert_accounting(result)


@pytest.mark.parametrize('endpoint_only', [False, True])
def test_opposing_certifications_including_shared_closed_endpoint_fail_atomically(monkeypatch, endpoint_only):
    original = b3.evaluate_interval_illumination
    calls = []
    def contradictory(q):
        evidence = original(q)
        calls.append(evidence)
        classes = ['UNRESOLVED']*len(evidence.cells)
        if endpoint_only:
            classes[:2] = ['ILLUMINATED', 'OCCULTED']
        elif len(calls) == 1:
            classes[0] = 'ILLUMINATED'
        else:
            classes[0] = 'OCCULTED'
        return _cell_variants(evidence, classes)
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', contradictory)
    result = evaluate(source=query(0, 1/16), max_trials=2)
    assert result.status == 'computational_failure' and not result.coverage_complete
    assert result.windows is None and result.reason
    assert len(result.trials) == (1 if endpoint_only else 2)
    assert result.combined_qualification == 'UNRESOLVED'


@pytest.mark.parametrize('budget,value', [
    ('max_integration_steps', 3), ('max_geometry_cells', 3),
    ('max_retained_evidence_units', 18), ('max_arithmetic_operations', 2560),
])
def test_global_budget_spans_multiple_complete_trials_and_blocked_attempt(monkeypatch, budget, value):
    calls = []
    original = b3.evaluate_interval_illumination
    def record(q):
        calls.append(q)
        return original(q)
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', record)
    result = evaluate(**{budget: value})
    assert result.status == 'budget_exhausted' and len(calls) == 2
    assert len(result.trials) == 3 and result.trials[-1].evidence is None
    blocked = result.trials[-1]
    assert blocked.planned_integration_steps == 4 and blocked.planned_geometry_cells == 4
    assert blocked.reserved_integration_steps == blocked.reserved_geometry_cells == 0
    assert blocked.reserved_arithmetic_operations == blocked.reserved_evidence_units == 0
    assert_complete_supported_partition(result)
    assert_accounting(result)


@pytest.mark.parametrize('budget', ['max_integration_steps', 'max_geometry_cells',
                                  'max_retained_evidence_units', 'max_arithmetic_operations'])
def test_initial_preflight_budget_failure_has_no_windows_and_no_upstream_call(monkeypatch, budget):
    def forbidden(*args):
        raise AssertionError('propagation before global admission')
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', forbidden)
    result = evaluate(source=query(0, 1/16), **{budget: 1})
    assert result.status == 'budget_exhausted' and result.windows is None
    assert not result.coverage_complete and result.propagation_calls == 0
    assert result.completed_integration_steps == result.geometry_cells_evaluated == 0
    assert result.reserved_integration_steps == result.reserved_geometry_cells == 0
    assert len(result.trials) == 1 and result.trials[0].evidence is None
    assert result.max_unresolved_width_seconds is None
    assert_accounting(result)


def test_trial_ceiling_preserves_last_complete_uncertain_partition():
    result = evaluate(max_trials=2)
    assert result.status == 'budget_exhausted'
    assert len(result.trials) == 2 and result.propagation_calls == 2
    assert_complete_supported_partition(result)
    assert not result.temporal_resolution_achieved
    assert_accounting(result)


def test_minimum_accepted_enclosure_step_stops_explicitly_without_reanchoring():
    q = example_request('ambiguous')
    h = 2**-20
    start = q.start.elapsed_seconds
    table = replace(q.table, domain_seconds=(start, start+h), samples=(
        SunPositionSample(start, (-1., 16., 0.)), SunPositionSample(start+h, (-1., -16., 0.))))
    source = replace(q, table=table, end=replace(q.end, elapsed_seconds=start+h),
        coast=replace(q.coast, enclosure_policy=replace(q.coast.enclosure_policy, step_seconds=h)))
    result = evaluate(source=source, resolution=h/4)
    assert result.status == 'numerical_limit' and result.reason
    assert result.propagation_calls == 1 and not result.temporal_resolution_achieved
    assert_complete_supported_partition(result)
    assert result.max_unresolved_width_seconds == Q(h)


@pytest.mark.parametrize('kind', ['upstream-failure', 'illuminated'])
def test_upstream_failure_has_no_nominal_fallback_and_preserves_actual_counts(monkeypatch, kind):
    def forbidden(*args):
        raise AssertionError('nominal propagation used in conditional proof')
    monkeypatch.setattr(nominal, 'evaluate_j2_cartesian_state', forbidden)
    q = example_request(kind)
    if kind == 'illuminated':
        q = replace(q, coast=replace(q.coast, enclosure_policy=replace(q.coast.enclosure_policy, max_picard_iterations=1)))
    result = evaluate(source=q)
    assert result.status == 'computational_failure' and result.windows is None
    assert not result.coverage_complete and result.propagation_calls == 1
    assert len(result.trials) == 1 and result.trials[0].evidence.status == 'unresolved'
    assert result.trials[0].evidence.j2_evidence.reason in result.reason
    assert_accounting(result)


def test_late_refinement_geometry_failure_discards_partition_without_erasing_work(monkeypatch):
    original = b3._geometry
    calls = []
    def second_fails(*args):
        calls.append(1)
        if len(calls) == 2:
            raise b3._WorkFailure('controlled second-trial geometry failure')
        return original(*args)
    monkeypatch.setattr(b3, '_geometry', second_fails)
    result = evaluate()
    assert result.status == 'computational_failure' and result.windows is None
    assert not result.coverage_complete and len(result.trials) == 2
    assert result.trials[0].evidence.status == 'complete'
    assert result.trials[1].evidence.status == 'unresolved'
    assert result.completed_integration_steps == 3 and result.geometry_cells_evaluated == 1
    assert result.propagation_calls == 2 and 'controlled second-trial' in result.reason
    assert result.retained_evidence_units == retained_raw_cells(result) == 4
    assert_accounting(result)


def test_late_second_leg_failure_counts_completed_prefix_and_publishes_no_partition(monkeypatch):
    original = enclosure._step_with_tube
    original_b3 = b3.evaluate_interval_illumination
    calls = []
    def fifth_fails(*args):
        calls.append(1)
        if len(calls) == 5:
            raise enclosure._Unresolved('controlled refined second-leg integration failure')
        return original(*args)
    def uncertain(q):
        evidence = original_b3(q)
        if evidence.status == 'complete':
            return _cell_variants(evidence, ['UNRESOLVED']*len(evidence.cells))
        return evidence
    monkeypatch.setattr(enclosure, '_step_with_tube', fifth_fails)
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', uncertain)
    result = evaluate(source=query(-1/32, 1/32))
    assert result.status == 'computational_failure' and result.windows is None
    assert len(result.trials) == 2 and len(calls) == 5
    # Initial coarse trial: one negative and one positive step. Fine trial:
    # two negative steps complete; its first positive attempt fails atomically.
    assert result.completed_integration_steps == 4 and result.propagation_calls == 2
    assert result.trials[1].evidence.j2_evidence.cells is None
    assert 'controlled refined second-leg' in result.reason
    assert result.retained_evidence_units == retained_raw_cells(result) == 4
    assert_accounting(result)


def test_late_uncounted_upstream_exception_retains_reservation_and_honest_lower_bounds(monkeypatch):
    original = b3.evaluate_interval_illumination
    calls = []
    def second_raises(q):
        calls.append(q)
        if len(calls) == 2:
            raise OverflowError('controlled upstream exception without returned counters')
        return original(q)
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', second_raises)
    result = evaluate()
    assert result.status == 'computational_failure' and result.windows is None
    assert not result.coverage_complete and len(result.trials) == len(calls) == 2
    failed = result.trials[-1]
    assert failed.status == 'exception_failed' and failed.evidence is None
    assert failed.reserved_integration_steps == 2 and failed.reserved_geometry_cells == 2
    assert result.reserved_integration_steps == 3 and result.completed_integration_steps == 1
    assert result.b3_evaluation_calls == 2 and result.propagation_calls == 1
    assert result.actual_work_accounting_complete is False
    assert result.reserved_picard_attempts == 3*result.request.coast.enclosure_policy.max_picard_iterations
    assert result.retained_evidence_units == retained_raw_cells(result) == 2
    assert 'controlled upstream exception' in result.reason
    assert_accounting(result)


def test_one_b3_and_one_b2_call_per_admitted_trial_without_second_propagation(monkeypatch):
    b3_original, b2_original = b3.evaluate_interval_illumination, segments.evaluate_j2_segments
    b3_calls, b2_calls = [], []
    def once_b3(q):
        b3_calls.append(q)
        return b3_original(q)
    def once_b2(q):
        b2_calls.append(q)
        return b2_original(q)
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', once_b3)
    monkeypatch.setattr(segments, 'evaluate_j2_segments', once_b2)
    result = evaluate(resolution=1/256)
    assert len(b3_calls) == len(b2_calls) == result.propagation_calls > 1
    assert all(a.coast == b.coast and a.start == b.start and a.end == b.end
               for a, b in zip(b3_calls, b2_calls))
    assert_accounting(result)


@pytest.mark.parametrize('field,maximum', list(LIMITS.items()))
@pytest.mark.parametrize('which', ['zero', 'above', 'bool', 'float', 'text', 'none', 'subclass'])
def test_strict_finite_policy_rejects_invalid_counts(field, maximum, which):
    class IntSubclass(int):
        pass
    invalid = {'zero': 0, 'above': maximum+1, 'bool': True, 'float': 1.,
               'text': '1', 'none': None, 'subclass': IntSubclass(1)}[which]
    with pytest.raises((TypeError, ValueError)):
        search_policy(**{field: invalid})


@pytest.mark.parametrize('resolution', [True, 0, -1, float('inf'), float('-inf'), float('nan'),
                                     '1', None, Q(1, 32), 2**41+1])
def test_strict_positive_bounded_resolution(resolution):
    with pytest.raises((TypeError, ValueError)):
        request(resolution=resolution)


@pytest.mark.parametrize('which', ['epoch', 'frame', 'reversed', 'domain', 'forged-time',
                                 'forged-policy', 'forged-model', 'forged-table', 'forged-provenance'])
def test_nested_invalid_requests_rejected_before_any_evaluation(monkeypatch, which):
    def forbidden(*args):
        raise AssertionError('evaluation of invalid reconstructed input')
    monkeypatch.setattr(b3, 'evaluate_interval_illumination', forbidden)
    q = request()
    if which == 'epoch':
        q = change_path(q, 'end.epoch.julian_day', 2451546)
    elif which == 'frame':
        q = change_path(q, 'table.frame.rotation.initial_phase_rad.value', .5)
    elif which == 'reversed':
        q = forge(q, end=q.start)
    elif which == 'domain':
        q = change_path(q, 'end.elapsed_seconds', 129.)
    elif which == 'forged-time':
        q = change_path(q, 'start.elapsed_seconds', True)
    elif which == 'forged-policy':
        q = change_path(q, 'policy.max_trials', True)
    elif which == 'forged-model':
        q = change_path(q, 'coast.policy_version', True)
    elif which == 'forged-table':
        q = change_path(q, 'table.interpolation', TextTrap('LINEAR_POSITION_V1'))
    else:
        q = change_path(q, 'table.provenance.accuracy_policy', 'ZERO_ERROR')
    with pytest.raises((TypeError, ValueError)):
        m.evaluate_illumination_windows(q)


def test_frozen_results_recompute_forged_fields_and_ignore_hostile_decimal_context():
    q = request('illuminated')
    result = m.evaluate_illumination_windows(q)
    for obj, name in ((result, 'status'), (result.request, 'start'),
                      (result.request.policy, 'max_trials'), (result.windows[0], 'assessment'),
                      (result.trials[0], 'index'), (result.windows[0].supports[0], 'trial_index')):
        assert not hasattr(obj, '__dict__')
        with pytest.raises(FrozenInstanceError):
            setattr(obj, name, None)
    assert [f.name for f in fields(result) if f.init] == ['request']
    assert replace(result) == result
    poisoned = forge(result, status='classified', windows=(), combined_qualification='QUALIFIED',
                     completed_integration_steps=999, propagation_calls=0)
    assert replace(poisoned) == result
    with localcontext() as context:
        context.prec = 2
        context.Emin, context.Emax = -4, 4
        context.traps[Inexact] = True
        assert m.evaluate_illumination_windows(q) == result
    assert 'ops_sim.v5.scenario_inputs' not in sys.modules


def test_order_independent_repeatability_and_external_inputs_remain_unqualified():
    qs = [request(kind) for kind in ('illuminated', 'occulted', 'external')]
    results = [m.evaluate_illumination_windows(q) for q in qs]
    assert results == list(reversed([m.evaluate_illumination_windows(q) for q in reversed(qs)]))
    assert results[-1].request.table.provenance.source_kind == 'HORIZONS'
    assert all(r.combined_qualification == 'UNRESOLVED' for r in results)
    assert 'FRAME_ALIGNMENT_ERROR_UNQUANTIFIED' in results[-1].combined_reasons
