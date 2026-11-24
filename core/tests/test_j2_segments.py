"""Continuous J2 coverage, exact time partitions and independent arc bounds.

The analytic checks enclose complete arcs using monotonicity and exact rational
Taylor remainders. A finite point sample is not the continuity oracle.
"""

from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal, DecimalException, Inexact, ROUND_UP, localcontext
from fractions import Fraction as Q

import pytest

from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5 import orbit_j2_enclosure as f3
from ops_sim.v5 import orbit_j2_segments as segments
from ops_sim.v5.orbit_config import GeometryInstant, TTEpoch
from ops_sim.v5.orbit_j2_binding import J2CoastOrbitInputs
from test_j2_enclosure import scale, trig_interval
from test_v56f1_j2_gravity_contracts import TextTrap, change_path, forge
from test_v56f2_j2_coast_contracts import at, trajectory


def coast(t=None, *, h=1/32, maximum=128, **policy_changes):
    t = trajectory(j2=11/32, v=(0, 17/8, 0)) if t is None else t
    p = replace(f3.J2EnclosurePolicy(h, maximum, .5, 50, 12), **policy_changes)
    return J2CoastOrbitInputs(t, f2.J2RK4SolverConfig(1/32, 256), p)


def request(start=0, end=1/8, *, inputs=None):
    c = coast() if inputs is None else inputs
    t = c.trajectory
    anchor = t.initial_state.position.instant.elapsed_seconds
    return segments.J2SegmentRequest(c, at(t, anchor+start), at(t, anchor+end))


def run(start=0, end=1/8, *, inputs=None):
    return segments.evaluate_j2_segments(request(start, end, inputs=inputs))


def bounds(cell):
    return cell.position_bounds_m + cell.velocity_bounds_m_per_s


def assert_contains(cell, reference):
    for actual, (lo, hi) in zip(bounds(cell), reference):
        assert type(actual) is tuple and len(actual) == 2
        assert all(type(x) is Decimal and x.is_finite() for x in actual)
        assert Q(actual[0]) <= lo <= hi <= Q(actual[1])


def circular_arc_reference(start, end, nonzero):
    """Whole-interval bounds, using monotonicity on angles inside [-1,1].

    cos(x) >= 1-x*x/2 >= 1/2 on this interval, so sin increases.
    cos increases to 0 and decreases afterward. Degree-100 endpoint Taylor
    polynomials with their analytic remainder bound endpoint evaluations.
    """
    n = Q(17,16) if nonzero else Q(1)
    a, b = n*start, n*end
    assert -1 <= a < b <= 1
    sa, sb = trig_interval(a, True), trig_interval(b, True)
    ca, cb = trig_interval(a, False), trig_interval(b, False)
    sine = (sa[0], sb[1])
    cosine = (min(ca[0], cb[0]), Q(1) if a <= 0 <= b else max(ca[1], cb[1]))
    return (scale(cosine, 2), scale(sine, 2), (Q(0), Q(0)),
            scale(sine, -2*n), scale(cosine, 2*n), (Q(0), Q(0)))


@pytest.mark.parametrize('nonzero', [False, True], ids=['central','J2'])
@pytest.mark.parametrize('start,end', [(3/64,9/64),(-9/64,-3/64),(-9/64,7/64)])
@pytest.mark.parametrize('anchor', [0,32.125])
def test_complete_circular_arcs_against_independent_analytic_enclosures(nonzero,start,end,anchor):
    t = trajectory(v=(0,17/8 if nonzero else 2,0), j2=11/32 if nonzero else 0, t0=anchor)
    result = run(start,end,inputs=coast(t))
    assert result.status == 'enclosed', result.reason
    for cell in result.cells:
        a, b = cell.start_seconds-Q(anchor), cell.end_seconds-Q(anchor)
        assert_contains(cell,circular_arc_reference(a,b,nonzero))
        # The exported bounds are the full source-step tube, including clipped
        # time outside the request. Check that stronger continuous property too.
        source = sorted((cell.source_initial_seconds-Q(anchor),cell.source_final_seconds-Q(anchor)))
        assert_contains(cell,circular_arc_reference(*source,nonzero))


def test_component_extremum_strictly_inside_cell_defeats_endpoint_only_hull():
    # Exact central circle r=(3,4), v=(-4,3), mu=125: radius=5, n=1.
    # x=3*cos(t)-4*sin(t), y=3*sin(t)+4*cos(t), vx=-y, vy=x.
    # On [5/8,21/32], y>0 so x strictly decreases. Opposite endpoint x
    # signs establish exactly one y maximum, and x*x+y*y=25 makes it 5.
    a,b = Q(5,8),Q(21,32)
    t = trajectory(r=(3,4,0),v=(-4,3,0),mu=125,j2=0,t0=0)
    result = run(float(a),float(b),inputs=coast(t))
    assert result.status == 'enclosed', result.reason
    assert len(result.cells) == 1

    def point(angle):
        s,c = trig_interval(angle,True),trig_interval(angle,False)
        return ((3*c[0]-4*s[1],3*c[1]-4*s[0]),
                (3*s[0]+4*c[0],3*s[1]+4*c[1]))

    (xa,ya),(xb,yb) = point(a),point(b)
    assert xa[0] > 0 and xb[1] < 0
    assert min(ya[0],yb[0]) > 0
    assert max(ya[1],yb[1]) < 5  # An endpoint-only hull excludes the maximum.
    x=(xb[0],xa[1]); y=(min(ya[0],yb[0]),Q(5))
    assert_contains(result.cells[0],(x,y,(Q(0),Q(0)),scale(y,-1),x,(Q(0),Q(0))))
    assert result.cells[0].position_bounds_m[1][1] >= Decimal(5)
    assert result.cells[0].velocity_bounds_m_per_s[0][0] <= Decimal(-5)


@pytest.mark.parametrize('start,end,expected_steps,expected_cells', [
    (0,1/8,4,4),(1/32,1/8,4,3),(3/64,9/64,5,4),
    (-1/8,0,4,4),(-1/8,-1/32,4,3),(-9/64,-3/64,5,4),
    (-9/64,7/64,9,9),
])
def test_closed_cells_complete_ordered_exact_grid_provenance(start,end,expected_steps,expected_cells):
    result=run(start,end)
    assert result.status=='enclosed',result.reason
    cells=result.cells; anchor=Q(result.request.coast.trajectory.initial_state.position.instant.elapsed_seconds)
    assert type(cells) is tuple and len(cells)==expected_cells
    assert result.planned_steps==result.enclosure_steps==expected_steps
    assert result.nominal_steps==0
    assert result.picard_attempts <= expected_steps*result.request.coast.enclosure_policy.max_picard_iterations
    assert cells[0].start_seconds==anchor+Q(start)
    assert cells[-1].end_seconds==anchor+Q(end)
    assert all(first.end_seconds==second.start_seconds for first,second in zip(cells,cells[1:]))
    for cell in cells:
        times=(cell.start_seconds,cell.end_seconds,cell.source_initial_seconds,cell.source_final_seconds)
        assert all(type(t) is Q for t in times)
        lo,hi=sorted(times[2:])
        assert lo<=cell.start_seconds<cell.end_seconds<=hi
        offset=cell.source_initial_seconds-anchor
        assert offset/Q(1,32)==int(offset/Q(1,32))
        assert abs(cell.source_final_seconds-anchor)>abs(offset)
        assert 0<abs(cell.source_final_seconds-cell.source_initial_seconds)<=Q(1,32)


@pytest.mark.parametrize('sign',[-1,1])
def test_absolute_internal_boundaries_are_not_silently_rounded(sign):
    c=coast(h=.01)
    req=request(*( (1/64,1/32) if sign>0 else (-1/32,-1/64)),inputs=c)
    result=segments.evaluate_j2_segments(req)
    assert result.status=='enclosed',result.reason
    assert result.planned_steps==result.enclosure_steps==4
    anchor=Q(c.trajectory.initial_state.position.instant.elapsed_seconds)
    h=Q(.01)
    internal=anchor+sign*2*h
    assert Q(float(internal)) != internal  # A GeometryInstant would lose bits.
    assert any(cell.source_initial_seconds==internal or cell.source_final_seconds==internal
               for cell in result.cells)
    assert all(abs(cell.source_final_seconds-cell.source_initial_seconds)<=h for cell in result.cells)


def test_accumulated_prefix_boxes_are_carried_without_collapsing_or_reanchoring(monkeypatch):
    original=f3._step_with_tube
    records=[]

    def record(box,h,model,policy,ar):
        answer=original(box,h,model,policy,ar)
        records.append((tuple(box),tuple(answer[0]),tuple(answer[1])))
        return answer

    monkeypatch.setattr(f3,'_step_with_tube',record)
    result=run(3/64,9/64)
    assert result.status=='enclosed',result.reason
    assert len(records)==5 and len(result.cells)==4
    assert all(current[0]==previous[1] for previous,current in zip(records,records[1:]))
    assert any(a.lo<a.hi for a in records[1][0])
    assert bounds(result.cells[0])==tuple((a.lo,a.hi) for a in records[1][2])


def test_each_crossing_leg_starts_from_same_original_point_authority(monkeypatch):
    original=f3._step_with_tube; inputs=[]

    def record(box,h,*rest):
        inputs.append((tuple(box),h))
        return original(box,h,*rest)

    monkeypatch.setattr(f3,'_step_with_tube',record)
    result=run(-3/64,3/64)
    assert result.status=='enclosed',result.reason
    assert len(inputs)==4
    assert inputs[0][0]==inputs[2][0]
    assert all(a.lo==a.hi for a in inputs[2][0])
    assert inputs[0][1].hi<0 and inputs[2][1].lo>0


@pytest.mark.parametrize('case',['crossing-total','prefix-work','horizon','input-envelope'])
def test_preflight_rejection_does_not_enter_integrator(monkeypatch,case):
    def forbidden(*args):
        raise AssertionError('entered integrator before admission')

    monkeypatch.setattr(f3,'_step_with_tube',forbidden)
    monkeypatch.setattr(f2,'evaluate_j2_cartesian_state',forbidden)
    c=coast(); start,end=0,1/8
    if case=='crossing-total': c=coast(maximum=8);start,end=-9/64,7/64
    if case=='prefix-work': c=coast(maximum=4);start,end=3/64,9/64
    if case=='horizon': c=coast(h=1024,maximum=4096);start,end=86400,86401
    if case=='input-envelope': c=coast(trajectory(v=(1e-110,2,0)))
    result=run(start,end,inputs=c)
    assert result.status=='unresolved' and result.reason
    assert result.cells is None
    assert result.enclosure_steps==result.picard_attempts==result.nominal_steps==0


def test_segment_bounds_do_not_call_nominal_integrator_or_nominal_grid(monkeypatch):
    def forbidden(*args):
        raise AssertionError('nominal work is outside segment bounds')

    monkeypatch.setattr(f2,'evaluate_j2_cartesian_state',forbidden)
    monkeypatch.setattr(f2,'_grid',forbidden)
    c=replace(coast(),solver_config=f2.J2RK4SolverConfig(1/1024,1))
    result=run(inputs=c)
    assert result.status=='enclosed',result.reason
    assert result.nominal_steps==0 and result.request.coast.solver_config==c.solver_config


@pytest.mark.parametrize('failure',[f3._Unresolved('injected later work failure'),DecimalException('injected arithmetic failure')])
def test_late_failure_never_publishes_successful_prefix(monkeypatch,failure):
    original=f3._step_with_tube; calls=[]

    def fail_second(*args):
        calls.append(1)
        if len(calls)==2:
            raise failure
        return original(*args)

    monkeypatch.setattr(f3,'_step_with_tube',fail_second)
    result=run(0,1/16)
    assert result.status=='unresolved' and result.reason
    assert result.cells is None and result.enclosure_steps==1
    assert result.planned_steps==2 and result.picard_attempts>0


@pytest.mark.parametrize('case',['picard','initial-radius','continuous-radius','decimal-range'])
def test_actual_numerical_failures_are_explicit_and_atomic(case):
    c=coast(); end=1/32
    if case=='picard': c=coast(max_picard_iterations=1)
    if case=='initial-radius': c=coast(min_radius_m=3)
    if case=='continuous-radius':
        c=coast(trajectory(v=(-10,0,0)),h=.125,min_radius_m=1.5);end=.125
    if case=='decimal-range':
        c=coast(trajectory(r=(1e60,0,0),v=(0,1,0),mu=1e100,rg=1,j2=0))
    result=run(0,end,inputs=c)
    assert result.status=='unresolved' and result.reason
    assert result.cells is None and result.nominal_steps==0
    if case=='picard': assert result.picard_attempts==1


@pytest.mark.parametrize('start,end',[(0,0),(1,0)])
def test_empty_or_reversed_intervals_are_invalid(start,end):
    with pytest.raises(ValueError): request(start,end)


@pytest.mark.parametrize('path,bad',[
    ('model',TextTrap('v56f-static-axis-cartesian-j2')),
    ('policy_version',True),('representation_version',2),('binding_version',True),
    ('trajectory.initial_state.position.components_m',(True,0,0)),
    ('trajectory.initial_state.velocity.components_m_per_s',(0,float('nan'),0)),
    ('trajectory.gravity_model.j2.provenance.units',TextTrap('1')),
    ('trajectory.initial_state.position.frame.ellipsoid.name','\ud800'),
    ('enclosure_policy.max_steps',True),('enclosure_policy.precision_digits',39),
    ('solver_config.step_seconds',0),('solver_config.max_steps',True),
], ids=['hostile-model', 'policy-bool', 'representation-version', 'binding-bool',
        'bool-position', 'nan-velocity', 'hostile-units', 'surrogate-frame',
        'bool-budget', 'precision', 'zero-solver-step', 'bool-solver-budget'])
def test_complete_nested_authority_reconstruction_rejects_forgery(path,bad):
    req=request()
    corrupted=change_path(req.coast,path,bad)
    with pytest.raises((TypeError,ValueError)):
        segments.J2SegmentRequest(corrupted,req.start,req.end)
    with pytest.raises((TypeError,ValueError)):
        segments.evaluate_j2_segments(forge(req,coast=corrupted))


def test_incompatible_epoch_is_not_an_absolute_time_equivalence():
    req=request()
    epoch=req.start.epoch
    other=GeometryInstant(TTEpoch(epoch.julian_day+1,epoch.fractional_day),req.end.elapsed_seconds-86400)
    with pytest.raises(ValueError):
        segments.J2SegmentRequest(req.coast,req.start,other)


@pytest.mark.parametrize('field',['start','end'])
def test_forged_instant_is_revalidated(field):
    req=request()
    corrupted=forge(getattr(req,field),elapsed_seconds=True)
    with pytest.raises((TypeError,ValueError)):
        segments.evaluate_j2_segments(forge(req,**{field:corrupted}))


def test_immutable_request_result_and_cells_recompute_derived_state():
    req=request(); result=segments.evaluate_j2_segments(req)
    assert result.status=='enclosed',result.reason
    assert [f.name for f in fields(segments.J2SegmentResult) if f.init]==['request']
    for obj,name,value in ((req,'coast',None),(result,'status','unresolved'),
                           (result.cells[0],'start_seconds',Q(0))):
        assert not hasattr(obj,'__dict__')
        with pytest.raises(FrozenInstanceError): setattr(obj,name,value)
    assert replace(req)==req and replace(result)==result
    changed=forge(result,status='enclosed',cells=(),enclosure_steps=999)
    assert replace(changed)==result


def test_reordering_and_repetition_do_not_cache_changed_query_origins():
    requests=[request(3/64,9/64),request(-9/64,-3/64),request(-3/64,3/64)]
    forward=[segments.evaluate_j2_segments(r) for r in requests]
    reverse=[segments.evaluate_j2_segments(r) for r in reversed(requests)]
    assert forward==list(reversed(reverse))
    assert all(r.status=='enclosed' for r in forward)
    assert segments.evaluate_j2_segments(requests[0])==forward[0]


def test_hostile_decimal_context_cannot_change_enclosures_or_exact_grid():
    req=request(-3/64,9/64,inputs=coast(h=.01))
    expected=segments.evaluate_j2_segments(req)
    assert expected.status=='enclosed',expected.reason
    with localcontext() as ctx:
        ctx.prec=3;ctx.rounding=ROUND_UP;ctx.traps[Inexact]=True
        ctx.Emin=-9;ctx.Emax=9
        assert segments.evaluate_j2_segments(req)==expected
