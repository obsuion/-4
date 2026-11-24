"""Real B64 source/build/root consumer boundaries, no campaign timings."""
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
import json
import pytest

from lifetime_support import root_for
from ops_sim.v5.lifecycle_backend import current_source_binding, service_call
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.lifecycle_execution import start_lifecycle
from ops_sim.v5.lifecycle_job_prepared import admit_job_root
from ops_sim.v5.lifecycle_typed_context import TypedBackendContext, TypedContactBinding
from ops_sim.v5.lifecycle_typed_backend import SUPPORT_DOMAIN,FULL_DOMAIN
from ops_sim.v5.lifecycle_state import guard_lifecycle
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.construction_service import service_physical_substep
from ops_sim.v5.long_mission_continuation import _scientific


SOURCE=Path(__file__).resolve().parents[1]
def encoded(value):
    return json.dumps(_scientific(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def receipt():
    return json.loads((SOURCE/'ops_sim/v5/lifecycle_typed_build_receipt.json').read_bytes())

def admitted(raw=None):
    raw=dumps_root(root_for(60))if raw is None else raw
    build=receipt();source=current_source_binding()
    root,token=admit_job_root(raw,source,build_binding=build)
    return root,token,build,source

def started(raw=None):
    root,token,build,source=admitted(raw)
    state=start_lifecycle(root,backend=build['execution_domain'],source_binding=source,
        backend_build=build,job_admission=token)
    return state,token,build,source


def test_real_start_consumes_one_shared_job_preparation_and_independent_roles():
    state,token,build,source=started()
    ctx=state.backend_context
    assert type(ctx)is TypedBackendContext
    assert ctx.model is state.model and ctx.root is state.root
    assert ctx.actual is not ctx.forecast and ctx.actual._cache is not ctx.forecast._cache
    assert ctx.actual.model is ctx.forecast.model is ctx.job.static.model
    assert ctx.actual._work is not ctx.forecast._work
    work=ctx.job.receipt()['preparation']
    assert work['raw_admissions']==1 and work['model_build_attempts']==work['model_build_completed']==1
    assert work['static_copy_attempts']==work['static_copy_completed']==1
    assert work['phase']=='CONSUMED'
    with pytest.raises(ValueError,match='consumed|stale'):
        start_lifecycle(state.root,backend=build['execution_domain'],source_binding=source,
            backend_build=build,job_admission=token)
    guard_lifecycle(state)


def test_foreign_build_rejected_before_owned_model_preparation():
    root,token,build,source=admitted()
    altered=deepcopy(build);altered['execution_domain']=SUPPORT_DOMAIN if build['execution_domain']==FULL_DOMAIN else FULL_DOMAIN
    with pytest.raises(ValueError,match='build|quiet|domain'):
        start_lifecycle(root,backend=build['execution_domain'],source_binding=source,
            backend_build=altered,job_admission=token)


def test_external_root_mutation_is_detected_at_selected_boundary():
    state,_,_,_=started();root=state.root;old=root.duration_seconds
    try:
        object.__setattr__(root,'duration_seconds',old+1)
        with pytest.raises(ValueError,match='drift|identity|authority'):
            guard_lifecycle(state)
    finally:object.__setattr__(root,'duration_seconds',old)
    guard_lifecycle(state)


@pytest.mark.parametrize('name',('_function_pins','_function_retained'))
def test_owned_function_reference_collections_cannot_be_replaced(name):
    state,_,_,_=started();ctx=state.backend_context
    original=getattr(ctx,name)
    assert type(original)is tuple and original
    before=ctx.native.native_entry_counts()
    try:
        setattr(ctx,name,())
        with pytest.raises(ValueError,match='activation|callable'):
            with ctx.transaction():
                raise AssertionError('tampered reference collection entered transaction')
    finally:setattr(ctx,name,original)
    assert ctx.native.native_entry_counts()==before
    guard_lifecycle(state)


def test_actual_contact_token_requires_active_exact_job_transaction():
    state,_,_,_=started();ctx=state.backend_context
    with pytest.raises(ValueError,match='transaction'):
        TypedContactBinding(state.physical)
    with ctx.transaction():
        binding=TypedContactBinding(state.physical)
        binding.check_context(state.physical.context)
        foreign=deepcopy(state.physical.context)
        with pytest.raises(ValueError,match='foreign'):
            binding.check_context(foreign)


def test_actual_service_consumer_accepts_fresh_derived_limits_and_keeps_static_seals():
    from test_lifecycle_native_state import arguments
    state,_,_,_=started();physical=state.physical;ctx=state.backend_context
    with ctx.transaction():
        args,kw=arguments(physical)
        assert kw['limits']is not state.model.construction_limits
        from ops_sim.v5.operational_protection import validate_policy
        contact_policy=validate_policy(args[4],physical.context)
        assert contact_policy is not args[4]
        args=(*args[:4],contact_policy,args[5])
        # The authority is this exact admitted derived-property value, not a
        # pointer that the original property never promised to retain.
        reference_context=deepcopy(args[0],{id(args[0].inputs):args[0].inputs})
        reference_kwargs=dict(kw)
        for name in ('work','service_work','battery_port_work'):
            reference_kwargs[name]=deepcopy(kw[name])
        expected=service_physical_substep(reference_context,*args[1:],**reference_kwargs)
        returned=service_call(physical,service_physical_substep,*args,**kw)
        assert encoded(returned)==encoded(expected)
        assert encoded(CheckpointState.from_context(physical.context))==encoded(CheckpointState.from_context(reference_context))
        for name in ('work','service_work','battery_port_work'):
            assert asdict(kw[name])==asdict(reference_kwargs[name])
        ctx.guard(state.root,state.model)
    assert ctx.receipt()['static_preparations']==1
    assert ctx.receipt()['typed_static_control_units']>0


@pytest.mark.parametrize('mutation',('foreign_port_work','changed_policy','changed_routing'))
def test_coupled_consumer_rejects_foreign_small_authority_before_kernel(mutation):
    from test_lifecycle_native_state import arguments
    state,_,_,_=started();physical=state.physical;ctx=state.backend_context
    with ctx.transaction():
        args,kw=arguments(physical)
        if mutation=='foreign_port_work':kw['battery_port_work']=deepcopy(kw['battery_port_work'])
        elif mutation=='changed_policy':args=(*args[:4],replace(args[4],rationale=args[4].rationale+' changed'),args[5])
        else:
            # Still a valid routing value, but foreign to this owned model:
            # the adapter may not silently overwrite a different heat fraction.
            original=args[2].routing_config;route=original.routes[0]
            fraction=route.retained_heat_fraction
            changed=replace(route,retained_heat_fraction=replace(fraction,value=.5 if fraction.value!=.5 else .25))
            routing=replace(original,routes=(changed,*original.routes[1:]))
            args=(args[0],args[1],replace(args[2],routing_config=routing),*args[3:])
        before=ctx.native.native_entry_counts()
        with pytest.raises((ValueError,TypeError),match='authority|routing|static|None'):
            service_call(physical,service_physical_substep,*args,**kw)
        assert ctx.native.native_entry_counts()==before


def test_typed_checkpoint_uses_fresh_paid_admission_and_no_native_prefix(tmp_path):
    from ops_sim.v5.lifecycle_checkpoint import (make_bindings,checkpoint_bytes,
        prepare_checkpoint_restore,restore_checkpoint,CHECKPOINT_FORMAT64)
    state,_,build,source=started();raw_input=dumps_root(state.root)
    bindings=make_bindings(state.root,state.clock)
    with state.backend_context.transaction():raw=checkpoint_bytes(state,bindings)
    assert json.loads(raw)['format']==CHECKPOINT_FORMAT64
    sha=sha256(raw).hexdigest();path=tmp_path/'typed.cp.json';path.write_bytes(raw)
    root,token,_,_=admitted(raw_input)
    prep=prepare_checkpoint_restore(path,root,sha,bindings,job_admission=token)
    from ops_sim.v5 import _lifecycle_typed
    before=_lifecycle_typed.native_entry_counts()
    restored,proof=restore_checkpoint(path,root,sha,bindings,prepared=prep)
    after=_lifecycle_typed.native_entry_counts()
    assert before==after
    assert encoded(CheckpointState.from_context(restored.physical.context))==encoded(CheckpointState.from_context(state.physical.context))
    assert restored.backend_context.actual is not restored.backend_context.forecast
    assert proof['native_entry_monitor']['total_delta']==0
    assert proof['preparation']['logical_control_units']>=2*524288
    with pytest.raises(ValueError,match='single-use'):
        restore_checkpoint(path,root,sha,bindings,prepared=prep)
