"""B54 structural optimization guards; numerical owners remain unchanged."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from fractions import Fraction
import json
import pytest

from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot,LifecyclePolicy
from ops_sim.v5.lifecycle_study import common_study_input,compile_study_base
from ops_sim.v5.lifecycle_quiet import QuietIntegrationPolicy
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
from ops_sim.v5.lifecycle_execution import start_lifecycle,step_lifecycle,scientific_projection
from ops_sim.v5.lifecycle_admission import (AdmittedInputs,CompiledLifecycleContext,
    COMPILED,BASELINE,MAX_WRAPPER_UNITS,validate_wrapper_data)
from ops_sim.v5.continuation import checked_checkpoint
from ops_sim.v5.lifecycle_checkpoint import checkpoint_bytes,make_bindings,restore_checkpoint


@pytest.fixture(scope='module')
def root():
    study=common_study_input()
    base=compile_study_base(make_inputs(wire='nominal'),study)
    return LifecycleRoot(base,600,policy=LifecyclePolicy(latency_seconds=study.latency_seconds,
        quiet_solver=QuietIntegrationPolicy()),study=study,output_policy=LifecycleStreamPolicy())


def test_compiled_and_baseline_same_root_exact_scientific_state(root):
    a=start_lifecycle(root,execution_mode=BASELINE)
    b=start_lifecycle(root,execution_mode=COMPILED)
    assert scientific_projection(a)==scientific_projection(b)
    assert b.compiled_context.actual is not b.compiled_context.forecast
    assert b.compiled_context.actual.work is not b.compiled_context.forecast.work
    while a.status=='ACTIVE':
        a,ae,ar=step_lifecycle(a);b,be,br=step_lifecycle(b)
        assert ae==be and ar==br and scientific_projection(a)==scientific_projection(b)
    work=b.compiled_context.to_data()
    assert work['actual']['dynamic_checkpoint_checks']>0
    assert work['forecast']['full_input_admissions']==1


def test_detailed_600_seconds_baseline_compiled_all_events_and_final_science_exact(root):
    detailed=replace(root,policy=replace(root.policy,quiet_solver=None))
    a=start_lifecycle(detailed,execution_mode=BASELINE)
    b=start_lifecycle(detailed,execution_mode=COMPILED)
    kinds=set();count=0
    assert a.physical.quiet_controller is b.physical.quiet_controller is None
    while a.status=='ACTIVE':
        a,ae,ar=step_lifecycle(a);b,be,br=step_lifecycle(b)
        kinds.add(ae['kind']);count+=1
        assert ae==be and ar==br
        assert b.physical.context.inputs is b.compiled_context.actual.inputs
        assert scientific_projection(a)==scientific_projection(b)
    assert a.status==b.status=='COMPLETE'
    assert a.clock==b.clock==detailed.start_seconds+600
    assert count>1 and {'POINT','CAPTURE','CONTACT','HOLD_UNTIL'}<=kinds
    assert scientific_projection(a)==scientific_projection(b)


def test_cached_checkpoint_keeps_dynamic_roundtrip_and_does_not_readmit_inputs(root,monkeypatch):
    s=start_lifecycle(root,execution_mode=COMPILED);owner=s.compiled_context.actual
    import ops_sim.v5.lifecycle_admission as admission
    def forbidden(*a,**k):raise AssertionError('no static constructor decoding on cache hit')
    monkeypatch.setattr(admission,'canonical_content',forbidden)
    got=owner.checked_checkpoint(s.physical.context)
    assert got==checked_checkpoint(s.physical.context)
    assert owner.work['dynamic_checkpoint_checks']>=2


@pytest.mark.parametrize('mutation',('clock_bool','clock_negative','energy_bool','energy_nan',
    'energy_negative','retention_zero','throughput_negative','temperature_nan','storage_wrong_type'))
def test_all_mutable_context_guards_still_reject(root,mutation):
    s=start_lifecycle(root,execution_mode=COMPILED)
    context=deepcopy(s.physical.context,{id(s.model.simulation_inputs):s.model.simulation_inputs})
    if mutation=='clock_bool':context.simulation_time_seconds=True
    elif mutation=='clock_negative':context.simulation_time_seconds=-1
    elif mutation=='energy_bool':context.spacecraft_state.battery.energy_wh=True
    elif mutation=='energy_nan':context.spacecraft_state.battery.energy_wh=float('nan')
    elif mutation=='energy_negative':context.spacecraft_state.battery.energy_wh=-1.
    elif mutation=='retention_zero':context.spacecraft_state.degradation.battery.usable_capacity_retention=0.
    elif mutation=='throughput_negative':context.spacecraft_state.degradation.battery.cumulative_energy_throughput_wh=-1.
    elif mutation=='temperature_nan':context.spacecraft_state.thermal.node_states[0].temperature_k=float('nan')
    else:context.spacecraft_state.data_storage.stored_records=[]
    with pytest.raises((ValueError,TypeError)):checked_checkpoint(context)
    with pytest.raises((ValueError,TypeError)):s.compiled_context.actual.checked_checkpoint(context)


@pytest.mark.parametrize('value',(0,0.,-0.,1,1.25))
def test_exact_dynamic_numeric_distinctions_match_old_helper(root,value):
    s=start_lifecycle(root,execution_mode=COMPILED)
    s.physical.context.spacecraft_state.battery.energy_wh=value
    baseline=checked_checkpoint(s.physical.context)
    fast=s.compiled_context.actual.checked_checkpoint(s.physical.context)
    from ops_sim.v5.experiment_codec import canonical_content
    assert canonical_content(baseline)==canonical_content(fast)


def test_deep_mutation_cannot_reuse_static_trust(root):
    s=start_lifecycle(root,execution_mode=COMPILED)
    inputs=deepcopy(s.model.simulation_inputs)
    owner=AdmittedInputs(inputs,root.identity,s.compiled_context.source_identity,'ACTUAL')
    target=inputs.spacecraft_configuration.eps.battery.nominal_energy_wh
    object.__setattr__(target,'value',target.value+1.)
    with pytest.raises(ValueError,match='immutable input field changed'):owner.guard(inputs)
    assert owner.work['guards_failed']==1 and owner.work['guards_reserved']==1


@pytest.mark.parametrize('field',('_numerator','_denominator'))
def test_fraction_in_genuine_admitted_parameter_cannot_mutate_in_place(root,field):
    s=start_lifecycle(root,execution_mode=COMPILED)
    inputs=deepcopy(s.model.simulation_inputs)
    parameter=inputs.spacecraft_configuration.eps.battery.nominal_energy_wh
    number=Fraction(parameter.value)
    object.__setattr__(parameter,'value',number)
    owner=AdmittedInputs(inputs,root.identity,s.compiled_context.source_identity,'ACTUAL')
    owner.guard(inputs)
    object.__setattr__(number,field,getattr(number,field)+1)
    with pytest.raises(ValueError,match='Fraction authority changed'):owner.guard(inputs)
    assert owner.work['guards_failed']==1


@pytest.mark.parametrize('field',('_name_','_value_'))
def test_enum_used_by_actual_hardware_cannot_mutate_in_place(root,field):
    s=start_lifecycle(root,execution_mode=COMPILED);owner=s.compiled_context.actual
    member=s.model.simulation_inputs.spacecraft_configuration.payload.payload_family
    original=getattr(member,field)
    try:
        object.__setattr__(member,field,'B54_INJECTED_ENUM_DRIFT')
        with pytest.raises(ValueError,match='enum authority changed'):owner.guard(owner.inputs)
    finally:object.__setattr__(member,field,original)
    owner.guard(owner.inputs)


def test_equal_foreign_graph_other_root_role_and_runtime_reject(root,monkeypatch):
    s=start_lifecycle(root,execution_mode=COMPILED);owner=s.compiled_context.actual
    with pytest.raises(ValueError,match='foreign'):owner.guard(deepcopy(owner.inputs))
    with pytest.raises(ValueError,match='foreign'):owner.guard(owner.inputs,root_identity='0'*64)
    with pytest.raises(ValueError,match='foreign'):owner.guard(owner.inputs,role='FORECAST')
    import ops_sim.v5.lifecycle_admission as admission
    monkeypatch.setattr(admission,'_runtime_token',lambda:('changed',))
    with pytest.raises(ValueError,match='foreign'):owner.guard(owner.inputs)


def test_global_codec_schema_drift_rejects_before_cached_dynamic_work(root,monkeypatch):
    s=start_lifecycle(root,execution_mode=COMPILED);owner=s.compiled_context.actual
    from ops_sim.v5._experiment_types import RECORD_FIELDS
    cls=type(owner.inputs)
    monkeypatch.setitem(RECORD_FIELDS,cls,tuple(list(RECORD_FIELDS[cls])))
    prior=owner.work['dynamic_checkpoint_checks']
    with pytest.raises(ValueError,match='schema replaced'):owner.checked_checkpoint(s.physical.context)
    assert owner.work['dynamic_checkpoint_checks']==prior


def test_wrapper_quota_refuses_prospectively_without_refund(root):
    s=start_lifecycle(root,execution_mode=COMPILED);owner=s.compiled_context.actual
    owner.work['control_units_reserved']=MAX_WRAPPER_UNITS
    before=dict(owner.work)
    with pytest.raises(ValueError,match='QUOTA_BEFORE_WORK'):owner.guard(owner.inputs)
    assert owner.work==before


def test_compiled_checkpoint_rebuilds_trust_inherits_wrapper_work_and_future_exact(root):
    s=start_lifecycle(root,execution_mode=COMPILED)
    while s.clock<300:s,_,_=step_lifecycle(s)
    bindings=make_bindings(root,s.clock);raw=checkpoint_bytes(s,bindings)
    document=json.loads(raw)
    assert document['format']=='B54_COMPILED_WRAPPER_CHECKPOINT_V3' and document['version']==3
    before=deepcopy(document['wrapper'])
    restored,proof=restore_checkpoint(raw,root,sha256(raw).hexdigest(),bindings)
    assert proof['retained_prior_static_admission_wrapper']==before
    assert proof['retained_prior_static_admission_wrapper'] is not document['wrapper']
    assert scientific_projection(s)==scientific_projection(restored)
    assert restored.compiled_context.actual is not s.compiled_context.actual
    for role in ('actual','forecast'):
        after=restored.compiled_context.to_data()[role]
        assert after['full_input_admissions']==before[role]['full_input_admissions']+1
        assert all(after[k]>=v for k,v in before[role].items())
    while s.status=='ACTIVE':s,_,_=step_lifecycle(s)
    while restored.status=='ACTIVE':restored,_,_=step_lifecycle(restored)
    assert scientific_projection(s)==scientific_projection(restored)


@pytest.mark.parametrize('field',('method','root_identity','source_identity','actual'))
def test_wrapper_document_cannot_acquire_foreign_cached_trust(root,field):
    s=start_lifecycle(root,execution_mode=COMPILED);data=s.compiled_context.to_data()
    if field=='method':data[field]='UNDECLARED'
    elif field=='actual':data[field]['guards_completed']+=1
    else:data[field]='unknown'
    with pytest.raises((TypeError,ValueError)):validate_wrapper_data(data)


def test_invalid_execution_mode_refuses_and_legacy_stays_baseline(root):
    with pytest.raises(ValueError):start_lifecycle(root,execution_mode=True)
    legacy=LifecycleRoot(make_inputs(wire='weakness'),60,sun_mode='BOUND_SHORT_TABLE_V1')
    assert start_lifecycle(legacy).compiled_context is None
    with pytest.raises(ValueError,match='explicitly versioned'):start_lifecycle(legacy,execution_mode=COMPILED)
