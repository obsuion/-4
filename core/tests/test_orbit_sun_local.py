"""Independent complete-arc composition and bounded local-proof contracts.

Analytic circular references bound every time in a source step. Synthetic
certificate mutations test integrity/atomicity only, never physical truth.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal, DecimalException, Inexact, localcontext
from fractions import Fraction as Q
import sys

import pytest

from examples.m2_interval_illumination_demo import example_request
from ops_sim.v5 import orbit_j2 as nominal
from ops_sim.v5 import orbit_j2_enclosure as enclosure
from ops_sim.v5 import orbit_j2_segments as segments
from ops_sim.v5 import orbit_sun_intervals as b3
from ops_sim.v5 import orbit_sun_local as m
from ops_sim.v5.sun_table import SunPositionSample
from test_j2_enclosure import scale, trig_interval
from test_j2_segments import circular_arc_reference, coast
from test_orbit_sun_intervals import query, _iadd, _imul, _isquare
from test_v56f1_j2_gravity_contracts import TextTrap, change_path, forge
from test_v56f2_j2_coast_contracts import trajectory


LIMITS = {
    'max_passes': 16, 'max_integration_steps': 65536,
    'max_picard_attempts': 1048576, 'max_geometry_cells': 65536,
    'max_retained_evidence_units': 393216, 'max_arithmetic_operations': 33562624,
}


def policy(**changes):
    values = dict(LIMITS, max_passes=7)
    values.update(changes)
    return m.LocalIlluminationPolicy(**values)


def request(kind='ambiguous', *, source=None, resolution=1/1024, **budgets):
    q = example_request(kind) if source is None else source
    return m.LocalIlluminationRequest(q.coast, q.table, q.start, q.end,
                                      resolution, policy(**budgets))


def evaluate(kind='ambiguous', **kwargs):
    return m.evaluate_local_illumination(request(kind, **kwargs))


def _contains(actual, reference):
    assert len(actual) == len(reference) == 6
    for pair, (lo, hi) in zip(actual, reference):
        assert type(pair) is tuple and len(pair) == 2
        assert all(type(x) is Decimal and x.is_finite() for x in pair)
        assert Q(pair[0]) <= lo <= hi <= Q(pair[1])


def _circle_endpoint(t, nonzero=True):
    n = Q(17, 16) if nonzero else Q(1)
    s, c = trig_interval(n*t, True), trig_interval(n*t, False)
    zero = (Q(0), Q(0))
    return scale(c, 2), scale(s, 2), zero, scale(s, -2*n), scale(c, 2*n), zero


def assert_analytic_graph(result, *, nonzero=True):
    """Complete continuous arcs, independent of production Taylor dynamics."""
    anchor = Q(result.request.coast.trajectory.initial_state.position.instant.elapsed_seconds)
    assert len(result.boundaries) == len(result.steps)+1
    root = result.boundaries[0]
    assert root.id == 0 and root.elapsed_seconds == anchor
    assert root.parent_step_id is None and root.direction == 0
    for boundary in result.boundaries:
        assert result.boundaries[boundary.id] is boundary
        assert boundary.common_authority_digest == result.common_authority_digest
        assert type(boundary.elapsed_seconds) is Q
        _contains(boundary.state_bounds, _circle_endpoint(boundary.elapsed_seconds-anchor, nonzero))
        if boundary.parent_step_id is not None:
            parent = result.steps[boundary.parent_step_id]
            assert parent.endpoint_boundary_id == boundary.id
            assert parent.tube.source_final_seconds == boundary.elapsed_seconds
    for step in result.steps:
        parent = result.boundaries[step.parent_boundary_id]
        endpoint = result.boundaries[step.endpoint_boundary_id]
        assert step.id == endpoint.parent_step_id
        assert parent.id < endpoint.id
        assert step.tube.source_initial_seconds == parent.elapsed_seconds
        assert step.tube.source_final_seconds == endpoint.elapsed_seconds
        sign = 1 if endpoint.elapsed_seconds > parent.elapsed_seconds else -1
        assert endpoint.direction == sign and parent.direction in (0, sign)
        assert abs(endpoint.elapsed_seconds-parent.elapsed_seconds) <= Q(step.enclosure_policy.step_seconds)
        a, b = sorted((parent.elapsed_seconds-anchor, endpoint.elapsed_seconds-anchor))
        _contains(step.tube.position_bounds_m+step.tube.velocity_bounds_m_per_s,
                  circular_arc_reference(a, b, nonzero))


def _max_unknown(windows):
    longest = Q(0)
    start = None
    for w in windows:
        if w.assessment == 'UNRESOLVED':
            if start is None:
                start = w.start_seconds
            longest = max(longest, w.end_seconds-start)
        else:
            start = None
    return longest


def assert_partition(result):
    assert result.coverage_complete and type(result.windows) is tuple and result.windows
    ws = result.windows
    assert ws[0].start_seconds == Q(result.request.start.elapsed_seconds)
    assert ws[-1].end_seconds == Q(result.request.end.elapsed_seconds)
    assert all(a.end_seconds == b.start_seconds for a, b in zip(ws, ws[1:]))
    for w in ws:
        assert type(w.start_seconds) is Q and type(w.end_seconds) is Q
        assert w.start_seconds < w.end_seconds
        assert w.assessment in ('ILLUMINATED', 'OCCULTED', 'UNRESOLVED')
        assert w.endpoint_convention == 'LEFT_CLOSED_RIGHT_OPEN_FINAL_END_INCLUDED'
        covered = w.start_seconds
        for s in sorted(w.supports, key=lambda s: s.start_seconds):
            record = result.geometry_records[s.geometry_record_id]
            cell = record.cell
            assert record.common_authority_digest == result.common_authority_digest
            assert cell.start_seconds <= s.start_seconds < s.end_seconds <= cell.end_seconds
            assert w.start_seconds <= s.start_seconds < s.end_seconds <= w.end_seconds
            assert cell.assessment == w.assessment and cell.reason in w.reasons
            assert s.start_seconds <= covered
            covered = max(covered, s.end_seconds)
            step = result.steps[record.step_id]
            assert cell.j2_cell_index == step.id
            assert step.tube.start_seconds <= cell.start_seconds < cell.end_seconds <= step.tube.end_seconds
            assert cell.position_bounds_m == tuple((Q(a), Q(b)) for a, b in step.tube.position_bounds_m)
            left, right = result.request.table.samples[cell.sun_segment_index:cell.sun_segment_index+2]
            assert Q(left.elapsed_seconds) <= cell.start_seconds < cell.end_seconds <= Q(right.elapsed_seconds)
        assert covered == w.end_seconds
    assert result.max_unresolved_width_seconds == _max_unknown(ws)
    assert result.all_spans_classified == (_max_unknown(ws) == 0)
    assert result.temporal_resolution_achieved == (_max_unknown(ws) <= Q(result.request.requested_resolution_seconds))
    assert result.combined_qualification == 'UNRESOLVED'
    assert result.combined_reasons == b3.COMBINED_REASONS


def assert_accounting(result):
    for name in ('reserved_integration_steps', 'reserved_picard_attempts', 'reserved_geometry_cells',
                 'reserved_arithmetic_operations', 'reserved_evidence_units',
                 'attempted_integration_steps', 'completed_integration_steps', 'picard_attempts',
                 'geometry_cells_attempted', 'geometry_cells_evaluated', 'arithmetic_operations',
                 'reused_boundary_records', 'reused_certificate_pieces'):
        assert getattr(result, name) == sum(getattr(p, name) for p in result.passes)
    assert result.completed_integration_steps == len(result.steps)
    assert result.geometry_cells_evaluated == len(result.geometry_records)
    assert result.completed_integration_steps <= result.attempted_integration_steps <= result.reserved_integration_steps
    assert result.picard_attempts <= result.reserved_picard_attempts <= result.request.policy.max_picard_attempts
    assert result.geometry_cells_evaluated <= result.geometry_cells_attempted <= result.reserved_geometry_cells
    assert result.arithmetic_operations <= result.reserved_arithmetic_operations <= result.request.policy.max_arithmetic_operations
    assert result.retained_evidence_units <= result.reserved_evidence_units <= result.request.policy.max_retained_evidence_units
    assert result.reserved_integration_steps <= result.request.policy.max_integration_steps
    assert result.reserved_geometry_cells <= result.request.policy.max_geometry_cells
    for p in result.passes:
        if p.status != 'rejected_plan':
            assert p.reserved_evidence_units == 12*p.planned_integration_steps+24*p.planned_geometry_cells+16
            assert p.reserved_picard_attempts == p.planned_integration_steps*result.request.coast.enclosure_policy.max_picard_iterations
            assert p.reserved_arithmetic_operations == 512*(1+p.planned_geometry_cells)
        else:
            assert p.reserved_integration_steps == p.reserved_picard_attempts == p.reserved_geometry_cells == 0
        assert all(result.geometry_records[i].pass_index == p.index for i in p.geometry_record_ids)


@pytest.mark.parametrize('nonzero', [False, True], ids=['central', 'J2'])
@pytest.mark.parametrize('start,end', [(3/64, 9/64), (-9/64, -3/64), (-9/64, 7/64)])
@pytest.mark.parametrize('anchor', [0, 32.125])
def test_complete_analytic_composed_arcs_both_directions_and_counted_prefix(nonzero, start, end, anchor):
    q = query(start, end, t0=anchor, knots=(start, (start+end)/2, end))
    c = coast(trajectory(v=(0, 17/8 if nonzero else 2, 0), j2=11/32 if nonzero else 0, t0=anchor))
    r = evaluate(source=replace(q, coast=c))
    assert r.status == 'classified', r.reason
    assert_analytic_graph(r, nonzero=nonzero)
    assert_partition(r)
    assert_accounting(r)
    h = Q(c.enclosure_policy.step_seconds)
    spans = (min(Q(start), Q(0)), max(Q(end), Q(0)))
    expected = sum(abs(s)//h+bool(abs(s)%h) for s in spans if s)
    assert r.completed_integration_steps == expected
    if start > 0 or end < 0:
        assert r.completed_integration_steps > len(r.geometry_records)


@pytest.mark.parametrize('kind,classification', [('illuminated', 'ILLUMINATED'), ('occulted', 'OCCULTED')])
def test_short_complete_ray_arc_has_independent_geometric_reference(kind, classification):
    # Exact R=2 equatorial J2 circle: cos(nt)>.99, |sin(nt)|<.034.
    # For sx=100 r.s-r.r>0; for sx=-100, inward cross/ray norm <1.
    angle = Q(17, 512)
    assert 1-angle**2/2 > Q(99, 100) and angle < Q(34, 1000)
    assert 198-Q(68, 1000)-4 > 0
    assert (2+200*Q(34, 1000))**2 < (100+Q(198, 100))**2
    r = evaluate(kind)
    assert r.status == 'classified' and len(r.passes) == 1
    assert len(r.windows) == 1 and r.windows[0].assessment == classification
    assert_partition(r); assert_analytic_graph(r); assert_accounting(r)


def test_one_initial_pass_captures_all_endpoints_without_duplicate_or_nominal_propagation(monkeypatch):
    calls = []
    original = enclosure._step_with_tube
    def record(box, h, model, p, ar):
        answer = original(box, h, model, p, ar)
        calls.append((tuple((x.lo, x.hi) for x in box), tuple((x.lo, x.hi) for x in answer[0])))
        return answer
    def forbidden(*args, **kwargs):
        raise AssertionError('nominal or second public propagation was entered')
    monkeypatch.setattr(enclosure, '_step_with_tube', record)
    monkeypatch.setattr(nominal, 'evaluate_j2_cartesian_state', forbidden)
    monkeypatch.setattr(segments, 'evaluate_j2_segments', forbidden)
    r = evaluate(source=query(3/64, 9/64))
    assert r.status == 'classified'
    assert len(calls) == r.completed_integration_steps == 5
    for step, (supplied, endpoint) in zip(r.steps, calls):
        assert supplied == r.boundaries[step.parent_boundary_id].state_bounds
        assert endpoint == r.boundaries[step.endpoint_boundary_id].state_bounds
    assert any(lo < hi for lo, hi in calls[1][0])
    assert_analytic_graph(r); assert_accounting(r)


def test_initial_geometry_matches_unchanged_b3_and_work_counts():
    q = example_request('ambiguous')
    old = b3.evaluate_interval_illumination(q)
    r = evaluate(source=q, max_passes=1)
    assert r.coverage_complete and len(r.passes) == 1
    assert tuple(g.cell for g in r.geometry_records) == old.cells
    assert r.completed_integration_steps == old.j2_evidence.enclosure_steps
    assert r.picard_attempts == old.j2_evidence.picard_attempts
    assert r.geometry_cells_evaluated == old.geometry_cells_evaluated
    assert r.arithmetic_operations == old.arithmetic_operations
    assert_partition(r); assert_accounting(r)


def test_multiple_local_levels_are_genuine_validated_work_with_original_authority(monkeypatch):
    q = request(resolution=1/512)
    before = deepcopy(q)
    supplied = []
    original = enclosure._step_with_tube
    def record(box, h, *args):
        supplied.append(tuple((x.lo, x.hi) for x in box))
        return original(box, h, *args)
    monkeypatch.setattr(enclosure, '_step_with_tube', record)
    r = m.evaluate_local_illumination(q)
    assert q == before and r.coverage_complete
    assert len(r.passes) > 1 and r.reused_boundary_records > 0
    assert len(supplied) == r.completed_integration_steps
    for step, box in zip(r.steps, supplied):
        assert box == r.boundaries[step.parent_boundary_id].state_bounds
        assert step.enclosure_policy == replace(q.coast.enclosure_policy,
            step_seconds=float(Q(q.coast.enclosure_policy.step_seconds)/2**step.pass_index))
    assert any(s.pass_index > 0 for s in r.steps)
    assert_analytic_graph(r); assert_partition(r); assert_accounting(r)
    first = tuple(r.geometry_records[i].cell for i in r.passes[0].geometry_record_ids)
    assert r.max_unresolved_width_seconds < _max_unknown(first)


def test_full_interior_occulted_arc_independent_cross_product_reference():
    # Whole closed [15/1024,17/1024] reference, not endpoint samples.
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
    r = evaluate(resolution=1/512)
    assert_partition(r); assert_analytic_graph(r)
    anchor = Q(r.request.start.elapsed_seconds)
    # B6 may split the reference arc differently from global B4; require
    # genuinely supported occulted overlap, without assuming equal partitions.
    covered = anchor+a
    for w in r.windows:
        if w.assessment == 'OCCULTED' and w.start_seconds <= covered:
            covered = max(covered, w.end_seconds)
    assert covered >= anchor+b


@pytest.mark.parametrize('start,end', [(3/64, 9/64), (-9/64, -3/64), (-9/64, 7/64)])
@pytest.mark.parametrize('h', [1/32, .01])
def test_exact_nonbinary_grid_and_nonaligned_sun_knots(start, end, h):
    knots = sorted({start, end, start+(end-start)/4, (start+end)/2})
    q = query(start, end, h=h, knots=knots)
    r = evaluate(source=q)
    assert r.status == 'classified', r.reason
    assert_partition(r); assert_analytic_graph(r); assert_accounting(r)
    expected = {Q(q.start.elapsed_seconds), Q(q.end.elapsed_seconds)}
    expected.update(Q(s.elapsed_seconds) for s in q.table.samples)
    # Prefix-only steps remain proof ancestors, not reporting cells. Add both
    # clipped endpoints only for a strictly positive reporting intersection.
    for s in r.steps:
        lo = max(Q(q.start.elapsed_seconds), s.tube.start_seconds)
        hi = min(Q(q.end.elapsed_seconds), s.tube.end_seconds)
        if lo < hi:
            expected.update((lo, hi))
    actual = {x for g in r.geometry_records for x in (g.cell.start_seconds, g.cell.end_seconds)}
    assert actual == expected
    if h == .01:
        assert any(Q(float(t)) != t for t in actual)


def test_reused_seed_keeps_nonzero_uncertainty_and_counted_interior_derivation(monkeypatch):
    q = query(3/64, 5/64, h=1/32)
    table = replace(q.table, samples=(SunPositionSample(q.start.elapsed_seconds, (-1., 16., 0.)),
                                      SunPositionSample(q.end.elapsed_seconds, (-1., -16., 0.))))
    # The reporting edge lies INSIDE coarse [1/32,1/16]; neither a Sun knot
    # nor clipping a tube establishes an endpoint at that reporting edge.
    q = replace(q, table=table)
    chosen = []
    original = m._Session._choose_seed
    def record(self, piece, direction):
        boundary = original(self, piece, direction)
        chosen.append(boundary)
        return boundary
    monkeypatch.setattr(m._Session, '_choose_seed', record)
    r = evaluate(source=q, max_passes=4)
    assert r.coverage_complete and chosen
    assert all(any(a < b for a, b in seed.state_bounds) for seed in chosen if seed.id)
    assert any(seed.id and seed.elapsed_seconds < Q(q.start.elapsed_seconds) for seed in chosen)
    assert any(s.pass_index > 0 and s.tube.source_final_seconds == Q(q.start.elapsed_seconds) for s in r.steps)
    assert_analytic_graph(r); assert_partition(r); assert_accounting(r)


@pytest.mark.parametrize('case', ['clone', 'stale', 'different-time', 'different-authority'])
def test_foreign_stale_and_same_digest_forged_seed_rejected_atomically(monkeypatch, case):
    captured = []
    original = m._Session._choose_seed
    def remember(self, piece, direction):
        seed = original(self, piece, direction)
        captured.append(seed)
        return seed
    monkeypatch.setattr(m._Session, '_choose_seed', remember)
    valid = evaluate(resolution=1/512)
    assert valid.coverage_complete and captured
    stale = captured[0]
    def substitute(self, piece, direction):
        seed = original(self, piece, direction)
        if case == 'stale': return stale
        if case == 'clone': return forge(seed)
        if case == 'different-time': return forge(seed, elapsed_seconds=seed.elapsed_seconds+Q(1, 128))
        return forge(seed, common_authority_digest='0'*64)
    monkeypatch.setattr(m._Session, '_choose_seed', substitute)
    r = evaluate(resolution=1/512)
    assert r.status == 'computational_failure' and r.windows is None and not r.coverage_complete
    assert 'FOREIGN_STALE_OR_FORGED_BOUNDARY_SEED' in r.reason
    assert len(r.passes) == 1 and all(s.pass_index == 0 for s in r.steps)


@pytest.mark.parametrize('record', ['boundary', 'step-tube', 'geometry-cell'])
def test_nested_ledger_mutation_cannot_reuse_a_forged_certificate(monkeypatch, record):
    original = m._Session._choose_seed
    changed = []
    def mutate(self, piece, direction):
        seed = original(self, piece, direction)
        if not changed:
            changed.append(True)
            if record == 'boundary':
                object.__setattr__(seed, 'state_bounds', tuple((Decimal(123), Decimal(123)) for _ in range(6)))
            elif record == 'step-tube':
                g = self.geometry_records[piece.supports[0].geometry_record_id]
                object.__setattr__(self.steps[g.step_id].tube, 'velocity_bounds_m_per_s',
                                   tuple((Decimal(123), Decimal(123)) for _ in range(3)))
            else:
                g = self.geometry_records[piece.supports[0].geometry_record_id]
                object.__setattr__(g.cell, 'assessment', 'ILLUMINATED')
        return seed
    monkeypatch.setattr(m._Session, '_choose_seed', mutate)
    r = evaluate(resolution=1/512)
    assert changed and r.status == 'computational_failure' and r.windows is None
    assert 'LEDGER' in r.reason or 'FORGED' in r.reason or 'ANCESTRY' in r.reason


@pytest.mark.parametrize('case', ['int-bool', 'float-int', 'hostile-int', 'hostile-float', 'hostile-text'])
def test_ledger_signatures_bind_primitive_types_without_hostile_equality(monkeypatch, case):
    class IntTrap(int):
        def __eq__(self, other):
            raise AssertionError('hostile integer equality executed')
        __ne__ = __eq__
    class FloatTrap(float):
        def __eq__(self, other):
            raise AssertionError('hostile float equality executed')
        __ne__ = __eq__
    original = m._Session._choose_seed
    changed = []
    def mutate(self, piece, direction):
        seed = original(self, piece, direction)
        if not changed:
            changed.append(True)
            if case == 'int-bool':
                object.__setattr__(seed, 'direction', bool(seed.direction))
            elif case == 'hostile-int':
                object.__setattr__(seed, 'direction', IntTrap(seed.direction))
            elif case == 'hostile-text':
                object.__setattr__(seed, 'common_authority_digest', TextTrap(seed.common_authority_digest))
            else:
                g = self.geometry_records[piece.supports[0].geometry_record_id]
                p = self.steps[g.step_id].enclosure_policy
                assert type(p.min_radius_m) is float and p.min_radius_m == 1.0
                object.__setattr__(p, 'min_radius_m', 1 if case == 'float-int' else FloatTrap(1.0))
        return seed
    monkeypatch.setattr(m._Session, '_choose_seed', mutate)
    source = example_request('ambiguous')
    source = replace(source, coast=replace(source.coast, enclosure_policy=replace(
        source.coast.enclosure_policy, min_radius_m=1.0)))
    r = evaluate(source=source, resolution=1/512)
    assert changed and r.status == 'computational_failure' and r.windows is None
    assert any(word in r.reason for word in ('LEDGER', 'FORGED', 'ANCESTRY', 'SIGNATURE'))
    assert 'hostile' not in r.reason


@pytest.mark.parametrize('endpoint_only', [False, True])
def test_opposing_closed_certificates_fail_even_at_shared_endpoint(monkeypatch, endpoint_only):
    original = b3._geometry_cell
    def inject(*args):
        c = original(*args)
        calls.append(c)
        if endpoint_only:
            classification = 'ILLUMINATED' if len(calls) == 1 else 'OCCULTED'
        else:
            # First pass has one retained certificate and an adjacent unknown
            # span. Its later opposite certificate shares only the old closed
            # boundary with the earlier retained illuminated cell.
            classification = {1: 'ILLUMINATED', 2: 'UNRESOLVED'}.get(len(calls), 'OCCULTED')
        return forge(c, assessment=classification,
                     reason='INJECTED_CLOSED_CERTIFICATE')
    calls = []
    monkeypatch.setattr(b3, '_geometry_cell', inject)
    r = evaluate(source=query(0, 1/16))
    assert r.status == 'computational_failure' and r.windows is None
    assert 'CONTRADICTORY_CLOSED' in r.reason
    assert_accounting(r)


@pytest.mark.parametrize('kind', ['position', 'sun', 'velocity'])
def test_incompatible_common_solution_enclosures_fail_atomically(monkeypatch, kind):
    original = b3._geometry_cell
    calls = []
    def disjoint(*args):
        c = original(*args)
        calls.append(c)
        if len(calls) == 2:
            if kind == 'position':
                c = forge(c, position_bounds_m=tuple((Q(1000), Q(1000)) for _ in range(3)))
            elif kind == 'sun':
                c = forge(c, provider_sun_bounds_m=tuple((Q(1000), Q(1000)) for _ in range(3)))
        return c
    if kind == 'velocity':
        step = segments._validated_step
        n = []
        def wrong_velocity(*args):
            endpoint, tube, other = step(*args)
            n.append(1)
            if len(n) == 2:
                tube = tuple(tube[:3])+tuple(enclosure._I(Decimal(1000), Decimal(1000)) for _ in range(3))
            return endpoint, tube, other
        monkeypatch.setattr(segments, '_validated_step', wrong_velocity)
    else:
        monkeypatch.setattr(b3, '_geometry_cell', disjoint)
    r = evaluate(source=query(0, 1/16))
    assert r.status == 'computational_failure' and r.windows is None
    assert 'INCONSISTENT_COMMON' in r.reason
    assert_accounting(r)


def test_initial_geometry_domain_ambiguity_remains_conditional():
    q = example_request('illuminated')
    table = replace(q.table, samples=(replace(q.table.samples[0], position_m=(0., 1., 0.)),
                                      replace(q.table.samples[-1], position_m=(0., -1., 0.))))
    r = evaluate(source=replace(q, table=table), max_passes=3)
    assert_partition(r); assert_accounting(r)
    assert any('SUN_VECTOR_NONZERO_NOT_ESTABLISHED' in w.reasons for w in r.windows)
    assert r.combined_qualification == 'UNRESOLVED'


@pytest.mark.parametrize('failure', [enclosure._Unresolved('injected late step failure'),
                                   DecimalException('injected late Decimal failure')])
def test_late_second_leg_failure_is_atomic_and_failed_work_charged(monkeypatch, failure):
    original = enclosure._step_with_tube
    calls = []
    def fail_third(*args):
        calls.append(1)
        if len(calls) == 3:
            raise failure
        return original(*args)
    monkeypatch.setattr(enclosure, '_step_with_tube', fail_third)
    r = evaluate(source=query(-3/64, 3/64))
    assert r.status == 'computational_failure' and r.windows is None and not r.coverage_complete
    assert r.attempted_integration_steps == 3 and r.completed_integration_steps == 2
    assert r.passes[0].status == 'failed' and r.picard_attempts > 0
    assert_analytic_graph(r); assert_accounting(r)


def test_failed_later_geometry_does_not_publish_prior_or_partial_new_partition(monkeypatch):
    original = b3._geometry_cell
    calls = []
    def fail_third(*args):
        calls.append(1)
        if len(calls) == 3:
            raise b3._WorkFailure('injected later geometry failure')
        return original(*args)
    monkeypatch.setattr(b3, '_geometry_cell', fail_third)
    r = evaluate(resolution=1/512)
    assert r.status == 'computational_failure' and r.windows is None
    assert r.passes[0].status == 'complete' and r.passes[-1].status == 'failed'
    assert r.geometry_cells_attempted == r.geometry_cells_evaluated+1
    assert r.reserved_geometry_cells > r.geometry_cells_evaluated
    assert_accounting(r)


@pytest.mark.parametrize('field', ['max_integration_steps', 'max_picard_attempts', 'max_geometry_cells',
                                 'max_retained_evidence_units', 'max_arithmetic_operations'])
def test_each_initial_global_quota_rejects_before_integrator(monkeypatch, field):
    def forbidden(*args, **kwargs):
        raise AssertionError('initial quota was checked after integration')
    monkeypatch.setattr(enclosure, '_step_with_tube', forbidden)
    r = evaluate(source=query(0, 1/16), **{field: 1})
    assert r.status == 'budget_exhausted' and r.windows is None
    assert r.attempted_integration_steps == r.picard_attempts == r.geometry_cells_attempted == 0
    assert len(r.passes) == 1 and r.passes[0].status == 'rejected_plan'
    assert_accounting(r)


@pytest.mark.parametrize('field,counter', [
    ('max_integration_steps', 'reserved_integration_steps'),
    ('max_picard_attempts', 'reserved_picard_attempts'),
    ('max_geometry_cells', 'reserved_geometry_cells'),
    ('max_retained_evidence_units', 'reserved_evidence_units'),
    ('max_arithmetic_operations', 'reserved_arithmetic_operations'),
])
def test_later_global_quota_retains_exact_last_supported_partition(field, counter):
    initial = evaluate(max_passes=1)
    r = evaluate(**{field: getattr(initial, counter)})
    assert r.status == 'budget_exhausted' and r.coverage_complete
    assert r.windows == initial.windows
    assert len(r.passes) == 2 and r.passes[-1].status == 'rejected_plan'
    assert r.completed_integration_steps == initial.completed_integration_steps
    assert_partition(r); assert_accounting(r)


def test_connected_uncertainty_across_reasons_does_not_shrink_by_cell_splitting(monkeypatch):
    original = b3._geometry_cell
    def unknown(*args):
        c = original(*args)
        return forge(c, assessment='UNRESOLVED', reason='FIRST' if c.j2_cell_index % 2 else 'SECOND')
    monkeypatch.setattr(b3, '_geometry_cell', unknown)
    q = query(0, 1/8)
    r = evaluate(source=q, max_passes=2, resolution=1/32)
    assert r.status == 'budget_exhausted' and r.max_unresolved_width_seconds == Q(1, 8)
    assert not r.temporal_resolution_achieved
    assert_partition(r); assert_accounting(r)


def test_prior_certified_spans_retained_with_original_support_identity():
    q = query(0, 1/8, knots=(0, 1/32, 1/8))
    q = replace(q, table=replace(q.table, samples=(
        SunPositionSample(q.start.elapsed_seconds, (-1., 16., 0.)),
        SunPositionSample(q.start.elapsed_seconds+1/32, (-1., -16., 0.)),
        SunPositionSample(q.end.elapsed_seconds, (-1., -16., 0.)))))
    first = evaluate(source=q, resolution=2**-20, max_passes=3)
    later = evaluate(source=q, resolution=2**-20, max_passes=4)
    assert first.coverage_complete and later.coverage_complete
    kept = [(w, s) for w in first.windows if w.assessment != 'UNRESOLVED' for s in w.supports]
    assert kept and later.reused_certificate_pieces > 0
    for w, s in kept:
        assert any(other.assessment == w.assessment and other.start_seconds <= s.start_seconds
                   and other.end_seconds >= s.end_seconds and s in other.supports for other in later.windows)
    assert_partition(later); assert_analytic_graph(later); assert_accounting(later)


def test_exact_minimum_step_floor_stops_with_last_complete_partition():
    q = example_request('ambiguous')
    anchor = q.start.elapsed_seconds
    q = replace(q, coast=replace(q.coast, enclosure_policy=replace(q.coast.enclosure_policy,
        step_seconds=2**-20)), end=replace(q.end, elapsed_seconds=anchor+2**-20))
    table = replace(q.table, domain_seconds=(anchor, anchor+2**-20), samples=(
        SunPositionSample(anchor, (-1., 16., 0.)), SunPositionSample(anchor+2**-20, (-1., -16., 0.))))
    r = evaluate(source=replace(q, table=table), resolution=2**-30)
    assert r.status == 'numerical_limit' and r.coverage_complete and len(r.passes) == 1
    assert_partition(r); assert_accounting(r)


@pytest.mark.parametrize('field,ceiling', list(LIMITS.items()))
@pytest.mark.parametrize('bad', ['bool', 'float', 'zero', 'negative', 'above', 'text', 'subclass'])
def test_every_local_policy_authority_has_strict_finite_domain(field, ceiling, bad):
    class IntSubclass(int):
        pass
    value = {'bool': True, 'float': 1., 'zero': 0, 'negative': -1,
             'above': ceiling+1, 'text': '1', 'subclass': IntSubclass(1)}[bad]
    with pytest.raises((TypeError, ValueError)):
        policy(**{field: value})


@pytest.mark.parametrize('value', [True, 0, -1, float('inf'), float('nan'), Q(1, 128),
                                 '0.1', 2**41+1, 2**54+1])
def test_resolution_is_strict_and_no_inexact_integer_is_normalized(value):
    with pytest.raises((TypeError, ValueError)):
        request(resolution=value)


@pytest.mark.parametrize('path,bad', [
    ('coast.policy_version', True), ('start.elapsed_seconds', True),
    ('policy.max_picard_attempts', True), ('table.interpolation', TextTrap('LINEAR_POSITION_V1')),
    ('table.provenance.accuracy_policy', 'ZERO_ERROR'),
], ids=['coast-bool', 'time-bool', 'picard-bool', 'hostile-text', 'invalid-accuracy'])
def test_forged_nested_input_rebuilt_before_any_numerical_work(monkeypatch, path, bad):
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid original authority entered integrator')
    monkeypatch.setattr(enclosure, '_step_with_tube', forbidden)
    with pytest.raises((TypeError, ValueError)):
        m.evaluate_local_illumination(change_path(request(), path, bad))


def test_results_are_request_only_recomputed_and_decimal_context_independent():
    q = request('illuminated')
    r = m.evaluate_local_illumination(q)
    assert [f.name for f in fields(m.LocalIlluminationResult) if f.init] == ['request']
    assert replace(forge(r, windows=(), status='classified', combined_qualification='QUALIFIED')) == r
    assert replace(r) == r
    for obj, name in ((q, 'policy'), (r, 'status'), (r.boundaries[0], 'state_bounds')):
        assert not hasattr(obj, '__dict__')
        with pytest.raises(FrozenInstanceError):
            setattr(obj, name, None)
    with localcontext() as ctx:
        ctx.prec = 3; ctx.traps[Inexact] = True
        assert m.evaluate_local_illumination(q) == r
    assert not {'events', 'roots', 'event_accuracy', 'executor_authorized'} & {f.name for f in fields(r)}
    assert 'ops_sim.v5.scenario_inputs' not in sys.modules


def test_reordered_fresh_evaluations_have_no_shared_derived_cache():
    requests = [request('illuminated'), request(source=query(-3/64, 3/64)), request(max_passes=3)]
    forward = [m.evaluate_local_illumination(q) for q in requests]
    reverse = [m.evaluate_local_illumination(q) for q in reversed(requests)]
    assert forward == list(reversed(reverse))
    for a, b in zip(forward, reversed(reverse)):
        if a.boundaries:
            assert a.boundaries[0] is not b.boundaries[0]
