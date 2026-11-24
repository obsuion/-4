"""Continuous proof/publication contracts, exact analytic and legacy references."""
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal, Inexact, ROUND_UP, localcontext
from fractions import Fraction as Q
import pytest

from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5 import orbit_j2_zonotope as z
from ops_sim.v5 import orbit_j2_zonotope_segments as seg
from ops_sim.v5.orbit_config import GeometryInstant, TTEpoch
from test_v56f2_j2_coast_contracts import at, trajectory
from test_j2_zonotope import circle, circle_range, assert_box_contains


def policy(cap=2**24, **changes):
    return z.J2ZonotopePolicyV3(replace(z._old.J2EnclosurePolicy(1/32, 4096, .5, 50, 12),
                                     **changes), (0,)*6, cap)


def request(span=3/32, *, p=None, t=None):
    # Fixture's public trajectory constructor performs F1 admission OUTSIDE query.
    t = circle() if t is None else t
    return seg.J2ZonotopeSegmentRequest(t, at(t, t.initial_state.position.instant.elapsed_seconds+span),
                                       policy() if p is None else p)


def atomic(r):
    assert r.status == 'unresolved' and r.reason
    assert r.cells is r.final_endpoint_intervals is r.final_diagnostic is None
    assert r.scalar_operations == r.charged_leaf_operations+r.reserved_control_operations
    assert r.scalar_operations <= r.request.policy.max_scalar_operations


@pytest.mark.parametrize('span', [1/64, 1/32, 3/64, 3/32, 7/64])
def test_exact_grid_closed_remainder_and_whole_arc_analytic_reference(span):
    r = seg.evaluate_j2_zonotope_segments(request(span))
    assert r.status == 'enclosed', r.reason
    assert r.planned_steps == r.completed_steps == r.attempted_steps == len(r.cells)
    begin = Q(128)
    for index,c in enumerate(r.cells):
        expected = min(begin+Q(1,32), Q(128+span))
        assert c.start_seconds == c.source_start_seconds == begin
        assert c.end_seconds == c.source_end_seconds == expected
        assert c.source_step_index == index
        assert_box_contains(c.position_bounds_m+c.velocity_bounds_m_per_s,
                            circle_range(begin-Q(128), expected-Q(128)))
        assert all(type(v)is Decimal for pair in c.position_bounds_m+c.velocity_bounds_m_per_s for v in pair)
        begin = expected
    assert begin == r.final_diagnostic.time == Q(128+span)
    assert r.scalar_operations == r.charged_leaf_operations+r.reserved_control_operations
    assert not hasattr(r,'nominal_steps') and not hasattr(r,'nominal_force_calls')


@pytest.mark.parametrize('j2', [0,11/32,-11/32])
@pytest.mark.parametrize('span',[1/32,3/64,3/32])
def test_exact_final_compatibility_with_endpoint_not_equal_resource_totals(j2,span):
    req=request(span,t=trajectory(t0=128,j2=j2))
    r=seg.evaluate_j2_zonotope_segments(req)
    endpoint=z.evaluate_j2_zonotope_enclosure_v3(req.trajectory,req.end,
                                                f2.J2RK4SolverConfig(1/32,4096),req.policy)
    assert r.status==endpoint.status=='enclosed',r.reason
    assert r.final_endpoint_intervals==endpoint.endpoint_intervals
    a,b=r.final_diagnostic,endpoint.diagnostic_state
    assert (a.center,a.generators,a.births,a.time)==(b.center,b.generators,b.births,b.time)
    for x,y in zip(r.final_endpoint_intervals,endpoint.endpoint_intervals):
        assert tuple(v.as_tuple()for v in x)==tuple(v.as_tuple()for v in y)
    assert r.scalar_operations!=endpoint.scalar_operations


def test_full_set_identity_one_cumulative_owner_and_no_nominal_or_force(monkeypatch):
    req=request();real=seg._transport;seen=[];previous=[]
    def spy(current,h,model,p,ar,index,next_time):
        assert type(ar)is z._CoefficientArithmeticV3
        if previous:assert current is previous[-1] and current.generators
        result,tube=real(current,h,model,p,ar,index,next_time)
        seen.append((id(ar),index,current.time,next_time,ar.operations));previous.append(result)
        return result,tube
    def forbidden(*args,**kwargs):raise AssertionError('hidden F2/F1 call')
    monkeypatch.setattr(seg,'_transport',spy)
    monkeypatch.setattr(f2,'evaluate_j2_cartesian_state',forbidden)
    monkeypatch.setattr(f2,'_gravity',forbidden)
    monkeypatch.setattr(z,'_nominal_evaluator',forbidden)
    r=seg.evaluate_j2_zonotope_segments(req)
    assert r.status=='enclosed',r.reason
    assert len(seen)==3 and len({x[0]for x in seen})==1
    assert all(a[-1]<b[-1]for a,b in zip(seen,seen[1:]))


def test_plain_publication_exact_copies_and_ambient_context_independence():
    req=request()
    expected=seg.evaluate_j2_zonotope_segments(req)
    with localcontext()as ctx:
        ctx.prec=3;ctx.rounding=ROUND_UP;ctx.traps[Inexact]=True
        actual=seg.evaluate_j2_zonotope_segments(req)
        assert actual==expected
    ar=z._CoefficientArithmeticV3(50,2**24)
    lo=Decimal('1.230000000000000000000000000000000000000000000000000001')
    hi=Decimal('1.230000000000000000000000000000000000000000000000000009')
    tube=tuple(z._I(ar.point(lo).lo,ar.point(hi).hi)for _ in range(6))
    c=seg._publish_cell(tube,Q(128),Q(129),0,ar)
    for pair in c.position_bounds_m+c.velocity_bounds_m_per_s:
        assert tuple(v.as_tuple()for v in pair)==(lo.as_tuple(),hi.as_tuple())
        assert all(type(v)is Decimal and not hasattr(v,'_ar')for v in pair)


@pytest.mark.parametrize('span',[0,-1/32])
def test_zero_backward_rejected(span):
    with pytest.raises(ValueError,match='forward nonempty'):request(span)


def test_epoch_subclass_and_corrupt_frozen_id_rejected():
    req=request()
    wrong=replace(req.end,epoch=TTEpoch(req.end.epoch.julian_day+1,req.end.epoch.fractional_day))
    with pytest.raises(ValueError,match='TT epoch'):replace(req,end=wrong)
    object.__setattr__(req,'api_version',True)
    with pytest.raises(TypeError):seg.evaluate_j2_zonotope_segments(req)
    class Sub(seg.J2ZonotopeSegmentRequest):pass
    with pytest.raises(TypeError):seg.evaluate_j2_zonotope_segments(Sub(req.trajectory,req.end,req.policy))


@pytest.mark.parametrize('name,value',[('kernel_id','wrong'),('method_id','wrong'),
 ('resource_policy_version',True),('pb_order',7),('rank_bit_cap',8192),('retained_generators',True)])
def test_corrupted_policy_fixed_identity(name,value):
    p=policy();object.__setattr__(p,name,value)
    with pytest.raises((TypeError,ValueError)):request(p=p)


@pytest.mark.parametrize('cap',[1,2047,2048,8192])
def test_early_exhaustion_atomic_and_latch(cap):
    r=seg.evaluate_j2_zonotope_segments(request(p=policy(cap=cap)))
    atomic(r);assert r.budget_rejected


def test_domain_step_horizon_and_picard_refusal():
    cases=[request(p=policy(min_radius_m=3)),request(span=3/32,p=policy(max_steps=1)),
           request(span=86400+1,p=policy()),request(p=policy(max_picard_iterations=1))]
    for req in cases:
        r=seg.evaluate_j2_zonotope_segments(req);atomic(r)
    assert seg.evaluate_j2_zonotope_segments(cases[1]).attempted_steps==0


def test_late_transport_failure_no_partial_coverage(monkeypatch):
    real=seg._transport
    def fail(current,h,model,p,ar,index,next_time):
        if index==1:raise z._Unresolved('late injected failure')
        return real(current,h,model,p,ar,index,next_time)
    monkeypatch.setattr(seg,'_transport',fail)
    r=seg.evaluate_j2_zonotope_segments(request());atomic(r)
    assert r.completed_steps==1 and 'late injected'in r.reason


def test_publication_precharged_late_rejection_and_no_work_after_latch(monkeypatch):
    req=request();real=seg._publish_cell;before=[]
    def note(tube,start,end,index,ar):
        before.append(ar.operations);return real(tube,start,end,index,ar)
    monkeypatch.setattr(seg,'_publish_cell',note)
    assert seg.evaluate_j2_zonotope_segments(req).status=='enclosed'
    cap=before[1]+seg._CELL_CONTROL-1;calls=[];ledgers=[]
    def guarded(tube,start,end,index,ar):
        ledgers.append(ar)
        # The debit must reject before any copy/constructor on the second cell.
        return real(tube,start,end,index,ar)
    constructor=seg.J2ZonotopeSegmentCell
    def constructed(*args):calls.append(args);return constructor(*args)
    monkeypatch.setattr(seg,'_publish_cell',guarded)
    monkeypatch.setattr(seg,'J2ZonotopeSegmentCell',constructed)
    r=seg.evaluate_j2_zonotope_segments(replace(req,policy=policy(cap=cap)))
    atomic(r);assert r.completed_steps==2 and r.budget_rejected and len(calls)==1
    ar=ledgers[-1];counts=(ar.operations,ar.leaf_operations,ar.reserved_units)
    with pytest.raises(z._Unresolved):ar.charge(0)
    assert counts==(ar.operations,ar.leaf_operations,ar.reserved_units)


def test_rank_failure_and_mixed_publication_ownership(monkeypatch):
    real=seg._transport
    def rank(current,h,model,p,ar,index,next_time):
        if index==1:z._check_fraction_bits(Q(1<<4097),ar)
        return real(current,h,model,p,ar,index,next_time)
    monkeypatch.setattr(seg,'_transport',rank)
    r=seg.evaluate_j2_zonotope_segments(request());atomic(r)
    assert r.completed_steps==1 and '4096'in r.reason
    a,b=z._CoefficientArithmeticV3(50,2**24),z._CoefficientArithmeticV3(50,2**24)
    v=b.point(1).lo;other=b.operations
    with pytest.raises(z._Unresolved):seg._publish_cell((z._I(v,v),)*6,Q(0),Q(1),0,a)
    assert b.operations==other


def test_immutable_and_invalid_cell_diagnostic_shapes():
    r=seg.evaluate_j2_zonotope_segments(request())
    for obj,field in [(r,'status'),(r.request,'end'),(r.cells[0],'end_seconds'),(r.final_diagnostic,'time')]:
        with pytest.raises(FrozenInstanceError):setattr(obj,field,getattr(obj,field))
        assert not hasattr(obj,'__dict__')
    c=r.cells[0]
    for change in [dict(source_step_index=True),dict(start_seconds=c.end_seconds),
                   dict(position_bounds_m=([Decimal(0),Decimal(1)],)*3),
                   dict(position_bounds_m=((Decimal('NaN'),Decimal(1)),)*3)]:
        with pytest.raises((ValueError,TypeError)):replace(c,**change)
    with pytest.raises(TypeError):replace(r.final_diagnostic,center=(z._CoefficientArithmeticV3(50).point(1).lo,)*6)
    assert all(not f.init for f in fields(r)if f.name!='request')
