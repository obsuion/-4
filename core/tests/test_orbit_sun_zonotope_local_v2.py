"""Actual v2 calls, independent integer schedules and retained physical proofs."""
from copy import copy
from dataclasses import fields, is_dataclass, replace
from decimal import Decimal, Inexact, ROUND_UP, localcontext
from fractions import Fraction as Q
from hashlib import sha256
import pytest
from test_orbit_sun_zonotope_local import request as legacy_request
from test_j2_zonotope import circle_range, assert_box_contains
from ops_sim.v5 import orbit_sun_zonotope_local as old
from ops_sim.v5 import orbit_sun_zonotope_local_v2 as m
from ops_sim.v5 import orbit_sun_zonotope_local_v2_document as doc
from ops_sim.v5 import orbit_j2_zonotope as z
from ops_sim.v5 import experiment_codec as codec

SHARED = ('max_initial_steps','max_refinement_steps','max_trials','max_passes',
          'max_picard_attempts','max_geometry_cells','max_retained_evidence_units')


def request(kind='ambiguous', *, passes=2, trials=8, span=None, knots=None,
            cap=2**31, **overrides):
    q=legacy_request(kind,passes=passes,trials=trials,span=span,knots=knots,cap=cap)
    p={n:getattr(q.policy,n) for n in SHARED}
    p.update(max_local_control_units=2**34,max_geometry_leaf_operations=2**24,
             max_geometry_control_units=2**32)
    p.update(overrides)
    return m.ZonotopeLocalIlluminationRequestV2(q.segment,q.table,
        q.requested_resolution_seconds,m.ZonotopeLocalIlluminationPolicyV2(**p))


def check(r):
    assert r.proof_scalar_operations==r.proof_scalar_leaf_operations+r.proof_scalar_reserved_operations<=r.proof_scalar_operation_cap
    assert r.local_control_reserved_units<=r.local_control_unit_cap
    assert r.geometry_leaf_operations<=r.geometry_leaf_operation_cap
    assert r.geometry_control_reserved_units<=r.geometry_control_unit_cap
    assert r.input_counting_control_units==32*r.input_nodes_visited
    assert r.picard_attempts<=r.reserved_picard_attempts
    assert r.completed_steps<=r.attempted_steps
    assert r.geometry_cells_evaluated<=r.reserved_geometry_cells
    assert r.retained_evidence_units<=r.reserved_evidence_units
    assert r.api_version==r.resource_policy_version==r.geometry_resource_policy_version==2
    assert r.transport_resource_policy_version==3 and r.combined_qualification=='UNRESOLVED'
    if r.coverage_complete:
        assert r.status in ('classified','resolution_reached','budget_exhausted')
        assert r.pieces[0].start_seconds==Q(r.request.segment.trajectory.initial_state.position.instant.elapsed_seconds)
        assert r.pieces[-1].end_seconds==Q(r.request.segment.end.elapsed_seconds)
        assert all(a.end_seconds==b.start_seconds for a,b in zip(r.pieces,r.pieces[1:]))
        expected=sha256(codec.json_text(codec.canonical_content(doc._input_map(r.request))).encode()).hexdigest()
        assert r.authority_digest==expected
        assert all(b.authority_digest==expected for b in r.boundaries)
        assert all(g.authority_digest==expected for g in r.geometry_records)
    else:
        assert r.pieces is r.windows is r.initial_pieces is None
    if any((r.proof_scalar_budget_rejected,r.local_control_ledger_failed,
            r.geometry_control_ledger_failed,r.geometry_leaf_ledger_failed)):
        assert r.status=='computational_failure' and not r.coverage_complete


def exact(v):
    if type(v)is Decimal or type(v)is z._D:return ('decimal',v.as_tuple())
    if type(v)is Q:return ('fraction',v.numerator,v.denominator)
    if type(v)is float:return ('float',v.hex())
    if is_dataclass(v):return tuple((f.name,exact(getattr(v,f.name)))for f in fields(v))
    if type(v)in(tuple,list):return tuple(exact(x)for x in v)
    return v


def science_projection(r):
    # Local record type/API identity and authority digest differ by design. All
    # physical fields, common structural quotas, graph and evidence are retained.
    def record(v):return tuple((f.name,exact(getattr(v,f.name)))for f in fields(v)if f.name!='authority_digest')
    return (exact(r.request.segment),exact(r.request.table),r.request.requested_resolution_seconds,
        tuple(getattr(r.request.policy,n)for n in SHARED),r.status,r.reason,r.coverage_complete,
        tuple(record(x)for x in r.boundaries),tuple(record(x)for x in r.steps),
        tuple(record(x)for x in r.geometry_records),exact(r.trials),exact(r.pieces),
        exact(r.windows),exact(r.initial_pieces),r.max_unresolved_width_seconds,
        r.attempted_steps,r.completed_steps,r.picard_attempts,r.reductions,
        r.reserved_picard_attempts,r.reserved_geometry_cells,r.reserved_evidence_units,
        r.retained_evidence_units,r.reused_boundaries,r.reused_certificates)


@pytest.mark.parametrize('kind',['illuminated','occulted','ambiguous'])
@pytest.mark.parametrize('passes',[0,2])
def test_full_short_scientific_projection_preserved(kind,passes):
    q1=legacy_request(kind,passes=passes);q2=request(kind,passes=passes)
    a=old.evaluate_zonotope_local_illumination(q1);b=m.evaluate_zonotope_local_illumination_v2(q2);check(b)
    assert b.coverage_complete,b.reason
    assert science_projection(a)==science_projection(b)
    assert doc.zonotope_local_request_digest_v2(q2)!=sha256(codec.json_text(codec.canonical_content(doc._input_map(q2))).encode()).hexdigest()


def node_reference(v):
    if is_dataclass(v):return 1+sum(node_reference(getattr(v,f.name))for f in fields(v))
    if type(v)in(tuple,list):return 1+sum(node_reference(x)for x in v)
    if type(v)is dict:return 1+sum(node_reference(k)+node_reference(x)for k,x in v.items())
    return 1


def cost_reference(v):
    if type(v)is str:return 32+16*len(v)
    if is_dataclass(v):return 64+sum(cost_reference(getattr(v,f.name))for f in fields(v))
    if type(v)in(tuple,list):return 64+sum(cost_reference(x)for x in v)
    if type(v)is dict:return 64+sum(cost_reference(k)+cost_reference(x)for k,x in v.items())
    return 512


def parameter_reference(p):
    v=p.provenance;texts=[v.parameter_id.value,v.units]+[s.value for s in v.source_ids]
    texts += [x for x in (v.rationale,v.derivation)if x is not None]
    n=len(v.source_ids);chars=sum(len(s.value)for s in v.source_ids)
    return 256+sum(64+40*len(x)for x in texts)+128*n+32*n*n+32*n*chars


def metadata_reference(q):
    total=512
    for v in (q.segment.trajectory.initial_state.position,q.segment.trajectory.initial_state.velocity):
        e=v.frame.ellipsoid;rot=v.frame.rotation
        total+=64+40*len(e.name)
        total+=sum(parameter_reference(p)for p in (e.equatorial_radius_m,e.flattening,rot.initial_phase_rad,rot.angular_velocity_rad_per_s))
    g=q.segment.trajectory.gravity_model
    gravity=sum(parameter_reference(p)for p in (g.gravitational_parameter_m3_s2,g.j2,g.reference_radius_m))
    return total+gravity,gravity


@pytest.mark.parametrize('kind,passes,span,knots',[
    ('illuminated',0,None,None),('occulted',0,None,None),('ambiguous',2,None,None),
    ('illuminated',0,3/64,(0.,1/64,1/32,3/64))])
def test_independent_all_four_ledgers_and_evidence_schedules(kind,passes,span,knots):
    q=request(kind,passes=passes,span=span,knots=knots);r=m.evaluate_zonotope_local_illumination_v2(q);check(r)
    assert r.coverage_complete,r.reason
    mall,mg=metadata_reference(q)
    assert r.proof_scalar_reserved_operations==mall+640+len(r.steps)*(105800+2*mg+50944+128)
    assert r.input_nodes_visited==node_reference(q)
    assert r.input_identity_control_units==4*cost_reference(q)
    local=8192+2*375424+512+32*node_reference(q)+4*cost_reference(q)
    geom=0;ev=96;previous=[];maxpass=max(t.pass_index for t in r.trials)
    for pi in range(maxpass+1):
        ts=[t for t in r.trials if t.pass_index==pi];n=sum(t.planned_steps for t in ts);g=sum(t.planned_geometry_cells for t in ts)
        B=1+sum(s.pass_index<pi for s in r.steps);M=len(previous)
        local+=8192+4096*(q.policy.max_initial_steps if pi==0 else min(4096*q.policy.max_trials,q.policy.max_refinement_steps))+4096*len(q.table.samples)
        local+=2*sum(375424*(t.seed_boundary_id+2)for t in ts)
        local+=1556736*n+2*375424*(B+1)+2048*(M+g)+8192
        geom+=4096*(4*M+5*g+3);ev+=96*n+64*g+8*len(ts)+16
        selected=[(t.start_seconds,t.end_seconds)for t in ts]
        previous=[p for p in previous if not any(a<p.end_seconds and p.start_seconds<b for a,b in selected)]
        previous += [m.LocalPiece(g.cell.start_seconds,g.cell.end_seconds,g.id,g.cell.assessment,g.cell.reason)for g in r.geometry_records if g.pass_index==pi]
        if pi<maxpass:local+=2048*len(previous)+64
    assert r.local_control_reserved_units==local
    assert r.geometry_control_reserved_units==geom
    assert r.reserved_evidence_units==ev


@pytest.mark.parametrize('domain',['proof','local','geometry_control','geometry_leaf'])
@pytest.mark.parametrize('delta',[-1,0,1])
def test_actual_query_exact_quota_boundaries(domain,delta):
    q=request('illuminated',passes=0);baseline=m.evaluate_zonotope_local_illumination_v2(q);check(baseline)
    if domain=='proof':q=replace(q,segment=replace(q.segment,policy=replace(q.segment.policy,max_scalar_operations=baseline.proof_scalar_operations+delta)))
    else:
        field,needed={'local':('max_local_control_units',baseline.local_control_reserved_units),
                      'geometry_control':('max_geometry_control_units',baseline.geometry_control_reserved_units),
                      'geometry_leaf':('max_geometry_leaf_operations',512*(baseline.reserved_geometry_cells+1))}[domain]
        q=replace(q,policy=replace(q.policy,**{field:needed+delta}))
    r=m.evaluate_zonotope_local_illumination_v2(q);check(r)
    if delta>=0:assert r.coverage_complete and r.status=='classified',r.reason
    else:assert not r.coverage_complete and r.reason


@pytest.mark.parametrize('count',range(4))
def test_counting_prefix_precharged_and_retained_on_actual_failure(monkeypatch,count):
    q=request('illuminated',passes=0,max_local_control_units=8192+2*375424+32*count+31)
    monkeypatch.setattr(m,'_transport',lambda *a:pytest.fail('transport after rejected sizing'))
    r=m.evaluate_zonotope_local_illumination_v2(q);check(r)
    assert r.status=='computational_failure' and r.local_control_budget_rejected
    assert r.input_nodes_visited==count and r.input_counting_control_units==32*count
    assert r.local_control_reserved_units==8192+2*375424+32*count
    assert r.proof_scalar_reserved_operations>0 and r.attempted_steps==0


@pytest.mark.parametrize('value',[(1,2),'x'*16385,tuple(range(4097)),float('inf'),object()])
def test_sizing_schema_and_prefix(value):
    ledger=m._LocalControlLedgerV2(2**24);progress=[0]
    if value==(1,2):
        assert m._size_and_cost(value,ledger,progress)==64+2*512
        assert progress==[3]and ledger.reserved_units==96
    else:
        with pytest.raises(m._Failure):m._size_and_cost(value,ledger,progress)
        assert progress[0]>=1 and ledger.reserved_units==32*progress[0]


def test_sizing_never_invokes_caller_hooks():
    class Meta(type):
        def __hash__(cls):pytest.fail('caller type hash')
        def __eq__(cls,other):pytest.fail('caller type equality')
    class Hostile(metaclass=Meta):
        def __getattribute__(self,name):pytest.fail('caller attribute')
        def __iter__(self):pytest.fail('caller iteration')
    a=m._LocalControlLedgerV2(2**24);p=[0]
    with pytest.raises(m._Failure,match='UNSUPPORTED_NORMALIZED'):m._size_and_cost(Hostile(),a,p)
    assert p==[1]and a.reserved_units==32


@pytest.mark.parametrize('ledger',[m._LocalControlLedgerV2,m._GeometryControlLedgerV2])
def test_control_exhaustion_is_latched_and_never_refunded(ledger):
    a=ledger(7);a.reserve(7,'test');assert a.reserved_units==7
    with pytest.raises(m._Failure):a.reserve(1,'over')
    with pytest.raises(m._Failure):a.reserve(0,'after rejection')
    assert a.rejected and a.budget_rejected and a.reserved_units==7


def test_geometry_leaf_latch_and_original_per_cell_limit():
    a=m._GeometryLeafLedgerV2(1024);a.begin_cell()
    for _ in range(512):a.scalar('add',Q(0),Q(1))
    with pytest.raises(Exception):a.scalar('add',Q(0),Q(1))
    assert a.operations==512 and a.budget_rejected and a.rejected
    with pytest.raises(m._Failure):a.begin_cell()
    with pytest.raises(m._Failure):a.point(0)
    assert a.operations==512


@pytest.mark.parametrize('mode',['proof','local','geometry_control','geometry_leaf','publication'])
def test_execution_failures_are_atomic_and_keep_counters(monkeypatch,mode):
    q=request();original=m._transport
    def transport(*args):
        if args[5]==1:
            if mode=='proof':args[4].charge(args[4].limit+1)
            raise z._Unresolved('injected local transport')
        return original(*args)
    if mode=='proof':monkeypatch.setattr(m,'_transport',transport)
    elif mode=='publication':monkeypatch.setattr(m,'_merge',lambda *a:(_ for _ in ()).throw(RuntimeError('late publication')))
    elif mode=='geometry_leaf':
        fn=m._geometry_cell
        def geometry(*a):
            if a[-1].operations>200:a[-1].scalar('add',Q(1<<16385),Q(0))
            return fn(*a)
        monkeypatch.setattr(m,'_geometry_cell',geometry)
    else:
        fn=m._SessionV2._seed
        def seed(self,b):
            if self.steps:
                ledger=self.lc if mode=='local'else self.gc
                ledger.reserve(ledger.maximum+1,'injected late failure')
            return fn(self,b)
        monkeypatch.setattr(m._SessionV2,'_seed',seed)
    r=m.evaluate_zonotope_local_illumination_v2(q);check(r)
    assert r.status=='computational_failure'and not r.coverage_complete
    assert r.initial_completed_steps>0 and r.pieces is r.windows is r.initial_pieces is None


@pytest.mark.parametrize('mode',['foreign','duplicate','center','generators','time','births','parent','step','context','rebuilt','anchor'])
def test_complete_seed_ownership_checks_remain(mode):
    q=request('illuminated',passes=0,span=1/16,knots=(0.,1/32,1/16));s=m._SessionV2(q);s.run();b=s.owned[-1]
    if mode=='foreign':other=m._SessionV2(q);other.run();b=other.owned[-1]
    elif mode=='duplicate':b=copy(b)
    elif mode=='center':object.__setattr__(b.z,'center',(Decimal(9),)+b.z.center[1:])
    elif mode=='generators':object.__setattr__(b.z,'generators',())
    elif mode=='time':object.__setattr__(b.z,'time',Q(123))
    elif mode=='births':object.__setattr__(b.z,'births',tuple(reversed(b.z.births)))
    elif mode=='parent':object.__setattr__(b.record,'parent_step_id',None)
    elif mode=='step':object.__setattr__(s.steps[0].tube,'end_seconds',Q(129))
    elif mode=='context':object.__setattr__(b.z.center[0],'_ar',z._CoefficientArithmeticV3(50))
    elif mode=='rebuilt':object.__setattr__(b,'z',z._Zonotope(b.z.center,b.z.generators,b.z.births,b.z.time))
    else:s.anchor=Q(0)
    with pytest.raises(m._Failure):s._seed(b)


def test_full_generator_carry_and_single_exact_proof_ledger(monkeypatch):
    q=request(span=1/16,knots=(0.,1/32,3/64,1/16))
    q=replace(q,table=replace(q.table,samples=tuple(replace(s,position_m=v)for s,v in zip(q.table.samples,((100.,0.,0.),(100.,0.,0.),(-1.,16.,0.),(-1.,-16.,0.))))))
    calls=[];fn=m._transport
    def spy(*a):calls.append(a);return fn(*a)
    monkeypatch.setattr(m,'_transport',spy);r=m.evaluate_zonotope_local_illumination_v2(q);check(r)
    assert r.coverage_complete,r.reason
    assert all(type(a[4])is z._CoefficientArithmeticV3 for a in calls)
    assert len({id(a[4])for a in calls})==1
    t=next(t for t in r.trials if t.pass_index);b=r.boundaries[t.seed_boundary_id]
    assert b.set.generators and b.set.births
    parent=calls[t.step_ids[0]][0]
    assert exact((parent.center,parent.generators,parent.births,parent.time))==exact((b.set.center,b.set.generators,b.set.births,b.set.time))


def test_bridge_and_whole_si_tubes_keep_outside_certificate():
    q=request(span=1/32,knots=(0.,1/64,1/32))
    q=replace(q,table=replace(q.table,samples=tuple(replace(s,position_m=v)for s,v in zip(q.table.samples,((100.,0.,0.),(100.,0.,0.),(-100.,0.,0.))))))
    r=m.evaluate_zonotope_local_illumination_v2(q);check(r);assert r.coverage_complete,r.reason
    assert r.initial_pieces[0]in r.pieces and r.reused_certificates>0
    bridges=[s for s in r.steps if s.bridge];assert bridges
    assert all(g.step_id!=bridges[0].id for g in r.geometry_records)
    for s in r.steps:assert_box_contains(s.tube.position_bounds_m+s.tube.velocity_bounds_m_per_s,circle_range(s.tube.start_seconds-Q(128),s.tube.end_seconds-Q(128)))


@pytest.mark.parametrize('touch',[True,False])
def test_closed_touch_and_positive_opposition_fail(touch):
    s=m._SessionV2(request('illuminated',passes=0,span=1/16,knots=(0.,1/32,1/16)));s.run();a,b=s.pieces
    g=s.geometry[b.geometry_record_id];s.geometry[g.id]=replace(g,cell=replace(g.cell,assessment='OCCULTED'))
    b=replace(b,assessment='OCCULTED')
    if not touch:b=replace(b,start_seconds=a.start_seconds)
    with pytest.raises(m._Failure,match='CONTRADICTORY_CLOSED'):s._common(a,b)


@pytest.mark.parametrize('mode',['duplicate','gap','outside','reversed','badlabel'])
def test_overlay_invalid_selected_coverage_fails_before_sweep(mode):
    s=m._SessionV2(request());s.run();tasks=s._tasks();new=list(s.pieces)
    if mode=='duplicate':new=[new[0],new[0]]+new[1:]
    elif mode=='gap':new=new[1:]
    elif mode=='outside':new=[replace(new[0],start_seconds=Q(127))]+new[1:]
    elif mode=='reversed':new.reverse()
    else:new=[replace(new[0],assessment='OCCULTED')]+new[1:]
    with pytest.raises(m._Failure):s._overlay(new,tasks)


def test_ambient_context_and_no_hidden_nominal_calls(monkeypatch):
    import ops_sim.v5.orbit_j2 as f2
    def forbidden(*a,**k):pytest.fail('hidden setup/public science')
    q=request();monkeypatch.setattr(f2.J2CartesianTrajectory,'__post_init__',forbidden)
    monkeypatch.setattr(f2,'_gravity',forbidden);monkeypatch.setattr(f2,'evaluate_j2_cartesian_state',forbidden)
    a=m.evaluate_zonotope_local_illumination_v2(q)
    with localcontext()as ctx:
        ctx.prec=3;ctx.rounding=ROUND_UP;ctx.traps[Inexact]=True
        b=m.evaluate_zonotope_local_illumination_v2(q)
    check(a);check(b);assert a==b


@pytest.mark.parametrize('field',list(m.LIMITS))
@pytest.mark.parametrize('bad',[True,-1,float('inf')])
def test_explicit_policy_types_and_ranges(field,bad):
    with pytest.raises((TypeError,ValueError)):request(**{field:bad})


@pytest.mark.parametrize('name',list(m.LIMITS))
def test_no_budget_is_implicitly_defaulted(name):
    p={n:getattr(request().policy,n)for n in m.LIMITS};del p[name]
    with pytest.raises(TypeError):m.ZonotopeLocalIlluminationPolicyV2(**p)


@pytest.mark.parametrize('value',[0.,-1.,float('nan'),float('inf'),True,1])
def test_strict_resolution(value):
    with pytest.raises((TypeError,ValueError)):replace(request(),requested_resolution_seconds=value)
