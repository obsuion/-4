"""B65 exact F2 differential, owned generations and strict target profiles.

These are bounded fixtures, not Linux execution or a long-horizon qualification.
"""
from pathlib import Path
from copy import deepcopy,copy
from dataclasses import replace
import json,pickle,math
import pytest
from lifetime_support import root_for
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.lifecycle_job_prepared import admit_job_root,prepare_job_runtime
from ops_sim.v5.lifecycle_generation import enable,_Generation
from ops_sim.v5.lifecycle_typed_platform import profile_for,WINDOWS,LINUX,admit_build_data,admit_typed_build,METHOD
from ops_sim.v5.lifecycle_backend import current_source_binding,runtime_binding
from ops_sim.v5.lifecycle_execution import start_lifecycle,build_model
from ops_sim.v5 import _lifecycle_typed65 as native
from ops_sim.v5.orbit_j2 import _rk4_step

SOURCE=Path(__file__).resolve().parents[1]
def build():return json.loads((SOURCE/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes())
def job():
    root,admission=admit_job_root(dumps_root(root_for(600)),'b'*64,build_binding={'synthetic':'generation test only'})
    return prepare_job_runtime(admission,root)
def bits(value):return tuple(tuple(x.hex()for x in row)for row in value)

@pytest.mark.parametrize('step',(10.,1.,.125,-.125))
@pytest.mark.parametrize('r,v',[
    ((7000000.,100000.,200000.),(-100.,6000.,4500.)),
    ((-7000000.,-100000.,200000.),(100.,-6000.,4500.)),
    ((0.,0.,7000000.),(7000.,0.,0.)),
    ((7000000.,0.,0.),(0.,7000.,-0.)),
])
def test_machine_rk4_exactly_matches_separately_owned_original_f2(step,r,v):
    trajectory=build_model(root_for(600)).environment.trajectory;model=trajectory.gravity_model;anchor=trajectory.initial_state.position
    expected=_rk4_step(model,anchor,r,v,step)
    actual=native._b65_world_kernel(float(model.gravitational_parameter_m3_s2.value),float(model.j2.value),float(model.reference_radius_m.value),r,v,step)
    assert bits(actual)==bits(expected)

@pytest.mark.parametrize('r,v,step',[
    ((0.,0.,0.),(1.,1.,1.),1.),
    ((7000000.,0.,0.),(1.,1.,1.),5e-324),
    ((1e308,1e308,1e308),(1.,1.,1.),1.),
])
def test_machine_refusal_matches_original_before_endpoint_publication(r,v,step):
    t=build_model(root_for(600)).environment.trajectory;m=t.gravity_model
    with pytest.raises((ValueError,OverflowError)):_rk4_step(m,t.initial_state.position,r,v,step)
    with pytest.raises((ValueError,OverflowError)):native._b65_world_kernel(float(m.gravitational_parameter_m3_s2.value),float(m.j2.value),float(m.reference_radius_m.value),r,v,step)

def test_generation_full_external_and_cheap_nested_guards_are_separate():
    j=job();hooks=[];v=enable(j,lambda:hooks.append('full'))
    with j.transaction()as outer:
        assert v.closed(outer)
        for _ in range(3):j._full_guard(outer)
        with j.transaction()as inner:
            assert v.closed(inner);j._full_guard(inner)
        assert v.closed(outer)
    snap=v.snapshot();assert snap['phase']=='IDLE';assert snap['closed_requests']>=4
    assert snap['full_requests']>=2;assert snap['activations']==snap['invalidations']==1
    assert not v.closed(outer)
    with pytest.raises(ValueError):outer.require_active()

def test_closed_capability_cannot_be_copied_persisted_or_cross_job():
    j=job();v=enable(j,lambda:None)
    for fn in(copy,deepcopy,pickle.dumps):
        with pytest.raises(TypeError):fn(v)
    with pytest.raises(TypeError):_Generation(j,lambda:None,object())
    other=job();other._validation=v;other._validation_pin=v
    with pytest.raises(ValueError):other._guard_identity()

def test_foreign_callback_called_exactly_once_and_reentrancy_refused():
    j=job();hooks=[];v=enable(j,lambda:hooks.append(1));called=[]
    with j.transaction()as tx:
        def external(x):
            called.append(x)
            with pytest.raises(ValueError,match='reentrancy'):
                with j.transaction():pass
            return x
        token=object();assert tx.callback(external,token)is token
        error=RuntimeError('original callback exception')
        def broken():raise error
        with pytest.raises(RuntimeError)as caught:tx.callback(broken)
        assert caught.value is error;assert v.closed(tx)
    # Two full checks per callback plus the real full outer BOUNDARY hook.
    assert called==[token];assert len(hooks)==5;assert v.snapshot()['callback_suspensions']==2

def test_callback_mutation_and_next_external_mutation_are_not_cached():
    j=job();v=enable(j,lambda:None);root=j.external_root;old=root.duration_seconds
    with pytest.raises(ValueError):
        with j.transaction()as tx:
            tx.callback(lambda:object.__setattr__(root,'duration_seconds',old+1))
    object.__setattr__(root,'duration_seconds',old)
    with j.transaction():assert v.closed()
    object.__setattr__(root,'duration_seconds',old+1)
    try:
        with pytest.raises(ValueError):
            with j.transaction():pytest.fail('mutation admitted')
    finally:object.__setattr__(root,'duration_seconds',old)

def test_foreign_callback_cannot_replace_native_math_intrinsic_before_more_work():
    state,_=started_pair();context=state.backend_context;original=native.fsum
    def forbidden(*a,**k):raise AssertionError('mutated native intrinsic was executed')
    try:
        with pytest.raises(ValueError,match='drift'):
            with context.transaction():
                context.job.require_transaction().callback(lambda:setattr(native,'fsum',forbidden))
    finally:native.fsum=original

def test_foreign_callback_cannot_reenter_existing_native_world_plan():
    from ops_sim.v5.lifecycle_physics import PendingLifecycleAction
    from ops_sim.v5.long_mission import LongMissionAction
    state,_=started_pair();context=state.backend_context;p=state.physical
    pending=PendingLifecycleAction(LongMissionAction('callback-world','HOLD_UNTIL',until_seconds=188),128,188,p.attitude)
    with context.transaction():
        plan=native.prepare_world(p,p.harness.hardware,pending)
        before=native.native_entry_counts()
        with pytest.raises(ValueError,match='inactive|foreign|callback'):
            context.job.require_transaction().callback(plan.validate)
        assert native.native_entry_counts()==before

def test_actual_native_build_and_current_source_scope_are_consumed():
    b=build();module=admit_typed_build(b);assert module is native
    raw=dumps_root(root_for(600));source=current_source_binding();root,token=admit_job_root(raw,source,build_binding=b)
    state=start_lifecycle(root,backend=METHOD,source_binding=source,backend_build=b,job_admission=token)
    context=state.backend_context;assert context.selection==METHOD;assert context.job._validation is not None
    assert context.actual is not context.forecast
    before=context.receipt()['validation_control']['activations']
    with context.transaction():
        assert context.job._validation.closed();context.guard(root,state.model)
    assert context.receipt()['validation_control']['activations']==before+1

def started_pair():
    from ops_sim.v5.lifecycle_document import loads_root
    raw=dumps_root(root_for(600));b=build();source=current_source_binding()
    root,token=admit_job_root(raw,source,build_binding=b)
    return start_lifecycle(root,backend=METHOD,source_binding=source,backend_build=b,job_admission=token),start_lifecycle(loads_root(raw))

def test_b65_checkpoint_uses_its_exact_wrapper_family_and_rejects_retagging():
    from ops_sim.v5.lifecycle_checkpoint import checkpoint_bytes,make_bindings,admit_checkpoint,canonical
    from hashlib import sha256
    state,_=started_pair();binding=make_bindings(state.root,state.clock)
    raw=checkpoint_bytes(state,binding);value=admit_checkpoint(raw,state.root,sha256(raw).hexdigest(),binding)
    assert value['format']=='B65_TYPED_EXPOSURE_EXECUTION_CHECKPOINT_V2'
    assert value['backend']['format']=='B65_TYPED_BACKEND_CHECKPOINT_BINDING_V2'
    value['format']='B64_TYPED_EXPOSURE_EXECUTION_CHECKPOINT_V1';changed=canonical(value).encode()
    with pytest.raises(ValueError,match='family'):
        admit_checkpoint(changed,state.root,sha256(changed).hexdigest(),binding)

def test_machine_world_uses_original_grid_tail_and_same_paid_owner_caches():
    from fractions import Fraction as Q
    from ops_sim.v5.lifecycle_physics import PendingLifecycleAction,_forcing
    from ops_sim.v5.long_mission import LongMissionAction
    from ops_sim.v5.long_mission_continuation import _scientific
    # These pure assertions must not import the retired B64 binary merely to
    # compare the independently owned B65 and original F2 state.
    from dataclasses import asdict
    def encoded(value):
        return json.dumps(_scientific(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    def owner_data(physical):
        source=physical.source_authority
        return dict(orbit=physical.nominal_provider.to_data(),
            world={name:getattr(source,name)for name in ('controls','lookups','guards','sun_queries',
                'lighting_evaluations','lighting_evictions','peak_lighting_records')},
            lighting=deepcopy(source._lighting),runtime=asdict(physical.runtime_work))
    state,reference=started_pair();p=state.physical;old=reference.physical
    action=LongMissionAction('b65-grid-tail','HOLD_UNTIL',until_seconds=188)
    pending=PendingLifecycleAction(action,128,188,p.attitude)
    with state.backend_context.transaction():
        plan=native.prepare_world(p,p.harness.hardware,pending)
        for left,right in((128,129),(129,133),(133,138),(138,148),(138,148)):
            data=native.world_forcing(plan,Q(left),Q(right));forcing,eps=native.materialize_world_forcing(plan,data)
            ref,refeps,camera,panel,supports=_forcing(old,old.harness.hardware,Q(left),Q(right),old.attitude.quaternion)
            assert encoded((forcing,eps,data['camera'],data['panel'],data['supports']))==encoded((ref,refeps,camera,panel,supports))
            assert owner_data(p)==owner_data(old)
    receipt=state.backend_context.receipt()['validation_control']
    assert receipt['machine_world_steps']>0 and receipt['reference_world_steps']==0

def test_b65_fresh_paid_restore_is_zero_native_prefix_and_exact_science(monkeypatch):
    from hashlib import sha256
    from ops_sim.v5.lifecycle_checkpoint import checkpoint_bytes,make_bindings,prepare_checkpoint_restore,restore_checkpoint
    from ops_sim.v5.lifecycle_execution import scientific_projection
    from ops_sim.v5.lifecycle_document import loads_root
    state,_=started_pair();bindings=make_bindings(state.root,state.clock)
    raw=checkpoint_bytes(state,bindings);digest=sha256(raw).hexdigest();root_raw=dumps_root(state.root);b=build()
    root,admission=admit_job_root(root_raw,current_source_binding(),build_binding=b)
    token=prepare_checkpoint_restore(raw,root,digest,bindings,job_admission=admission)
    before=native.native_entry_counts()
    import ops_sim.v5.lifecycle_execution as execution
    import ops_sim.v5.orbit_j2_gravity as gravity
    def forbidden(*a,**k):raise AssertionError('numerical prefix during direct restore')
    monkeypatch.setattr(execution,'start_lifecycle',forbidden);monkeypatch.setattr(execution,'step_lifecycle',forbidden)
    monkeypatch.setattr(gravity,'_gravity',forbidden)
    restored,proof=restore_checkpoint(raw,root,digest,bindings,prepared=token)
    assert before==native.native_entry_counts();assert proof['native_entry_monitor']['total_delta']==0
    assert scientific_projection(restored)==scientific_projection(state)

@pytest.mark.parametrize('field,value',[
    ('platform','darwin'),('machine','aarch64'),('cache_tag','cpython-314t'),
    ('ext_suffix','.so'),('python','3.13.0 other'),('implementation','pypy')])
def test_native_profiles_reject_other_abis(field,value):
    r=runtime_binding();r[field]=value
    with pytest.raises(ValueError):profile_for(r)

def test_linux_profile_is_explicit_and_not_a_windows_wildcard():
    r=runtime_binding();r.update(platform='win32',machine='AMD64',ext_suffix='.cp314-win_amd64.pyd')
    assert profile_for(r)==WINDOWS
    r.update(platform='linux',machine='x86_64',ext_suffix='.cpython-314-x86_64-linux-gnu.so')
    assert profile_for(r)==LINUX
    b=build();b['runtime']=r;b['profile']=WINDOWS
    with pytest.raises(ValueError):admit_build_data(b)

@pytest.mark.parametrize('field,value', [('execution_domain','B64_TYPED_EXECUTION_V1'),('profile','OTHER_TARGET'),('format','other')])
def test_native_receipt_family_cannot_be_relabelled(field,value):
    b=build()
    if field=='profile':value=LINUX if b['profile']==WINDOWS else WINDOWS
    b[field]=value
    with pytest.raises(ValueError):admit_build_data(b)
