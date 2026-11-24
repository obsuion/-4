"""Typed static ownership and finite DATA admission, not campaigns."""
from dataclasses import replace
from copy import copy
import pytest
from ops_sim.v5 import _lifecycle_typed as typed
from ops_sim.v5.lifecycle_typed_state import indexed_static_data,prepare_typed_static,service_port_substep
from ops_sim.v5.integration_time import RationalSeconds
from ops_sim.v5.lifecycle_prepared import _Seal
from test_battery_port_coupling import leaf


def setup_static():
    s,f,e,origin,port,allocation,kw=leaf()
    st=prepare_typed_static(s.context.inputs.spacecraft_configuration,kw['compilation'],kw['service_policy'],
        kw['battery_port_policy'],s.inputs.protection,s.inputs.routing,kw['limits'],module=typed)
    return s,f,e,kw,st


def test_static_indices_are_private_bounded_and_scientific_work_not_reset():
    s,f,e,kw,st=setup_static()
    shape=st.compiled.shape()
    assert shape['nodes']==len(st.ids) and shape['branches']==8 and shape['loads']==7
    assert shape['storage']=='PRIVATE_C_DOUBLE_ARRAYS'
    assert st.compilation is kw['compilation']
    st.guard()
    assert not hasattr(st.compiled,'capacity')


def test_indexed_static_reinitialization_refuses_before_constants_or_work_change():
    from dataclasses import asdict
    import json
    from ops_sim.v5.checkpoint import CheckpointState
    from ops_sim.v5.construction_service import service_physical_substep
    from ops_sim.v5.long_mission_continuation import _scientific
    s,f,e,kw,st=setup_static()
    changed=indexed_static_data(st.configuration,st.compilation,st.service_policy,st.port_policy,
        st.protection,st.routing,st.limits)
    changed.update(nominal_energy=123.,nominal_solar=37.,charge_limit=11.,discharge_limit=19.)
    changed['nodes']=((changed['nodes'][0][0]*1.25,*changed['nodes'][0][1:]),*changed['nodes'][1:])
    before=typed.native_entry_counts()
    separate=typed.IndexedStatic(changed)  # valid changed DATA, separate ownership
    assert separate is not st.compiled and separate.shape()==st.compiled.shape()
    with pytest.raises(TypeError,match='cannot be reinitialized'):
        st.compiled.__init__(changed)
    with pytest.raises(TypeError,match='cannot be reinitialized'):
        typed.IndexedStatic.__init__(st.compiled,changed)
    with pytest.raises(TypeError,match='cannot be reinitialized'):
        st.compiled.__init__(None)  # one-shot gate precedes input admission
    assert not hasattr(st.compiled,'_initialized') and not hasattr(st.compiled,'__dict__')
    assert typed.native_entry_counts()==before
    st.guard()
    actual=service_port_substep(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,compiled_static=st,**kw)
    r,rf,re,origin,port,allocation,rkw=leaf()
    expected=service_physical_substep(r.context,RationalSeconds(1,1),rf,re,r.inputs.protection,None,**rkw)
    def result(value,context,options):
        return json.dumps(_scientific((value,CheckpointState.from_context(context),
            asdict(options['service_work']),asdict(options['battery_port_work']),asdict(options['work']))),
            sort_keys=True,separators=(',',':'),allow_nan=False)
    assert result(actual,s.context,kw)==result(expected,r.context,rkw)


def test_uninitialized_failed_and_subclass_static_instances_cannot_gain_authority():
    s,f,e,kw,st=setup_static()
    from ops_sim.v5.lifecycle_typed_state import _dynamic
    dynamic=_dynamic(st,s.context,kw['battery_port_state'])
    before=typed.native_entry_counts()
    raw=typed.IndexedStatic.__new__(typed.IndexedStatic)
    failed=typed.IndexedStatic.__new__(typed.IndexedStatic)
    with pytest.raises(TypeError,match='exact indexed input DATA'):failed.__init__(None)
    with pytest.raises(TypeError,match='cannot be reinitialized'):failed.__init__({})
    class Foreign(typed.IndexedStatic):
        def __init__(self):pass
    foreign=Foreign()
    with pytest.raises(TypeError,match='exact indexed static owner'):
        typed.IndexedStatic.__init__(foreign,{})
    for model in (raw,failed,foreign):
        with pytest.raises(TypeError,match='not initialized'):model.shape()
        with pytest.raises(TypeError,match='not initialized'):typed.TypedDynamic(model,{})
        with pytest.raises(TypeError,match='not initialized'):
            typed.coupled_cut(model,dynamic,{},kw['service_work'],kw['battery_port_work'],kw['work'],kw['limits'])
    assert typed.native_entry_counts()==before


def test_static_admission_preserves_every_original_owned_edge():
    s,f,e,origin,port,allocation,kw=leaf()
    spacecraft=s.context.inputs.spacecraft_configuration
    configuration=kw['compilation'].configuration
    ports=configuration.ports
    authority=(spacecraft,kw['compilation'],kw['service_policy'],
        kw['battery_port_policy'],s.inputs.protection,s.inputs.routing,kw['limits'])
    seal=_Seal(authority)
    st=prepare_typed_static(spacecraft,kw['compilation'],kw['service_policy'],
        kw['battery_port_policy'],s.inputs.protection,s.inputs.routing,kw['limits'],module=typed)
    seal.guard()
    assert configuration.ports is ports
    assert st.configuration is configuration and st.spacecraft is spacecraft


def test_constructor_validation_runs_on_a_detached_configuration(monkeypatch):
    s,f,e,origin,port,allocation,kw=leaf()
    configuration=kw['compilation'].configuration
    owner=type(configuration);original=owner.__post_init__;seen=[]
    def checked(self):
        assert self is not configuration
        seen.append(self)
        return original(self)
    monkeypatch.setattr(owner,'__post_init__',checked)
    st=prepare_typed_static(s.context.inputs.spacecraft_configuration,kw['compilation'],kw['service_policy'],
        kw['battery_port_policy'],s.inputs.protection,s.inputs.routing,kw['limits'],module=typed)
    assert seen and all(item is not configuration for item in seen)
    st.guard()


def test_detached_constructor_keeps_original_domain_refusal():
    s,f,e,kw,st=setup_static()
    invalid=copy(st.configuration)
    object.__setattr__(invalid,'bus_voltage_v',-1.)
    seal=_Seal(st.configuration)
    with pytest.raises(ValueError):
        indexed_static_data(invalid,st.compilation,st.service_policy,st.port_policy,
            st.protection,st.routing,st.limits)
    seal.guard()


def test_changed_static_source_fails_boundary_seal():
    s,f,e,kw,st=setup_static()
    obj=st.compilation.branches[0].wire
    old=obj.current_limit_a
    try:
        object.__setattr__(obj,'current_limit_a',old+.25)
        with pytest.raises(ValueError,match='drift'):st.guard()
    finally:object.__setattr__(obj,'current_limit_a',old)


def test_equal_foreign_static_pointer_rejected_without_fee():
    s,f,e,kw,st=setup_static()
    kw['compilation']=replace(kw['compilation'])
    before=kw['service_work'].allocation_trials
    with pytest.raises(ValueError,match='foreign coupled static'):
        service_port_substep(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,compiled_static=st,**kw)
    assert kw['service_work'].allocation_trials==before


def test_changed_compiled_kernel_refuses_before_work(monkeypatch):
    s,f,e,kw,st=setup_static()
    before=kw['service_work'].allocation_trials
    def forbidden(*args,**kwargs):raise AssertionError('foreign kernel was called')
    monkeypatch.setattr(typed,'coupled_cut',forbidden)
    with pytest.raises(ValueError,match='changed compiled numerical callable'):
        service_port_substep(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,compiled_static=st,**kw)
    assert kw['service_work'].allocation_trials==before


@pytest.mark.parametrize('change',[
    lambda d:d.update(nodes=()),
    lambda d:d.update(branches=d['branches'][:-1]),
    lambda d:d.update(priority=(0,0,1,2,3,4,5)),
    lambda d:d.update(bisections=True),
    lambda d:d.update(bus_voltage=2**200),
    lambda d:d.update(nodes=((float('nan'),*d['nodes'][0][1:]),*d['nodes'][1:])),
])
def test_malformed_or_unsupported_index_data_refuses_before_numerical_entry(change):
    s,f,e,kw,st=setup_static()
    data=indexed_static_data(st.configuration,st.compilation,st.service_policy,st.port_policy,st.protection,st.routing,st.limits)
    change(data)
    before=typed.native_entry_counts()
    with pytest.raises((TypeError,ValueError,OverflowError)):typed.IndexedStatic(data)
    assert typed.native_entry_counts()==before
