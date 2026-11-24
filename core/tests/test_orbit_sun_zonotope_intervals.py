"""Independent exact-ray references, original grids, binding and atomicity."""
from copy import deepcopy
from dataclasses import fields, replace
from decimal import Decimal, Inexact, ROUND_UP, localcontext
from fractions import Fraction as Q
import pytest

from examples.m2_interval_illumination_demo import example_request
from ops_sim.v5 import orbit_sun_zonotope_intervals as m
from ops_sim.v5 import orbit_sun_intervals as geo
from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5 import orbit_j2_zonotope as z
from ops_sim.v5 import orbit_j2_zonotope_segments as seg
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.sun_table import SunPositionSample
from test_j2_zonotope import circle_range, assert_box_contains


def request(kind='illuminated', *, span=None, step=None, knots=None, maximum=32, cells=32, cap=2**24):
    old=example_request(kind)
    t=old.coast.trajectory;start=t.initial_state.position.instant.elapsed_seconds
    end=old.end if span is None else GeometryInstant(old.end.epoch,start+span)
    p=replace(old.coast.enclosure_policy, max_steps=maximum,
              **({} if step is None else {'step_seconds':step}))
    source=seg.J2ZonotopeSegmentRequest(t,end,z.J2ZonotopePolicyV3(p,(0,)*6,cap))
    table=old.table
    if end != old.end or knots is not None:
        ts=(start,end.elapsed_seconds) if knots is None else tuple(start+x for x in knots)
        table=replace(table, domain_seconds=(ts[0],ts[-1]), samples=tuple(SunPositionSample(x,(100.,0.,0.)) for x in ts))
    return m.ZonotopeIntervalIlluminationRequest(source,table,m.ZonotopeIntervalIlluminationPolicy(cells))


def failed(r):
    assert r.status=='unresolved' and r.reason and r.cells is None
    assert not r.all_cells_classified and r.combined_qualification=='UNRESOLVED'
    assert r.arithmetic_operations <= r.request.policy.max_arithmetic_operations


def fake_source(q, bounds=((2,2),(0,0),(0,0))):
    """Synthetic certified-source seam, NOT an orbital/physical oracle."""
    grid,_=m._plan(q.segment,q.table)
    e=object.__new__(seg.J2ZonotopeSegmentResult)
    for f in fields(e):object.__setattr__(e,f.name,q.segment if f.name=='request' else f.default)
    object.__setattr__(e,'status','enclosed')
    for n in ['planned_steps','attempted_steps','completed_steps']:object.__setattr__(e,n,len(grid)-1)
    tube=tuple(tuple(Decimal(v) for v in p) for p in bounds)
    object.__setattr__(e,'cells',tuple(seg.J2ZonotopeSegmentCell(a,b,i,a,b,tube,((Decimal(0),Decimal(0)),)*3) for i,(a,b) in enumerate(zip(grid,grid[1:]))))
    return e


@pytest.mark.parametrize('kind,expected',[('illuminated','ILLUMINATED'),('occulted','OCCULTED'),('ambiguous','UNRESOLVED')])
def test_real_whole_arc_and_independent_rational_circle_reference(kind,expected):
    q=request(kind);r=m.evaluate_zonotope_interval_illumination(q)
    assert r.status=='complete',r.reason
    assert r.cells[0].assessment==expected and r.propagation_calls==1
    assert r.all_cells_classified==(expected!='UNRESOLVED')
    # R=2, n=17/16: a rigorous whole-arc trig series reference, not samples.
    assert_box_contains(r.upstream_evidence.cells[0].position_bounds_m+r.upstream_evidence.cells[0].velocity_bounds_m_per_s,circle_range(Q(0),Q(1,32)))
    assert 1-Q(17,512)**2/2>Q(99,100) and Q(17,512)<Q(34,1000)
    assert 198-Q(68,1000)-4>0  # r.S-4 positive for Sun x=100.
    assert (2+200*Q(34,1000))**2<(100+Q(198,100))**2  # independent cross-distance criterion, Sun x=-100.
    assert r.upstream_evidence.scalar_operations==r.upstream_evidence.charged_leaf_operations+r.upstream_evidence.reserved_control_operations


@pytest.mark.parametrize('position,sun,expected',[
    (((2,2),(0,0),(0,0)),(100.,0.,0.),'ILLUMINATED'),
    (((2,2),(0,0),(0,0)),(-100.,0.,0.),'OCCULTED'),
    (((2,2),(1,1),(0,0)),(1.,1.,0.),'OCCULTED'),  # exact tangent y=1
    (((2,2),(1.01,1.01),(0,0)),(1.,1.01,0.),'ILLUMINATED'),
    (((2,2),(.99,1.01),(0,0)),(1.,1.,0.),'UNRESOLVED'),
])
def test_fixed_and_interval_sphere_ray_oracle(monkeypatch,position,sun,expected):
    q=request();q=replace(q,table=replace(q.table,samples=tuple(replace(s,position_m=sun) for s in q.table.samples)))
    e=fake_source(q,position);monkeypatch.setattr(m,'_propagate',lambda x:e)
    r=m.evaluate_zonotope_interval_illumination(q);assert r.status=='complete';assert r.cells[0].assessment==expected
    if position[1]==(1,1):
        # Independent exact distance from center to horizontal half-ray is 1.
        assert r.cells[0].D==(Q(0),Q(0)) and r.cells[0].B[1]<0


@pytest.mark.parametrize('span,step,knots',[(.25,.1,(0.,.05,.1,.2,.25)),(3/64,1/32,(0.,1/64,1/32,3/64)),(1/16,1/32,(0.,1/32,1/16))])
def test_exact_union_remainders_and_shared_closed_endpoints(span,step,knots):
    q=request(span=span,step=step,knots=knots);grid,plan=m._plan(q.segment,q.table)
    a=Q(q.segment.trajectory.initial_state.position.instant.elapsed_seconds);end=Q(q.segment.end.elapsed_seconds)
    assert grid[0]==plan[0]==a and grid[-1]==plan[-1]==end
    assert set(plan)==set(grid)|{Q(s.elapsed_seconds) for s in q.table.samples}
    full,tail=divmod(end-a,Q(step));assert len(grid)-1==full+bool(tail)
    if tail:assert grid[-1]-grid[-2]==tail


def test_non_binary_anchor_and_absolute_union_ceiling_without_propagation(monkeypatch):
    q=request(span=4.,step=4/4096,maximum=4096,cells=5118,knots=tuple(i*4/1023 for i in range(1024)))
    grid,plan=m._plan(q.segment,q.table);assert len(grid)==4097 and len(plan)-1==5118
    t=q.segment.trajectory;state=t.initial_state;instant=GeometryInstant(state.position.instant.epoch,.1)
    state=replace(state,position=replace(state.position,instant=instant),velocity=replace(state.velocity,instant=instant))
    t=object.__new__(f2.J2CartesianTrajectory);object.__setattr__(t,'initial_state',state);object.__setattr__(t,'gravity_model',q.segment.trajectory.gravity_model)
    source=seg.J2ZonotopeSegmentRequest(t,GeometryInstant(instant.epoch,.35),replace(q.segment.policy,base_policy=replace(q.segment.policy.base_policy,step_seconds=.1)))
    table=replace(q.table,domain_seconds=(.1,.35),samples=(SunPositionSample(.1,(100.,0.,0.)),SunPositionSample(.35,(100.,0.,0.))))
    a,b=m._plan(source,table);assert a[0]==Q(.1) and a[-1]==Q(.35) and a[-1]-a[-2]==Q(.35)-Q(.1)-2*Q(.1)


def test_source_tube_unchanged_across_sun_splits_and_hostile_context():
    q=request(span=3/64,knots=(0,1/64,1/32,3/64));normal=m.evaluate_zonotope_interval_illumination(q)
    with localcontext() as ctx:
        ctx.prec=3;ctx.rounding=ROUND_UP;ctx.traps[Inexact]=True
        r=m.evaluate_zonotope_interval_illumination(q);assert r==normal
    assert len(r.cells)==3
    for c in r.cells:
        source=r.upstream_evidence.cells[c.j2_cell_index]
        assert c.position_bounds_m==tuple(tuple(Q(v) for v in p) for p in source.position_bounds_m)
    assert r.cells[0].j2_cell_index==r.cells[1].j2_cell_index==0
    assert r.cells[0].position_bounds_m==r.cells[1].position_bounds_m


@pytest.mark.parametrize('a,b',[(1.,-1.),(5e-324,-5e-324),(0.,5e-324),(1e-300,-1e-300)])
def test_complete_affine_and_binary64_rounding_envelope(a,b):
    q=request();table=replace(q.table,samples=(SunPositionSample(128.,(100.,a,0.)),SunPositionSample(129.,(100.,b,0.))),domain_seconds=(128.,129.))
    ar=m._Rational(m.MAX_GEOMETRY_OPERATIONS)
    _,exact,rounded=geo._sun_envelope(table,0,Q(128)+Q(1,3),Q(128)+Q(2,3),ar)
    x=Q(a)+(Q(b)-Q(a))/3;y=Q(a)+2*(Q(b)-Q(a))/3
    assert exact[1]==(min(x,y),max(x,y))
    assert rounded[1]==(min(x,y,Q(float(min(x,y)))),max(x,y,Q(float(max(x,y)))))
    # Correct rounding monotonicity encloses every affine value, including subnormal zero.
    assert rounded[1][0]<=exact[1][0]<=exact[1][1]<=rounded[1][1]


@pytest.mark.parametrize('mode,reason',[('sun','SUN_VECTOR_NONZERO_NOT_ESTABLISHED'),('direction','SPACECRAFT_TO_SUN_NONZERO_NOT_ESTABLISHED'),('earth','SPACECRAFT_NOT_PROVEN_STRICTLY_EXTERIOR')])
def test_explicit_unresolved_domains(monkeypatch,mode,reason):
    q=request();s=(2.,0.,0.) if mode=='direction' else (100.,0.,0.)
    nodes=(s,s) if mode!='sun' else ((1.,0.,0.),(-1.,0.,0.))
    q=replace(q,table=replace(q.table,samples=tuple(replace(v,position_m=p) for v,p in zip(q.table.samples,nodes))))
    e=fake_source(q,((.9,1.1),(0,0),(0,0)) if mode=='earth' else ((2,2),(0,0),(0,0)))
    monkeypatch.setattr(m,'_propagate',lambda x:e);r=m.evaluate_zonotope_interval_illumination(q)
    assert r.status=='complete' and r.cells[0].reason==reason and not r.all_cells_classified


@pytest.mark.parametrize('mode',['geometry','source_steps','horizon'])
def test_preflight_refusal_zero_owner_entries(monkeypatch,mode):
    q=request(span=1/16,knots=(0,1/64,1/32,1/16),cells=1)
    if mode=='source_steps':q=replace(q,policy=m.ZonotopeIntervalIlluminationPolicy(32),segment=replace(q.segment,policy=replace(q.segment.policy,base_policy=replace(q.segment.policy.base_policy,max_steps=1))))
    if mode=='horizon':
        end=128.+86401;table=replace(q.table,domain_seconds=(128.,end),samples=(SunPositionSample(128.,(100.,0.,0.)),SunPositionSample(end,(100.,0.,0.))))
        q=replace(q,table=table,segment=replace(q.segment,end=GeometryInstant(q.segment.end.epoch,end)))
    monkeypatch.setattr(m,'_propagate',lambda *a:pytest.fail('forbidden propagation'))
    r=m.evaluate_zonotope_interval_illumination(q);failed(r);assert r.propagation_calls==0


@pytest.mark.parametrize('cap',[1,1024])
def test_upstream_resource_failure_retains_separate_evidence(cap):
    r=m.evaluate_zonotope_interval_illumination(request(cap=cap));failed(r)
    assert r.propagation_calls==1 and r.upstream_evidence.status=='unresolved'
    assert r.upstream_evidence.budget_rejected


def test_one_upstream_call_no_hidden_setup_nominal_or_force(monkeypatch):
    q=request();calls=[];original=m._propagate
    def spy(x):calls.append(x);return original(x)
    def forbidden(*a,**k):raise AssertionError('unsafe hidden science')
    monkeypatch.setattr(m,'_propagate',spy)
    monkeypatch.setattr(f2.J2CartesianTrajectory,'__post_init__',forbidden)
    monkeypatch.setattr(f2,'_gravity',forbidden);monkeypatch.setattr(f2,'evaluate_j2_cartesian_state',forbidden)
    monkeypatch.setattr(z,'_nominal_evaluator',forbidden)
    q2=m._request(q);assert q2==q
    r=m.evaluate_zonotope_interval_illumination(q2);assert r.status=='complete',r.reason;assert len(calls)==1


@pytest.mark.parametrize('mode',['work','bit','conversion','late','final'])
def test_atomic_failure_without_partial_geometry(monkeypatch,mode):
    q=request(span=3/64);e=fake_source(q)
    if mode=='work':q=replace(q,policy=m.ZonotopeIntervalIlluminationPolicy(32,1));e=fake_source(q)
    elif mode=='bit':
        ar=m._Rational(512)
        with pytest.raises(geo._WorkFailure):ar.point(Q(1,2**16385))
        monkeypatch.setattr(m,'_fraction_endpoint',lambda x:ar.point(Q(1,2**16385)))
    elif mode=='conversion':
        c=e.cells[0];object.__setattr__(c,'position_bounds_m',((Decimal('1e999999'),Decimal('1e999999')),)+c.position_bounds_m[1:])
    elif mode=='late':
        original=m._geometry_cell;calls=[]
        def seam(*args):
            calls.append(1)
            if len(calls)==2:raise ArithmeticError('late geometry failure')
            return original(*args)
        monkeypatch.setattr(m,'_geometry_cell',seam)
    elif mode=='final':monkeypatch.setattr(m,'_publish',lambda *a:(_ for _ in ()).throw(ValueError('final publication failure')))
    monkeypatch.setattr(m,'_propagate',lambda x:e)
    r=m.evaluate_zonotope_interval_illumination(q);failed(r);assert r.upstream_evidence is e
    if mode in ('late','final'):assert r.geometry_cells_evaluated>0


@pytest.mark.parametrize('mode',['missing','reordered','gap','tail','index','identity','physical','type'])
def test_substituted_upstream_rejected_atomically(monkeypatch,mode):
    q=request(span=3/64);e=fake_source(q)
    if mode=='missing':object.__setattr__(e,'cells',e.cells[:-1])
    elif mode=='reordered':object.__setattr__(e,'cells',e.cells[::-1])
    elif mode in ('gap','tail'):object.__setattr__(e.cells[-1],'end_seconds',e.cells[-1].end_seconds-Q(1,1024))
    elif mode=='index':object.__setattr__(e.cells[0],'source_step_index',1)
    elif mode=='identity':object.__setattr__(e,'kernel_id','wrong')
    elif mode=='physical':object.__setattr__(e,'request',request(span=1/32).segment)
    elif mode=='type':e=object()
    monkeypatch.setattr(m,'_propagate',lambda x:e);r=m.evaluate_zonotope_interval_illumination(q);failed(r)


@pytest.mark.parametrize('field,value',[('api_version',True),('api_id','wrong'),('geometry_resource_policy_version',2)])
def test_tampered_request_identity(field,value):
    q=request();object.__setattr__(q,field,value)
    with pytest.raises((TypeError,ValueError)):m._request(q)


@pytest.mark.parametrize('field,value',[('max_cells',True),('max_cells',5119),('max_cells',0),('max_arithmetic_operations',True),('max_arithmetic_operations',0),('max_arithmetic_operations',m.MAX_GEOMETRY_OPERATIONS+1)])
def test_policy_strict_limits(field,value):
    data=dict(max_cells=32,max_arithmetic_operations=1024);data[field]=value
    with pytest.raises((TypeError,ValueError)):m.ZonotopeIntervalIlluminationPolicy(**data)


def test_complete_frame_and_closed_table_binding():
    q=request();badframe=replace(q.table.frame,ellipsoid=replace(q.table.frame.ellipsoid,name='different'))
    with pytest.raises(ValueError):replace(q,table=replace(q.table,frame=badframe))
    with pytest.raises(ValueError):replace(q,segment=replace(q.segment,end=GeometryInstant(q.segment.end.epoch,q.segment.end.elapsed_seconds+1)))


@pytest.mark.parametrize('mode',['ellipsoid','rotation','epoch','velocity','provenance','gravity','ledger','budget_flag','completed','geometry_index'])
def test_complete_authority_and_published_work_bindings(monkeypatch,mode):
    q=request()
    if mode=='ellipsoid':
        shape=replace(q.table.frame.ellipsoid,equatorial_radius_m=replace(q.table.frame.ellipsoid.equatorial_radius_m,value=2.))
        with pytest.raises(ValueError):replace(q,table=replace(q.table,frame=replace(q.table.frame,ellipsoid=shape)))
        return
    if mode=='rotation':
        rotation=replace(q.table.frame.rotation,initial_phase_rad=replace(q.table.frame.rotation.initial_phase_rad,value=0.))
        with pytest.raises(ValueError):replace(q,table=replace(q.table,frame=replace(q.table.frame,rotation=rotation)))
        return
    if mode=='epoch':
        epoch=replace(q.table.epoch,julian_day=q.table.epoch.julian_day+1)
        with pytest.raises(ValueError):replace(q,table=replace(q.table,epoch=epoch))
        return
    if mode=='velocity':
        t=deepcopy(q.segment.trajectory);v=t.initial_state.velocity
        object.__setattr__(v,'instant',GeometryInstant(v.instant.epoch,v.instant.elapsed_seconds+1))
        with pytest.raises(ValueError):replace(q,segment=replace(q.segment,trajectory=t))
        return
    if mode=='provenance':
        table=deepcopy(q.table);object.__setattr__(table.provenance,'source_timescale','UTC')
        with pytest.raises(ValueError):replace(q,table=table)
        return
    e=fake_source(q)
    if mode=='gravity':
        t=deepcopy(q.segment.trajectory);model=t.gravity_model
        object.__setattr__(model,'j2',replace(model.j2,value=0.))
        object.__setattr__(e,'request',replace(q.segment,trajectory=t))
    if mode=='ledger':object.__setattr__(e,'scalar_operations',1)
    if mode=='budget_flag':object.__setattr__(e,'budget_rejected',True)
    if mode=='completed':object.__setattr__(e,'completed_steps',0)
    if mode=='geometry_index':
        original=m._geometry_cell
        monkeypatch.setattr(m,'_geometry_cell',lambda *a:replace(original(*a),j2_cell_index=3))
    monkeypatch.setattr(m,'_propagate',lambda x:e)
    failed(m.evaluate_zonotope_interval_illumination(q))
