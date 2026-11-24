"""Short proof/lineage/reference checks; no saved diagnostic is authority."""
from copy import copy
from dataclasses import replace, fields
from decimal import Decimal, Inexact, localcontext, ROUND_UP
from fractions import Fraction as Q
import pytest
from test_orbit_sun_zonotope_intervals import request as base_request
from test_j2_zonotope import circle_range, assert_box_contains
from ops_sim.v5 import orbit_sun_zonotope_local as m
from ops_sim.v5 import orbit_sun_zonotope_intervals as b34
from ops_sim.v5 import orbit_j2_zonotope as z
from ops_sim.v5 import orbit_j2_zonotope_segments as b33
from ops_sim.v5 import orbit_sun_intervals as geo


def request(kind='ambiguous', *, passes=2, trials=8, span=None, knots=None, cap=2**31, **overrides):
    q=base_request(kind,span=span,knots=knots,cap=cap)
    values=dict(max_initial_steps=32,max_refinement_steps=64,max_trials=trials,max_passes=passes,
                max_picard_attempts=2048,max_geometry_cells=256,max_retained_evidence_units=65536,
                max_geometry_operations=2**24)
    values.update(overrides)
    return m.ZonotopeLocalIlluminationRequest(q.segment,q.table,1/1024,
                                             m.ZonotopeLocalIlluminationPolicy(**values))


def check(r):
    assert r.scalar_operations==r.charged_leaf_operations+r.reserved_control_operations<=r.request.segment.policy.max_scalar_operations
    assert r.geometry_operations==r.geometry_leaf_operations+r.geometry_control_operations<=r.request.policy.max_geometry_operations
    assert r.picard_attempts<=r.reserved_picard_attempts
    assert r.completed_steps<=r.attempted_steps
    assert r.initial_attempted_steps<=r.request.policy.max_initial_steps
    assert r.refinement_attempted_steps<=r.request.policy.max_refinement_steps
    assert r.geometry_cells_attempted<=r.reserved_geometry_cells
    assert r.retained_evidence_units<=r.reserved_evidence_units
    assert r.geometry_cells_evaluated<=r.reserved_geometry_cells
    assert r.combined_qualification=='UNRESOLVED'
    if r.coverage_complete:
        assert r.status in ('classified','resolution_reached','budget_exhausted')
        assert r.pieces[0].start_seconds==Q(r.request.segment.trajectory.initial_state.position.instant.elapsed_seconds)
        assert r.pieces[-1].end_seconds==Q(r.request.segment.end.elapsed_seconds)
        assert all(a.end_seconds==b.start_seconds for a,b in zip(r.pieces,r.pieces[1:]))
        assert r.retained_evidence_units<=r.reserved_evidence_units
    else:assert r.pieces is None and r.windows is None and r.initial_pieces is None


@pytest.mark.parametrize('kind',['illuminated','occulted','ambiguous'])
@pytest.mark.parametrize('passes,trials',[(0,8),(3,0)])
def test_zero_refinement_initial_full_scientific_partition_exact(kind,passes,trials):
    q=request(kind,passes=passes,trials=trials);r=m.evaluate_zonotope_local_illumination(q);check(r)
    old=b34.evaluate_zonotope_interval_illumination(b34.ZonotopeIntervalIlluminationRequest(
        q.segment,q.table,b34.ZonotopeIntervalIlluminationPolicy(5118)))
    assert r.coverage_complete,r.reason
    assert tuple(g.cell for g in r.geometry_records)==old.cells
    assert tuple(s.tube for s in r.steps)==old.upstream_evidence.cells
    assert r.boundaries[-1].set==old.upstream_evidence.final_diagnostic
    assert r.refinement_completed_steps==0


@pytest.mark.parametrize('kind',['illuminated','occulted'])
def test_fully_certified_no_local_work_with_independent_circle(kind):
    r=m.evaluate_zonotope_local_illumination(request(kind,passes=4));check(r)
    assert r.status=='classified' and len(r.trials)==1 and r.reused_boundaries==0
    assert_box_contains(r.steps[0].tube.position_bounds_m+r.steps[0].tube.velocity_bounds_m_per_s,
                        circle_range(Q(0),Q(1,32)))


def test_ambiguous_span_runs_refinement_and_keeps_closed_provenance():
    q=request();r=m.evaluate_zonotope_local_illumination(q);check(r)
    assert r.coverage_complete,r.reason
    assert r.initial_completed_steps==1 and r.refinement_completed_steps>0
    assert len(r.trials)>1 and r.reused_boundaries>0
    assert r.max_unresolved_width_seconds<Q(1,32)
    assert any(p.assessment!='UNRESOLVED' for p in r.pieces)
    assert r.max_unresolved_width_seconds>Q(q.requested_resolution_seconds)
    assert r.status=='budget_exhausted'
    assert all(g.pass_index==0 for g in r.geometry_records if g.id in [p.geometry_record_id for p in r.initial_pieces])


def test_nonconvergence_is_complete_unresolved_not_computational_failure():
    q=request();q=replace(q,table=replace(q.table,samples=tuple(replace(s,position_m=v) for s,v in zip(q.table.samples,((100.,0.,0.),(-100.,0.,0.))))))
    r=m.evaluate_zonotope_local_illumination(q);check(r)
    assert r.status=='budget_exhausted' and r.coverage_complete
    assert any(p.assessment=='UNRESOLVED' for p in r.pieces)
    assert any(g.cell.reason=='SUN_VECTOR_NONZERO_NOT_ESTABLISHED' for g in r.geometry_records)


def test_full_generator_transfer_and_one_cumulative_arithmetic(monkeypatch):
    # Second original cell is ambiguous; its seed has accumulated generators.
    q=request(span=1/16,knots=(0.,1/32,3/64,1/16))
    q=replace(q,table=replace(q.table,samples=tuple(replace(s,position_m=p) for s,p in zip(q.table.samples,((100.,0.,0.),(100.,0.,0.),(-1.,16.,0.),(-1.,-16.,0.))))))
    calls=[];original=m._transport
    def spy(state,h,model,policy,ar,index,end):
        calls.append((state,ar,index,end))
        return original(state,h,model,policy,ar,index,end)
    monkeypatch.setattr(m,'_transport',spy)
    r=m.evaluate_zonotope_local_illumination(q);check(r);assert r.coverage_complete,r.reason
    assert len({id(ar) for _,ar,_,_ in calls})==1
    assert [index for _,_,index,_ in calls]==list(range(len(calls)))
    local=[t for t in r.trials if t.pass_index]
    assert local
    t=local[0];seed=r.boundaries[t.seed_boundary_id]
    assert seed.set.generators and seed.set.births
    parent=calls[t.step_ids[0]][0]
    assert tuple(v.as_tuple() for v in parent.center)==tuple(v.as_tuple() for v in seed.set.center)
    assert tuple(tuple(v.as_tuple() for v in c) for c in parent.generators)==tuple(tuple(v.as_tuple() for v in c) for c in seed.set.generators)
    assert parent.births==seed.set.births and parent.time==seed.set.time
    assert r.request.segment.trajectory.initial_state.position.instant==q.segment.trajectory.initial_state.position.instant


@pytest.mark.parametrize('span,knots',[(3/64,(0.,1/64,1/32,3/64)),(.25,(0.,.05,.1,.2,.25))])
def test_fractional_grid_sun_union_full_tubes_and_initial_reference(span,knots):
    q=request('illuminated',span=span,knots=knots,passes=0)
    r=m.evaluate_zonotope_local_illumination(q);check(r);assert r.coverage_complete,r.reason
    grid,plan=b34._plan(q.segment,q.table)
    assert tuple(b.set.time for b in r.boundaries)==grid
    assert tuple(p.start_seconds for p in r.pieces)+(r.pieces[-1].end_seconds,)==plan
    old=b34.evaluate_zonotope_interval_illumination(b34.ZonotopeIntervalIlluminationRequest(q.segment,q.table,b34.ZonotopeIntervalIlluminationPolicy(5118)))
    assert tuple(g.cell for g in r.geometry_records)==old.cells
    for g in r.geometry_records:
        whole=r.steps[g.step_id].tube
        assert g.cell.position_bounds_m==tuple(tuple(Q(v) for v in pair) for pair in whole.position_bounds_m)


@pytest.mark.parametrize('mode',['foreign','duplicate','center','generator','time','birth','parent','step'])
def test_seed_refuses_foreign_duplicate_and_tampered_ancestry(mode):
    q=request('illuminated',span=1/16,knots=(0.,1/32,1/16),passes=0)
    s=m._Session(q);s.run();b=s.owned[-1]
    if mode=='foreign':
        other=m._Session(q);other.run();b=other.owned[-1]
    elif mode=='duplicate':b=copy(b)
    elif mode=='center':object.__setattr__(b.z,'center',(Decimal(9),)+b.z.center[1:])
    elif mode=='generator':object.__setattr__(b.z,'generators',())
    elif mode=='time':object.__setattr__(b.z,'time',Q(123))
    elif mode=='birth':object.__setattr__(b.z,'births',tuple(reversed(b.z.births)))
    elif mode=='parent':object.__setattr__(b.record,'parent_step_id',None)
    elif mode=='step':object.__setattr__(s.steps[0].tube,'end_seconds',Q(129))
    with pytest.raises(m._Failure):s._seed(b)


@pytest.mark.parametrize('touch',[True,False])
def test_closed_touch_and_positive_overlap_opposing_certificates_refused(touch):
    s=m._Session(request('illuminated',span=1/16,knots=(0.,1/32,1/16),passes=0));s.run()
    a,b=s.pieces
    c=replace(s.geometry[b.geometry_record_id].cell,assessment='OCCULTED')
    s.geometry[b.geometry_record_id]=replace(s.geometry[b.geometry_record_id],cell=c)
    b=replace(b,assessment='OCCULTED')
    if not touch:b=replace(b,start_seconds=a.start_seconds)
    with pytest.raises(m._Failure,match='CONTRADICTORY_CLOSED'):s._common(a,b)


def test_exact_tangent_closed_ray_contact_is_occulted():
    q=request();a=m._GeometryLedger(2**20);weights=geo._shape_weights(q.table.frame.ellipsoid,a)
    # Equatorial tangent to the unit equatorial radius; y=1, d=(-1,0,0).
    p=tuple(a.point(Q(v)) for v in (2,1,0));sun=tuple(a.point(Q(v)) for v in (1,1,0))
    out=geo._geometry(p,sun,weights,a)
    assert out[4]==(Q(0),Q(0)) and out[-2]=='OCCULTED'


@pytest.mark.parametrize('name,value,reason',[('max_initial_steps',1,'INITIAL_STEP'),('max_picard_attempts',1,'PICARD'),('max_geometry_cells',1,'GEOMETRY_CELL'),('max_retained_evidence_units',1,'ROOT_EVIDENCE'),('max_geometry_operations',1,'GEOMETRY_OPERATION')])
def test_prospective_initial_quota_refusal_without_transport(monkeypatch,name,value,reason):
    q=request('illuminated',span=1/16,knots=(0.,1/32,1/16),**{name:value})
    monkeypatch.setattr(m,'_transport',lambda *a:pytest.fail('forbidden transport'))
    r=m.evaluate_zonotope_local_illumination(q);check(r)
    assert not r.coverage_complete and r.status=='budget_exhausted' and reason in r.reason
    assert r.attempted_steps==0


@pytest.mark.parametrize('name,value,reason',[('max_refinement_steps',0,'REFINEMENT_STEP'),('max_trials',0,'TRIAL'),('max_picard_attempts',12,'PICARD'),('max_geometry_cells',1,'GEOMETRY_CELL'),('max_retained_evidence_units',400,'EVIDENCE'),('max_geometry_operations',100000,'GEOMETRY_OPERATION')])
def test_bounded_resolution_stop_retains_complete_initial_partition(name,value,reason):
    r=m.evaluate_zonotope_local_illumination(request(**{name:value}));check(r)
    assert r.coverage_complete,r.reason
    assert r.status=='budget_exhausted' and reason in r.reason
    assert r.refinement_completed_steps==0


@pytest.mark.parametrize('mode',['transport','geometry','lineage','final','scalar'])
def test_trial_computational_failure_is_atomic_no_accepted_partition(monkeypatch,mode):
    q=request();old=m._transport;calls=[]
    def injected(*args):
        calls.append(1)
        if len(calls)==2:
            if mode=='scalar':args[4].charge(args[4].limit+1)
            if mode=='transport':raise z._Unresolved('injected second transport')
        return old(*args)
    monkeypatch.setattr(m,'_transport',injected)
    if mode=='geometry':
        oldg=m._geometry_cell
        def fail(*args):
            if len(calls)>1:raise RuntimeError('injected local geometry')
            return oldg(*args)
        monkeypatch.setattr(m,'_geometry_cell',fail)
    if mode=='lineage':
        seed=m._Session._seed
        def bad(self,b):
            if self.steps:object.__setattr__(b.record,'authority_digest','forged')
            return seed(self,b)
        monkeypatch.setattr(m._Session,'_seed',bad)
    if mode=='final':monkeypatch.setattr(m,'_merge',lambda *a:(_ for _ in ()).throw(RuntimeError('final publication')))
    r=m.evaluate_zonotope_local_illumination(q);check(r)
    assert r.status=='computational_failure' and not r.coverage_complete and r.reason
    assert r.pieces is None and r.windows is None and r.initial_pieces is None


def test_scalar_rejection_latches_and_records_failure():
    r=m.evaluate_zonotope_local_illumination(request(cap=1));check(r)
    assert r.status=='computational_failure' and r.scalar_budget_rejected
    assert r.attempted_steps==0


def test_no_nominal_public_segment_or_hidden_setup(monkeypatch):
    q=request();import ops_sim.v5.orbit_j2 as f2
    def forbidden(*a,**k):raise AssertionError('hidden public science')
    monkeypatch.setattr(f2,'evaluate_j2_cartesian_state',forbidden)
    monkeypatch.setattr(f2,'_gravity',forbidden)
    monkeypatch.setattr(f2.J2CartesianTrajectory,'__post_init__',forbidden)
    monkeypatch.setattr(b33,'evaluate_j2_zonotope_segments',forbidden)
    r=m.evaluate_zonotope_local_illumination(q);check(r);assert r.coverage_complete,r.reason


def test_hostile_ambient_decimal_context_does_not_change_complete_results():
    q=request();a=m.evaluate_zonotope_local_illumination(q)
    with localcontext() as c:
        c.prec=3;c.rounding=ROUND_UP;c.traps[Inexact]=True
        b=m.evaluate_zonotope_local_illumination(q)
    assert a==b


@pytest.mark.parametrize('field_name,bad',[('max_passes',True),('max_trials',-1),('max_initial_steps',4097),('max_geometry_operations',float('inf')),('max_refinement_steps',28673)])
def test_strict_policy(field_name,bad):
    with pytest.raises((TypeError,ValueError)):request(**{field_name:bad} if field_name not in ('max_passes','max_trials') else {'passes':bad} if field_name=='max_passes' else {'trials':bad})


@pytest.mark.parametrize('x',[0.,-1.,float('inf'),float('nan'),True,1])
def test_strict_resolution(x):
    with pytest.raises((TypeError,ValueError)):replace(request(),requested_resolution_seconds=x)


def test_local_sun_knot_bridge_preserves_certified_support_and_whole_tube():
    q=request(knots=(0.,1/64,1/32),span=1/32)
    q=replace(q,table=replace(q.table,samples=tuple(replace(s,position_m=p) for s,p in zip(q.table.samples,((100.,0.,0.),(100.,0.,0.),(-100.,0.,0.))))))
    r=m.evaluate_zonotope_local_illumination(q);check(r);assert r.coverage_complete,r.reason
    first=r.initial_pieces[0]
    assert first.assessment=='ILLUMINATED' and first in r.pieces
    assert r.reused_certificates>=1
    bridges=[s for s in r.steps if s.bridge]
    assert bridges and bridges[0].tube.start_seconds==Q(128)
    assert bridges[0].tube.end_seconds==Q(128)+Q(1,64)
    assert all(g.step_id!=bridges[0].id for g in r.geometry_records)
    for s in r.steps:
        assert_box_contains(s.tube.position_bounds_m+s.tube.velocity_bounds_m_per_s,
            circle_range(s.tube.start_seconds-Q(128),s.tube.end_seconds-Q(128)))


def test_reconstructed_private_set_is_rejected_even_with_equal_values():
    s=m._Session(request('illuminated',passes=0));s.run();b=s.owned[-1]
    forged=z._Zonotope(b.z.center,b.z.generators,b.z.births,b.z.time)
    object.__setattr__(b,'z',forged)
    with pytest.raises(m._Failure):s._seed(b)


@pytest.mark.parametrize('mode',['duplicate','gap','outside','reversed','badlabel'])
def test_overlay_rejects_malformed_selected_partition_before_overlap(mode):
    s=m._Session(request());s.run();tasks=s._tasks();new=list(s.pieces)
    if mode=='duplicate':new=[new[0],new[0]]+new[1:]
    elif mode=='gap':new=new[1:]
    elif mode=='outside':new=[replace(new[0],start_seconds=Q(127))]+new[1:]
    elif mode=='reversed':new=list(reversed(new))
    else:new=[replace(new[0],assessment='OCCULTED' if new[0].assessment!='OCCULTED' else 'ILLUMINATED')]+new[1:]
    with pytest.raises(m._Failure):s._overlay(new,tasks)


def test_resolved_width_stop_is_not_event_accuracy_claim():
    q=replace(request(),requested_resolution_seconds=1/32)
    r=m.evaluate_zonotope_local_illumination(q);check(r)
    assert r.status=='resolution_reached' and r.max_unresolved_width_seconds==Q(1,32)
    assert r.refinement_attempted_steps==0 and not all(p.assessment!='UNRESOLVED' for p in r.pieces)


def test_geometry_ledger_exact_control_and_leaf_boundary():
    a=m._GeometryLedger(512+10);a.reserve(10);a.begin_cell()
    for _ in range(512):a.scalar('add',Q(0),Q(1))
    assert a.total_operations==522 and a.operations==512 and a.control_units==10
    with pytest.raises(geo._WorkFailure):a.scalar('add',Q(0),Q(1))
    with pytest.raises(m._Failure):a.reserve(1)
