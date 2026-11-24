"""Exact analytic/interval references, coverage and bounded failure contracts."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Inexact, localcontext
from fractions import Fraction as Q
from math import nextafter, inf
import sys

import pytest

from examples.m2_interval_illumination_demo import example_request, summary
from examples.m2_orbit_sun_demo import demo_query
from examples.m2_sun_table_demo import synthetic_table
from ops_sim.v5 import orbit_sun_intervals as m
from ops_sim.v5 import orbit_j2_segments as b2
from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5.orbit_config import GeometryInstant, FrameKind
from ops_sim.v5.sun_table import SunPositionSample, evaluate_sun_position
from test_j2_enclosure import trig_interval
from test_j2_segments import coast
from test_v56f1_j2_gravity_contracts import change_path, forge, TextTrap
from test_v56f2_j2_coast_contracts import trajectory


def box(values):
    return tuple((Q(x),Q(x)) for x in values)


def geometry(r, s, a=1, f=0):
    # Direct exact geometry unit test: an arbitrary enclosing box is sufficient.
    ar=m._Rational(); b=Q(a)*(1-Q(f))
    return m._geometry(r,s,(1/Q(a)**2,1/Q(a)**2,1/b**2),ar)


@pytest.mark.parametrize('r,s,expected',[
    ((2,0,0),(100,0,0),'ILLUMINATED'),
    ((2,0,0),(-100,0,0),'OCCULTED'),
    ((2,0,0),(2,100,0),'ILLUMINATED'),
    ((2,1,0),(1,1,0),'OCCULTED'),  # exact closed-Earth tangency
    ((2,nextafter(1,inf),0),(1,nextafter(1,inf),0),'ILLUMINATED'),
    ((2,nextafter(1,0),0),(1,nextafter(1,0),0),'OCCULTED'),
    ((2,0,0),(1.5,0,0),'OCCULTED'),  # hit beyond finite Sun endpoint
    ((2,0,0),(1,1,0),'ILLUMINATED'),  # geocentric s points away, actual ray differs
])
def test_exact_sphere_half_ray_and_closed_contact(r,s,expected):
    result=geometry(box(r),box(s))
    assert result[-2]==expected
    assert all(lo==hi for lo,hi in result[1:6])


@pytest.mark.parametrize('z,expected',[(Q(1,2),'OCCULTED'),(Q(3,4),'ILLUMINATED'),(Q(1,4),'OCCULTED')])
def test_exact_polar_radius_not_rounded_sphere(z,expected):
    assert geometry(box((2,0,z)),box((1,0,z)),f=Q(1,2))[-2]==expected


@pytest.mark.parametrize('which,reason',[
    ('earth','SPACECRAFT_NOT_PROVEN_STRICTLY_EXTERIOR'),
    ('direction','SPACECRAFT_TO_SUN_NONZERO_NOT_ESTABLISHED'),
    ('sun','SUN_VECTOR_NONZERO_NOT_ESTABLISHED'),
])
def test_whole_box_domain_must_be_established(which,reason):
    r,s=box((2,0,0)),box((100,0,0))
    if which=='earth':r=((Q(9,10),Q(11,10)),r[1],r[2])
    if which=='direction':s=r
    if which=='sun':s=((Q(-1),Q(1)),(Q(0),Q(0)),(Q(0),Q(0)))
    result=geometry(r,s)
    assert result[-2:]==('UNRESOLVED',reason)


def test_dependence_d_equals_s_minus_entire_spacecraft_box():
    r=((Q(2),Q(3)),(Q(0),Q(1)),(Q(0),Q(0)))
    s=box((2,0,0))
    result=geometry(r,s)
    assert result[0]==((Q(-1),Q(0)),(Q(-1),Q(0)),(Q(0),Q(0)))
    assert result[1][0]==0
    assert result[-2:] == ('UNRESOLVED','SPACECRAFT_TO_SUN_NONZERO_NOT_ESTABLISHED')


def test_tangent_straddling_box_is_ambiguous_not_exact_contact():
    r=((Q(2),Q(2)),(Q(999,1000),Q(1001,1000)),(Q(0),Q(0)))
    result=geometry(r,box((1,1,0)))
    assert result[4][0]<0<result[4][1]
    assert result[-2]=='UNRESOLVED'


@pytest.mark.parametrize('kind,expected',[('illuminated','ILLUMINATED'),('occulted','OCCULTED')])
def test_whole_analytic_j2_arc_clear_classifications(kind,expected):
    # Exact equatorial J2 circle R=2, n=17/16, 0<=t<=1/32.
    # cos(nt)>=1-(17/512)^2/2 > .99, 0<=sin(nt)<=17/512 < .034.
    # Sun x=+100, |sy|<=1 gives r.s-4 >=198-.068-4>0: all rays away.
    # Sun x=-100 gives r.s<0. Cross norm <=2+200*.034=8.8;
    # |d|>=100+1.98=101.98, so distance to ray line <1 for the WHOLE arc.
    # Closest lambda>0; closed equatorial ellipsoid section has radius1.
    assert 1-Q(17,512)**2/2 > Q(99,100)
    assert Q(17,512)<Q(34,1000)
    assert 198-Q(68,1000)-4 > 0
    assert (2+200*Q(34,1000))**2 < (100+Q(198,100))**2
    request=example_request(kind); before=deepcopy(request)
    result=m.evaluate_interval_illumination(request)
    assert request==before
    assert result.status=='complete' and result.all_cells_classified
    assert len(result.cells)==1 and result.cells[0].assessment==expected
    assert result.combined_qualification=='UNRESOLVED'
    assert result.propagation_calls==1 and result.j2_evidence.nominal_steps==0


def _iadd(a,b):return a[0]+b[0],a[1]+b[1]
def _imul(a,b):
    products=[x*y for x in a for y in b]
    return min(products),max(products)
def _isquare(a):return (Q(0) if a[0]<=0<=a[1] else min(x*x for x in a)),max(x*x for x in a)


def independent_circle_ray_side(t, sy):
    # Independent cross-product distance criterion, not production A*C-B^2.
    c,s=trig_interval(Q(17,16)*t,False),trig_interval(Q(17,16)*t,True)
    rx,ry=(2*c[0],2*c[1]),(2*s[0],2*s[1])
    dx,dy=(-1-rx[1],-1-rx[0]),(sy-ry[1],sy-ry[0])
    cross=_iadd(_imul(rx,(sy,sy)),ry)  # r x Sun, Sun x=-1
    distance_num=_isquare(cross)
    length2=_iadd(_isquare(dx),_isquare(dy))
    towards=_iadd(_imul(rx,(-1,-1)),_imul(ry,(sy,sy)))
    assert towards[1]-4<0
    if distance_num[0]>length2[1]:return 'ILLUMINATED'
    if distance_num[1]<length2[0]:return 'OCCULTED'
    raise AssertionError('independent reference did not separate signs')


def test_internal_geometry_change_missed_by_endpoint_only_checks():
    # One affine Sun segment changes direction, never vanishes (sx=-1).
    assert independent_circle_ray_side(Q(0),Q(16))=='ILLUMINATED'
    assert independent_circle_ray_side(Q(1,32),Q(-16))=='ILLUMINATED'
    assert independent_circle_ray_side(Q(1,64),Q(0))=='OCCULTED'
    result=m.evaluate_interval_illumination(example_request('ambiguous'))
    assert result.status=='complete' and not result.all_cells_classified
    assert len(result.cells)==1 and result.cells[0].assessment=='UNRESOLVED'
    assert result.cells[0].sun_norm_squared_m2[0]>0
    assert result.cells[0].D[0]<0<result.cells[0].D[1]


def query(start,end,*,h=1/32,knots=None,t0=32.125,maximum=128,cells=64):
    c=coast(trajectory(t0=t0,j2=11/32,v=(0,17/8,0)),h=h,maximum=maximum)
    times=(t0+start,t0+end) if knots is None else tuple(t0+x for x in knots)
    table=replace(synthetic_table(c.trajectory.initial_state.position.frame),domain_seconds=(times[0],times[-1]),
        samples=tuple(SunPositionSample(t,(100.,i*.125,0.)) for i,t in enumerate(times)))
    return m.IntervalIlluminationRequest(c,table,GeometryInstant(table.epoch,t0+start),
        GeometryInstant(table.epoch,t0+end),m.IntervalIlluminationPolicy(cells))


@pytest.mark.parametrize('start,end',[(0,1/8),(3/64,9/64),(-9/64,-3/64),(-9/64,7/64)])
@pytest.mark.parametrize('h',[1/32,.01])
def test_common_refinement_exact_coverage_provenance_and_single_call(monkeypatch,start,end,h):
    knots=sorted(set((start,end,(start+end)/2,start+(end-start)/4)))
    q=query(start,end,h=h,knots=knots)
    calls=[]; original=b2.evaluate_j2_segments
    def once(request):calls.append(request);return original(request)
    monkeypatch.setattr(b2,'evaluate_j2_segments',once)
    r=m.evaluate_interval_illumination(q)
    assert r.status=='complete',r.reason
    assert len(calls)==1 and r.propagation_calls==1
    expected=sorted({Q(q.start.elapsed_seconds),Q(q.end.elapsed_seconds)} |
        {cell.start_seconds for cell in r.j2_evidence.cells} |
        {cell.end_seconds for cell in r.j2_evidence.cells} |
        {Q(s.elapsed_seconds) for s in q.table.samples})
    actual=[r.cells[0].start_seconds]+[c.end_seconds for c in r.cells]
    assert actual==expected and len(r.cells)==r.planned_geometry_cells
    assert all(a.end_seconds==b.start_seconds for a,b in zip(r.cells,r.cells[1:]))
    for cell in r.cells:
        source=r.j2_evidence.cells[cell.j2_cell_index]
        assert source.start_seconds<=cell.start_seconds<cell.end_seconds<=source.end_seconds
        assert cell.position_bounds_m==tuple((Q(a),Q(b)) for a,b in source.position_bounds_m)
        left,right=q.table.samples[cell.sun_segment_index:cell.sun_segment_index+2]
        assert Q(left.elapsed_seconds)<=cell.start_seconds<cell.end_seconds<=Q(right.elapsed_seconds)
    if h==.01:
        assert any(Q(float(t))!=t for t in actual[1:-1])
    assert r.arithmetic_operations<=m.MAX_CELL_OPERATIONS*(len(r.cells)+1)


def test_many_sun_knots_use_sum_not_cartesian_product():
    q=query(0,1/8,knots=tuple(i/128 for i in range(17)))
    r=m.evaluate_interval_illumination(q)
    assert r.status=='complete'
    assert len(r.j2_evidence.cells)==4
    assert len(r.cells)==16  # union grid, not 4*16
    assert r.cells[-1].sun_weights[1]==1
    assert r.cells[0].sun_weights[0]==0


def test_orbit_prefix_outside_sun_domain_remains_counted():
    q=query(3/64,9/64)
    r=m.evaluate_interval_illumination(q)
    assert r.status=='complete'
    assert r.j2_evidence.enclosure_steps==5 and len(r.j2_evidence.cells)==4
    assert q.table.domain_seconds[0]>q.coast.trajectory.initial_state.position.instant.elapsed_seconds


@pytest.mark.parametrize('a,b',[(0.,1.),(1.,0.),(-1.,0.),(0.,-1.),(0.,2**-1074),(2**-1074,0.),(1e308,-1e308)])
def test_affine_extrema_and_rounding_envelope_without_empirical_tolerance(a,b):
    q=example_request('illuminated')
    table=replace(q.table,domain_seconds=(0.,3.),samples=(
        SunPositionSample(0.,(a,1.,0.)),SunPositionSample(3.,(b,1.,0.))))
    ar=m._Rational()
    weights, exact, envelope=m._sun_envelope(table,0,Q(1),Q(2),ar)
    assert weights==(Q(1,3),Q(2,3))
    values=tuple((1-w)*Q(a)+w*Q(b) for w in weights)
    assert exact[0]==(min(values),max(values))
    assert envelope[0]==(min(exact[0][0],Q(float(exact[0][0]))),max(exact[0][1],Q(float(exact[0][1]))))
    # Supplementary B1 points, not the whole-interval proof (monotone rounding).
    for t in (1.,1.25,1.5,1.75,2.):
        xyz=evaluate_sun_position(table,GeometryInstant(table.epoch,t)).components_m
        assert all(lo<=Q(x)<=hi for x,(lo,hi) in zip(xyz,envelope))


def test_nonzero_nodes_do_not_prove_nonzero_interpolated_sun():
    q=example_request('illuminated')
    table=replace(q.table,samples=(replace(q.table.samples[0],position_m=(0.,1.,0.)),
                                  replace(q.table.samples[-1],position_m=(0.,-1.,0.))))
    result=m.evaluate_interval_illumination(replace(q,table=table))
    assert result.status=='complete' and result.cells[0].assessment=='UNRESOLVED'
    assert result.cells[0].reason=='SUN_VECTOR_NONZERO_NOT_ESTABLISHED'
    midpoint=(q.start.elapsed_seconds+q.end.elapsed_seconds)/2
    with pytest.raises(ValueError):evaluate_sun_position(table,GeometryInstant(table.epoch,midpoint))


def test_geometry_preflight_fails_before_upstream_call(monkeypatch):
    def forbidden(*args):raise AssertionError('propagation before geometry admission')
    monkeypatch.setattr(b2,'evaluate_j2_segments',forbidden)
    result=m.evaluate_interval_illumination(example_request('work-failure'))
    assert result.status=='unresolved' and result.cells is None
    assert result.j2_evidence is None and result.propagation_calls==0
    assert result.planned_geometry_cells==2 and result.geometry_cells_evaluated==0


@pytest.mark.parametrize('which',['work','picard','horizon'])
def test_upstream_failure_preserved_without_nominal_fallback(monkeypatch,which):
    def forbidden(*args):raise AssertionError('nominal propagation used in proof')
    monkeypatch.setattr(f2,'evaluate_j2_cartesian_state',forbidden)
    q=example_request('upstream-failure')
    if which=='picard':
        q=example_request('illuminated')
        q=replace(q,coast=replace(q.coast,enclosure_policy=replace(q.coast.enclosure_policy,max_picard_iterations=1)))
    if which=='horizon':q=query(86400,86401,h=1024,maximum=4096)
    result=m.evaluate_interval_illumination(q)
    assert result.status=='unresolved' and result.cells is None
    assert result.j2_evidence.status=='unresolved' and result.propagation_calls==1
    assert result.j2_evidence.reason in result.reason
    assert result.geometry_cells_evaluated==0 and result.j2_evidence.nominal_steps==0


def test_late_failure_publishes_no_partial_partition(monkeypatch):
    q=query(0,1/16)
    original=m._geometry;calls=[]
    def fail_second(*args):
        calls.append(1)
        if len(calls)==2:raise m._WorkFailure('injected late work failure')
        return original(*args)
    monkeypatch.setattr(m,'_geometry',fail_second)
    result=m.evaluate_interval_illumination(q)
    assert result.status=='unresolved' and result.cells is None
    assert result.geometry_cells_evaluated==1 and result.j2_evidence.status=='enclosed'
    assert result.reason=='injected late work failure'


@pytest.mark.parametrize('limit',['MAX_RATIONAL_BITS','MAX_CELL_OPERATIONS'])
def test_arithmetic_limits_are_explicit_failures(monkeypatch,limit):
    monkeypatch.setattr(m,limit,1)
    result=m.evaluate_interval_illumination(example_request('illuminated'))
    assert result.status=='unresolved' and result.cells is None and result.reason
    assert result.j2_evidence.status=='enclosed'


@pytest.mark.parametrize('max_cells',[0,5119,True,1.,'1',None])
def test_strict_bounded_policy(max_cells):
    with pytest.raises((TypeError,ValueError)):m.IntervalIlluminationPolicy(max_cells)


@pytest.mark.parametrize('which',['two-body','epoch','frame','domain','start-end','forged-time','forged-policy','forged-model','forged-table','forged-provenance'])
def test_input_reconstruction_rejects_before_propagation(monkeypatch,which):
    def forbidden(*args):raise AssertionError('propagation from invalid request')
    monkeypatch.setattr(b2,'evaluate_j2_segments',forbidden)
    q=example_request('illuminated')
    if which=='two-body':q=forge(q,coast=demo_query('two-body').coast)
    if which=='epoch':q=change_path(q,'end.epoch.julian_day',2451546)
    if which=='frame':q=change_path(q,'table.frame.rotation.initial_phase_rad.value',.5)
    if which=='domain':q=change_path(q,'end.elapsed_seconds',129.)
    if which=='start-end':q=forge(q,end=q.start)
    if which=='forged-time':q=change_path(q,'start.elapsed_seconds',True)
    if which=='forged-policy':q=change_path(q,'policy.max_cells',True)
    if which=='forged-model':q=change_path(q,'coast.policy_version',True)
    if which=='forged-table':q=change_path(q,'table.interpolation',TextTrap('LINEAR_POSITION_V1'))
    if which=='forged-provenance':q=change_path(q,'table.provenance.accuracy_policy','ZERO_ERROR')
    with pytest.raises((TypeError,ValueError)):m.evaluate_interval_illumination(q)


def test_external_table_also_has_only_conditional_model_classification():
    result=m.evaluate_interval_illumination(example_request('external'))
    assert result.status=='complete',result.reason
    assert result.request.table.provenance.source_kind=='HORIZONS'
    assert any(c.assessment in ('ILLUMINATED','OCCULTED') for c in result.cells)
    assert result.combined_qualification=='UNRESOLVED'
    assert 'FRAME_ALIGNMENT_ERROR_UNQUANTIFIED' in result.combined_reasons


def test_repeat_reorder_immutability_hostile_decimal_and_no_scenario_import():
    requests=[example_request(k) for k in ('illuminated','occulted','ambiguous')]
    results=[m.evaluate_interval_illumination(q) for q in requests]
    assert results==list(reversed([m.evaluate_interval_illumination(q) for q in reversed(requests)]))
    r=results[0]
    for obj,name in ((r,'status'),(r.request,'start'),(r.cells[0],'assessment')):
        with pytest.raises(FrozenInstanceError):setattr(obj,name,None)
    assert replace(r)==r
    assert replace(forge(r,status='complete',cells=(),arithmetic_operations=999))==r
    with localcontext() as ctx:
        ctx.prec=2;ctx.Emin=-4;ctx.Emax=4;ctx.traps[Inexact]=True
        assert m.evaluate_interval_illumination(requests[0])==r
    assert 'ops_sim.v5.scenario_inputs' not in sys.modules
